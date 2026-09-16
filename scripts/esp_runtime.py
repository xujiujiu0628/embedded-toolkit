"""ESP32 运行时后端 (F-174 esp32s3 pilot) — idf.py 构建 / esptool 烧录 / UART 采集.

设计: docs/specs/2026-09-16-esp32s3-pilot-design.md
纪律:
- 机器路径只允许存在于 machine.json (esp_idf_path / esp_tools_dir);
- 子进程成败只信 returncode (F-090 同源教训, OpenOCD 日志走 stderr 的同款坑);
- idf.py / esptool 依赖 export.ps1 注入的环境, 统一经 run_idf 单点封装
  (PowerShell 会话内 source 后顺序执行, 逐命令 $LASTEXITCODE 门闩传播退出码)。
"""
import glob
import json
import os
import subprocess
import time

from wb_common import load_machine

_PANIC_MARKERS = ("Guru Meditation", "Backtrace:", "abort() was called",
                  "assert failed", "Heap corruption")


class EspConfigError(RuntimeError):
    """machine.json 缺 esp_idf_path 或目录不存在 — 友好报错不裸 traceback"""


def resolve_idf_path() -> str:
    m = load_machine()
    path = m.get("esp_idf_path", "")
    if not path or not os.path.isdir(path):
        raise EspConfigError(
            f"machine.json esp_idf_path 未配置或目录不存在: {path!r} — "
            "真机构建/烧录前请填入 ESP-IDF 根目录绝对路径")
    return path


def _idf_env() -> dict:
    """子进程 env: IDF_TOOLS_PATH 指到 machine.json 的 esp_tools_dir.

    export.ps1 找不到工具会去默认 %USERPROFILE%\\.espressif 兜底——装在哪
    就必须告诉它去哪找, 键缺省时不注入 (回落 IDF 官方默认)。"""
    env = os.environ.copy()
    tools = load_machine().get("esp_tools_dir", "")
    if tools:
        env["IDF_TOOLS_PATH"] = tools
    return env


def run_idf(ps_commands: list[str], timeout: int, workspace: str,
            *, _run=subprocess.run) -> dict:
    """在 export.ps1 环境里顺序执行 PowerShell 命令串.

    导出脚本失败不单独拦——下一条命令必炸且报错更具体。
    返回 {status, returncode, output} (output = stdout+stderr 合并) 或
    超时 {status:"error", message}。_run 注入点供 host 单测。"""
    idf = resolve_idf_path()
    export = os.path.join(idf, "export.ps1").replace("\\", "/")  # PS 单引号不吃反斜杠转义
    export = export.replace("'", "''")  # PS 单引号串内 ' 只能翻倍转义 (Task 2 审查裁决)
    parts = [f". '{export}'"]
    for c in ps_commands:
        parts.append(c)
        parts.append("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-Command", "; ".join(parts)]
    try:
        proc = _run(cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout, cwd=workspace,
                    env=_idf_env())
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"idf 子进程超时 ({timeout}s)"}
    return {"status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "output": (proc.stdout or "") + (proc.stderr or "")}


def detect_esp_panic(text: str) -> bool:
    """ESP panic 只做文本级标记 (spec §4.3): 符号化解析后置另票。"""
    return any(m in text for m in _PANIC_MARKERS)


def step_build_idf(config: dict, rebuild: bool = False,
                   workspace: str | None = None,
                   *, _run_idf=None) -> dict:
    """builder=idf (F-174): idf.py build, 契约对齐 gcc_build (spec §4.2)。

    metrics 从合并日志行计数 ("error:" 行 + ninja "FAILED:" 行);
    成败判据: run_idf rc==0 且 errors==0, 两者缺一即 error。
    _run_idf 注入点供单测 (默认走模块级 run_idf)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    cfg = (config or {}).get("idf", {}) or {}
    commands = (["idf.py fullclean"] if rebuild else []) + ["idf.py build"]
    run = run_idf_(commands, timeout=int(cfg.get("build_timeout", 900)),
                   workspace=ws)
    output = run.get("output", "")

    log_dir = os.path.join(ws, ".workbench", "build")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "idf_build.log")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    errors = sum(1 for ln in output.splitlines()
                 if "error:" in ln or "FAILED:" in ln)
    warnings = sum(1 for ln in output.splitlines() if "warning:" in ln)
    metrics = {"errors": errors, "warnings": warnings}
    details = {"log_file": os.path.relpath(log_file, ws).replace(os.sep, "/")}

    if run.get("status") != "ok" or errors > 0:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": (f"idf build failed "
                            f"(rc={run.get('returncode', '?')}, {errors} errors)"),
                "stderr": output[-500:]}

    bins = sorted(glob.glob(os.path.join(ws, "build", "*.bin")))
    elfs = sorted(glob.glob(os.path.join(ws, "build", "*.elf")))
    if not bins:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": "idf build ok 但 build/*.bin 缺失 (先 set-target?)",
                "stderr": output[-300:]}
    bin_rel = os.path.relpath(bins[0], ws).replace(os.sep, "/")
    elf_rel = (os.path.relpath(elfs[0], ws).replace(os.sep, "/")
               if elfs else "")
    details.update({"hex_file": bin_rel, "bin_file": bin_rel,
                    "elf_file": elf_rel})
    _write_last_build(ws, bin_rel, elf_rel)
    return {"status": "ok", "metrics": metrics, "details": details,
            "summary": f"idf build ok ({warnings} warnings)"}


def step_flash_esptool(flash_cfg: dict, workspace: str | None = None,
                       *, _run_idf=None) -> dict:
    """flash.backend=esptool (F-174): 经 idf.py -p <port> flash 烧录.

    选 idf.py flash 而非手拼 esptool write_flash 地址表: flash_args 由构建
    系统生成 (bootloader/分区表/app 三镜像+offset), 手拼即漂移 (spec §4.2)。
    结束自带 --after hard-reset, capture 段仍显式再复位一次 (确定性起点)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    port = (flash_cfg.get("port") or "").strip()
    if not port:
        return {"status": "error", "backend": "esptool",
                "message": "flash.port 未配置 (esptool 后端需要串口号, 如 COM3)"}
    run = run_idf_([f"idf.py -p {port} flash"],
                   timeout=int(flash_cfg.get("timeout", 300)), workspace=ws)
    out = run.get("output", "")
    if run.get("status") == "ok":
        return {"status": "ok", "backend": "esptool", "stdout": out[-1000:]}
    return {"status": "error", "backend": "esptool",
            "message": f"idf.py flash 失败 (port={port}, "
                       f"rc={run.get('returncode', '?')})",
            "stderr": out[-500:]}


def _write_last_build(ws: str, bin_rel: str, elf_rel: str) -> None:
    """state.json last_build (verify --no-build 回读契约, 与 gcc_build 同构)。

    hex_file 键复用 = .bin 路径: step_flash 的存在性检查与 --no-build
    读取逻辑零改动即可走通 esptool 后端。"""
    state_path = os.path.join(ws, ".workbench", "state.json")
    state = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["last_build"] = {"provider": "idf", "hex_file": bin_rel,
                           "bin_file": bin_rel, "elf_file": elf_rel,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
