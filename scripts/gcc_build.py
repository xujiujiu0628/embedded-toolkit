"""GNU 工具链构建后端 (make + arm-none-eabi-gcc)。

与 keil_build.py 同构契约, 供 verify.py 按 config.json builder 字段切换:
  - JSON 输出: {status, action, metrics{errors,warnings}, details{...}}
  - 写工程 .workbench/state.json last_build (provider="gcc")
  - 写回工程级配置 gcc 段 (project/target/log_dir)

机器路径唯一来源: toolkit/machine.json (gcc_path / make_exe)。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]  # embedded-toolkit/ (machine.json 所在)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wb_runtime import (  # noqa: E402
    JSONCorruptError,
    hidden_subprocess_kwargs,
    load_json_strict,
    load_project_config,
    make_timing,
    now_iso,
    output_json,
    save_json_file,
    workspace_root,
    update_state_entry,
)

MAKE_JOBS = 8


def load_machine() -> dict:
    """读 toolkit/machine.json (本机工具链绝对路径)。"""
    import json
    with open(ROOT_DIR / "machine.json", encoding="utf-8") as f:
        return json.load(f)


def _resolve_makefile(project: str, workspace: Path) -> tuple[Path, Path]:
    """project 可为 Makefile 路径或工程目录; 返回 (Makefile, 工程目录)。"""
    p = Path(project).expanduser()
    if not p.is_absolute():
        p = workspace / p
    if p.is_dir():
        p = p / "Makefile"
    return p, p.parent


def _makefile_vars(makefile: Path) -> dict:
    """从 Makefile 提取 TARGET / BUILD_DIR (最简正则, 足够 CubeMX 生成物)。"""
    vars_: dict[str, str] = {}
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return vars_
    for key in ("TARGET", "BUILD_DIR"):
        m = re.search(rf"^{key}\s*=\s*(\S+)", text, re.M)
        if m:
            vars_[key] = m.group(1)
    return vars_


def _parse_log_metrics(log_file: Path) -> dict:
    """从 GCC 构建日志解析 error/warning 计数 (GCC 格式: `file:line:col: error: ...`)。"""
    errors = warnings = 0
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"errors": -1, "warnings": -1}
    for line in lines:
        if re.search(r":\s*error\s*:", line, re.IGNORECASE) or \
           re.search(r"\berror\s*:\s*ld returned", line, re.IGNORECASE):
            errors += 1
        elif re.search(r":\s*warning\s*:", line, re.IGNORECASE):
            warnings += 1
    return {"errors": errors, "warnings": warnings}


def _collect_artifacts(project_dir: Path, makefile_vars: dict, target: str) -> dict:
    """收集构建产物 (与 keil_build._collect_target_artifacts 同构)。"""
    build_dir = makefile_vars.get("BUILD_DIR", "build")
    output_dir = project_dir / build_dir
    if not target:
        target = makefile_vars.get("TARGET", "main")
    stem = output_dir / target
    details = {
        "output_dir": str(output_dir),
        "elf_file": str(stem.with_suffix(".elf")),
        "hex_file": str(stem.with_suffix(".hex")),
        "bin_file": str(stem.with_suffix(".bin")),
        "map_file": str(stem.with_suffix(".map")),
    }
    details["debug_file"] = details["elf_file"]
    details["flash_file"] = details["hex_file"]
    return details


def merge_gcc_config(config_file: Path, makefile: Path, target: str,
                     log_path: Path, workspace: Path) -> dict:
    """写回工程级配置 gcc 段 (只改 gcc 段, 不碰其他段)。

    F-020: 配置损坏时抛 JSONCorruptError 拒绝写回 — 旧实现经 load_json_file
    把损坏当空文件, 写回后 config.json 只剩 gcc 段, 验证/采集/物理门控等
    其他段无声蒸发 (损坏被构建行为放大成数据丢失)。"""
    config_file, makefile = Path(config_file), Path(makefile)
    log_path, workspace = Path(log_path), Path(workspace)
    data = load_json_strict(config_file) if Path(config_file).exists() else {}
    data["gcc"] = {
        **data.get("gcc", {}),
        "project": str(makefile.relative_to(workspace) if makefile.is_relative_to(workspace) else makefile),
        "target": target,
        "log_dir": str(log_path.relative_to(workspace) if log_path.is_relative_to(workspace) else log_path),
    }
    save_json_file(config_file, data)
    return {"status": "ok"}


def _run_make(project_dir: Path, action: str, target: str, log_file: Path,
              machine: dict) -> subprocess.CompletedProcess[str]:
    """执行 make (PATH 前置 gcc/make 目录), 输出写入 log_file。"""
    gcc_path = machine.get("gcc_path", "")
    make_exe = machine.get("make_exe", "make")
    env = os.environ.copy()
    bin_dirs = [d for d in (gcc_path, str(Path(make_exe).parent)) if d]
    if bin_dirs:
        env["PATH"] = os.pathsep.join(bin_dirs + [env.get("PATH", "")])

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        with open(log_file, "a", encoding="utf-8", errors="replace") as log_fp:
            return subprocess.run(
                cmd,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                cwd=str(project_dir),
                env=env,
                timeout=300,
                **hidden_subprocess_kwargs(),
            )

    if action == "clean":
        return run([make_exe, "clean"] + ([f"TARGET={target}"] if target else []))
    if action == "rebuild":
        run([make_exe, "clean"] + ([f"TARGET={target}"] if target else []))
    return run([make_exe, f"-j{MAKE_JOBS}"] + ([f"TARGET={target}"] if target else []))


def main() -> None:
    parser = argparse.ArgumentParser(description="GNU 工具链构建 (make + arm-none-eabi-gcc)")
    parser.add_argument("action", choices=["build", "rebuild", "clean"])
    parser.add_argument("--project", default=None, help="Makefile 路径或工程目录")
    parser.add_argument("--target", default=None, help="make TARGET (可选, 默认读 Makefile)")
    parser.add_argument("--log-dir", default=None, help="日志输出目录")
    parser.add_argument("--workspace", default=None, help="workspace 根目录, 默认当前目录")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    machine = load_machine()

    # project: CLI > 工程级配置 gcc 段 > 默认 gcc-pilot/Makefile
    project_config = load_project_config(str(workspace))
    gcc_cfg = project_config.get("gcc", {}) if isinstance(project_config, dict) else {}
    project = args.project or gcc_cfg.get("project") or "gcc-pilot/Makefile"
    target = args.target or gcc_cfg.get("target") or ""
    log_dir = args.log_dir or gcc_cfg.get("log_dir") or ".workbench/build"

    makefile, project_dir = _resolve_makefile(project, workspace)
    log_path = Path(log_dir).expanduser()
    if not log_path.is_absolute():
        log_path = workspace / log_path
    log_path.mkdir(parents=True, exist_ok=True)
    stem = makefile.parent.name or "gcc"
    log_file = log_path / f"{stem}-{target or 'default'}-{args.action}.log"

    # 预检
    errors: list[str] = []
    if not makefile.is_file():
        errors.append(f"Makefile not found: {makefile}")
    if not machine.get("gcc_path") or not (Path(machine["gcc_path"]) / "arm-none-eabi-gcc.exe").exists():
        errors.append(f"gcc_path invalid in machine.json: {machine.get('gcc_path')}")
    if not machine.get("make_exe") or not Path(machine["make_exe"]).exists():
        errors.append(f"make_exe invalid in machine.json: {machine.get('make_exe')}")
    if errors:
        output_json({
            "status": "error",
            "action": args.action,
            "error": {"code": "precheck", "message": "; ".join(errors)},
        })
        return

    # 执行构建
    try:
        log_file.write_text("", encoding="utf-8")  # 清空旧日志
        proc = _run_make(project_dir, args.action, target, log_file, machine)
    except subprocess.TimeoutExpired:
        output_json({
            "status": "error",
            "action": args.action,
            "error": {"code": "timeout", "message": "make 执行超时 (300s)"},
        })
        return

    metrics = _parse_log_metrics(log_file)
    details = _collect_artifacts(project_dir, _makefile_vars(makefile), target)
    status = "ok" if proc.returncode == 0 and metrics["errors"] == 0 else "error"
    if args.action == "clean":
        status = "ok"

    result = {
        "status": status,
        "action": args.action,
        "metrics": metrics,
        "details": details,
        "timing_ms": make_timing(started_at, time.time() - started_ts),
        "started_at": started_at,
        "summary": f"{metrics['errors']} errors, {metrics['warnings']} warnings ({args.action})",
    }
    if status == "error":
        result["error"] = {
            "code": "make_failed",
            "message": f"make 退出码 {proc.returncode}, 日志: {log_file}",
        }

    # 写 state.json last_build (与 keil_build 同构, verify.py --no-build 依赖)
    if args.action in ("build", "rebuild") and status == "ok":
        artifacts = {k: details[k] for k in ("axf_file", "hex_file", "flash_file",
                                             "debug_file", "output_dir", "log_file") if k in details}
        artifacts["elf_file"] = details.get("elf_file")
        artifacts["hex_file"] = details.get("hex_file")
        artifacts["log_file"] = str(log_file)
        update_state_entry(
            "last_build",
            {
                "provider": "gcc",
                "action": args.action,
                "project": str(makefile),
                "target": target,
                "log_dir": str(log_path),
                "artifacts": artifacts,
                **artifacts,
            },
            str(workspace),
        )
        # 写回工程级配置 gcc 段 (F-020: 损坏拒绝写回, 结果随 JSON 出档留痕)
        config_file = workspace / ".workbench" / "config.json"
        try:
            result["config_writeback"] = merge_gcc_config(
                config_file, makefile, target, log_path, workspace)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 config.json 以免清空其他配置段: {e}",
                  file=sys.stderr)
            result["config_writeback"] = {"status": "skipped_corrupt",
                                          "reason": str(e)}

    output_json(result, indent=2)


if __name__ == "__main__":
    main()  # F-006: import time 已上移模块顶部 — 被未来调用方 import 时不再 NameError
