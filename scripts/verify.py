#!/usr/bin/env python3
"""
闭环验证编排器 — 一键完成 编译→分析→烧录→采集→验证

用法:
    python verify.py                        # 完整流程
    python verify.py --timeout 10           # 捕获 10 秒
    python verify.py --no-build             # 跳过编译 (用上次产物)
    python verify.py --no-flash             # 跳过烧录 (用已烧录固件)
    python verify.py --json                 # JSON 输出 (供 Claude 判断)

流程:
    1. Build   → gcc_build.py (默认 builder=gcc; 显式配 "keil" 时唤起 legacy 桥)
    2. Analyze → gcc 路径直传 build metrics; keil 路径走 legacy keil_analyze 知识库 (有 error 则终止)
    3. Flash   → OpenOCD program
    4. Capture → verify.py 内置双路: semihosting 内联会话 (默认) | rtt (capture.backend)
    4c. Physical → OpenOCD ODR 轮询 GPIO 翻转频率 (物理层门控, 默认 skipped)
    5. Output  → 结构化 JSON 结果, Claude 对比期望判断 ✅/❌
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta


WORKSPACE = None  # 工程根, main() 中 --project 或 cwd 向上发现后设置

from wb_common import (TOOLKIT_ROOT, find_project_root, load_machine,
                       toolkit_version, version_ok, atomic_write_json)

def _openocd_exe() -> str:
    """F-054: 原 OPENOCD_EXE 模块级常量惰性化——import 期零 IO。

    旧形态在 import 期读 machine.json，缺失时还向 stderr 吐回退警告，
    6 个测试文件被迫以注释豁免（CONTRIBUTING 禁令 #2 的存在理由之一）。
    惰性化后 import 卫生由 test_import_hygiene 钉死。"""
    return load_machine()["openocd_exe"]

from runtime_common import output_json  # noqa: E402  (F-041: doctor --json 复用共享层)
from openocd_runtime import swd_probe  # noqa: E402  (F-041: SWD 探测与 release G0.5 同源)
from expectations import (ExpectationError, contract_hashes,  # noqa: E402  (F-055: 拆分件再导出, verify.X 调用面不变)
                          evaluate_expectations, load_expectations,
                          _expect_matched)
from capture_rtt import step_capture_rtt as _step_capture_rtt  # noqa: E402  (F-056: 拆分件再导出, 旧私有名保持——3 处测试钉兼容)
from physical_gate import step_physical_gate  # noqa: E402  (F-057: 拆分件再导出, 同名同签名)

GCC_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "gcc_build.py")         # 默认后端 (builder=gcc)
# Keil 桥 (2026-08-28 退役入 legacy): builder 显式配 "keil" 时按需唤起, 见 scripts/legacy/keil/README.md
KEIL_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "legacy", "keil", "keil_build.py")
KEIL_ANALYZE = os.path.join(TOOLKIT_ROOT, "scripts", "legacy", "keil", "keil_analyze.py")
FEEDBACK_DB = os.path.join(TOOLKIT_ROOT, "scripts", "feedback_db.py")

def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def load_config(project_root: str) -> dict:
    """加载工程级配置 (.workbench/config.json, 兜底 .embeddedskills)

    JSON 损坏/非 UTF-8 抛 ConfigError (main() 捕获后友好退出, F-002)"""
    for marker in (".workbench/config.json", ".embeddedskills/config.json"):
        config_path = os.path.join(project_root, marker)
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ConfigError(f"{config_path} 不可解析: {e}") from e
    raise FileNotFoundError("工程内未找到 .workbench/config.json")


def run_py(script: str, args: list[str], timeout: int = 120) -> dict:
    """运行 Python 脚本并解析 JSON 输出"""
    cmd = [sys.executable, script] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, cwd=WORKSPACE
        )
        stdout = result.stdout.strip()
        if stdout:
            return json.loads(stdout)
        return {"status": "error", "message": f"no output from {os.path.basename(script)}",
                "stderr": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"{os.path.basename(script)} timed out after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON parse error: {e}",
                "raw_output": result.stdout[:500] if 'result' in dir() else ""}


def run_cmd(cmd: list[str], timeout: int = 60) -> dict:
    """运行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, cwd=WORKSPACE
        )
        success = result.returncode == 0 or 'verified' in result.stdout.lower()
        return {
            "status": "ok" if success else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-500:]
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"command timed out after {timeout}s"}


def step_build(config: dict, builder: str = "gcc",
               rebuild: bool = False) -> dict:
    """步骤 1: 编译 (按 config.json builder 字段切换后端: gcc | keil[legacy])"""
    if rebuild and builder != "gcc":
        # YAGNI: keil 后端不接 --rebuild (blink legacy 不用该旗标)
        return {"status": "error", "message": "--rebuild 仅支持 builder=gcc"}
    if builder == "gcc":
        gcc = config.get("gcc", {})
        project = gcc.get("project", "gcc-pilot/Makefile")
        target = gcc.get("target", "")
        log_dir = gcc.get("log_dir", ".workbench/build")
        # gcc/make 路径由 gcc_build 自行从 machine.json 解析
        args = ["rebuild" if rebuild else "build", "--project", project,
                "--target", target, "--log-dir", log_dir, "--json"]
        return run_py(GCC_BUILD, args, timeout=300)

    keil = config.get("keil", {})
    project = keil.get("project", "blink.uvprojx")
    target = keil.get("target", "STM32F103C8_Blink")
    log_dir = keil.get("log_dir", ".workbench/build")

    # uv4 由 keil_build 自行从 machine.json 解析 (机器路径只允许存在于 machine.json)
    args = ["build", "--project", project,
            "--target", target, "--log-dir", log_dir, "--json"]
    return run_py(KEIL_BUILD, args, timeout=120)


def step_analyze(log_file: str, builder: str = "gcc",
                 build_metrics: dict | None = None) -> dict:
    """步骤 2: 编译日志诊断 (gcc 后端自带 metrics, 跳过 ARMCC 知识库分析)"""
    if builder == "gcc":
        m = build_metrics or {}
        return {"status": "ok",
                "summary": {"errors": m.get("errors", 0),
                            "warnings": m.get("warnings", 0),
                            "matched": 0, "unmatched": 0}}
    return run_py(KEIL_ANALYZE, [log_file, "--json"], timeout=30)


def step_flash(hex_file: str) -> dict:
    """步骤 3: OpenOCD 烧录"""
    if not hex_file:
        # F-007: blink 退役后旧默认 obj/blink.hex 已移除; --no-build 无产物须明说
        return {"status": "error",
                "message": ("无可用 hex 产物 (--no-build 且 state.json 无 "
                            "last_build.hex_file): 先完整构建一次")}
    if not os.path.exists(os.path.join(WORKSPACE, hex_file)):
        return {"status": "error", "message": f"hex file not found: {hex_file}"}

    hex_abs = os.path.join(WORKSPACE, hex_file)
    cmd = [
        _openocd_exe(),
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f1x.cfg",
        "-c", f"program {{{hex_abs}}} verify reset exit"
    ]
    return run_cmd(cmd, timeout=30)


class ConfigError(ValueError):
    """工程配置非法 (.workbench/config.json JSON 损坏 / 非 UTF-8)。
    与 M1 的 ExpectationError 同款前置拦截: 损坏文件报友好错误而非裸 traceback"""


# F-046: HIL 任务 (flash / capture) 入口来源白名单 (2026-09-02 方案四-1)
#   manual    = 开发者手动 CLI 调起 (默认, 兼容现有 VS Code verify 任务)
#   schedule  = 定时任务 / cron 拉起 (release 门禁脚本会用)
#   dispatch  = 事件触发 / Harness 派发 (AI 工作流注入 origin=dispatch)
# 白名单外值一律 ValueError: 防止上游 typo 静默回落 manual, 绕过审计
HIL_ORIGINS = ("manual", "schedule", "dispatch")


def enforce_hil_origin(origin: str, require_schedule_origin: bool) -> tuple[bool, str]:
    """F-046 守卫: HIL 步骤 (flash / capture) 是否放行.

    Args:
        origin: 任务来源, 必须在 HIL_ORIGINS 白名单内, 否则抛 ValueError
        require_schedule_origin: --require-schedule-origin 旗标, 开启时拒绝 manual

    Returns:
        (allowed, reason): allowed=False 时 reason 给用户看的提示文本
    """
    if origin not in HIL_ORIGINS:
        raise ValueError(
            f"task_origin 非法: {origin!r}, 须为 {HIL_ORIGINS} 之一")
    if require_schedule_origin and origin == "manual":
        return False, (
            "HIL 任务 (flash/capture) 拒绝 manual 触发: "
            "请通过 schedule (CI/release 门禁) 或 dispatch (Harness 派发) 拉起, "
            "或去掉 --require-schedule-origin 旗标")
    return True, ""


def append_audit_entry(workspace: str, origin: str, step: str,
                       status: str, command: str) -> None:
    """F-046 台账: 每次 HIL 步骤执行后追加一行 JSON 到 .workbench/state/audit.jsonl.

    append-only 写入, 单调追加, 不重写历史. 失败不阻断主流程 (台账是审计而非门禁).
    """
    audit_dir = os.path.join(workspace, ".workbench", "state")
    audit_path = os.path.join(audit_dir, "audit.jsonl")
    try:
        os.makedirs(audit_dir, exist_ok=True)
        entry = {
            "ts": now_iso(),
            "origin": origin,
            "step": step,
            "status": status,
            "command": command,
        }
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # 台账是审计而非门禁: 落盘失败不阻断主流程, stderr 告警即可
        print(f"[warn] audit 落盘失败: {audit_path}", file=sys.stderr)


# F-047: 进度台账 (2026-09-02 方案四-2)
#   - checkpoints.jsonl: append-only, 8 字段 (ts/git_head/git_branch/status/
#     duration_sec/origin/step_keys/contract_hashes) — 审计链
#   - state.json last_checkpoint: 覆盖式, 与 jsonl 末行同步 — 消费方读
# 落盘失败不阻断 (与 F-046 audit.jsonl 同款审计非门禁纪律)
CHECKPOINT_STATUSES = ("ok", "fail", "timing_fail", "hardfault",
                       "build_failed", "build_has_errors", "flash_failed",
                       "capture_failed", "build_clean_skipped")


def _git_head(workspace: str) -> tuple[str, str]:
    """F-047: 隔离 git 调用, 失败返回 ("", "") 而非抛.

    返回 (短 commit hash, branch name). 非 git 目录 / git 不可用 → 空字符串.
    """
    try:
        head_p = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=workspace)
        branch_p = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=workspace)
        head = head_p.stdout.strip() if head_p.returncode == 0 else ""
        branch = branch_p.stdout.strip() if branch_p.returncode == 0 else ""
        # detached HEAD 时 git 报 "HEAD", 仍是有用信息, 不过滤
        return head, branch
    except (OSError, subprocess.TimeoutExpired):
        return "", ""


def record_checkpoint(workspace: str, status: str, duration_sec: float,
                      origin: str, step_keys: list,
                      contract_hashes: dict, *,
                      step_durations: dict | None = None,
                      gate_run: bool = False) -> None:
    """F-047: 双写 — checkpoints.jsonl (append) + state.json last_checkpoint.

    与 F-046 audit.jsonl 关系: audit 记 HIL 步骤级 (flash/capture),
    checkpoint 记 verify 全流程级 (跑完一次落一条). 两者职责正交.

    自审 (2026-09-03) 扩展:
      - step_durations: 各 step 实际耗时 (F-050 时长画像数据源).
        不传则留空 dict (向后兼容).
      - gate_run=True: 门禁重跑/豁免运行, 跳过 jsonl append 但仍更新
        state.json["last_checkpoint"] 标 status="gate_skip", 避免污染
        release audit 的"上次 PASS"语义 (Finding 3).
    """
    if status not in CHECKPOINT_STATUSES:
        raise ValueError(
            f"checkpoint status 非法: {status!r}, 须为 {CHECKPOINT_STATUSES} 之一")
    git_head, git_branch = _git_head(workspace)
    entry = {
        "ts": now_iso(),
        "git_head": git_head,
        "git_branch": git_branch,
        "status": status,
        "duration_sec": round(duration_sec, 1),
        "origin": origin,
        "step_keys": list(step_keys),
        "step_durations": dict(step_durations) if step_durations else {},
        "contract_hashes": dict(contract_hashes),
    }
    state_dir = os.path.join(workspace, ".workbench", "state")
    jsonl_path = os.path.join(state_dir, "checkpoints.jsonl")
    state_path = os.path.join(workspace, ".workbench", "state.json")
    # 自审 Finding 3: gate_run 不污染主台账, 但仍写 state.json (与
    # _log_feedback_event 跳 gate_run 同口径, spec 2026-08-26 §5)
    if gate_run:
        entry["status"] = "gate_skip"
    try:
        os.makedirs(state_dir, exist_ok=True)
        if not gate_run:
            # 1) append-only 台账 (gate 模式跳过, 防污染 release audit)
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 2) 同步 last_checkpoint 到 state.json (与现有 last_build 同构)
        #    gate 模式也写, 但 status=gate_skip 标出, 给 release audit 区分
        state = {}
        if os.path.isfile(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 旧 state.json 损坏: 不丢其它键, 按空 dict 继续 (load_workspace_state
                # for_update 的损坏隔离纪律不适用于 read-modify-write 单点)
                state = {}
        state["last_checkpoint"] = entry
        # F-047 自审 (2026-09-03) 改: 改用 atomic_write_json (F-022 纪律),
        # 防止进程在写 state.json 中途被 kill 导致 JSON 截断 → 下次读
        # 走损坏 → 走 state={} → 丢全部历史键 (含 last_build).
        atomic_write_json(state_path, state)
    except OSError:
        # 审计非门禁: 落盘失败不阻断主流程
        print(f"[warn] checkpoint 落盘失败: {jsonl_path}", file=sys.stderr)


def _record_checkpoint_early_exit(result: dict, args) -> None:
    """F-047 自审 (2026-09-03) Finding 2: 早退路径落台账.

    main() 各 sys.exit(1) 早退点 (build_failed / build_has_errors /
    flash_failed / capture_failed) 调用此函数, 让 progress 台账覆盖
    失败路径 — 不然 release audit 答不上"上次 build_failed 是哪天".

    与正常出口的 record_checkpoint 调用点不同: 早退时 result.steps
    已有部分填充, step_keys 来自已写入的 steps, step_durations
    来自已有的 duration_sec 字段.
    """
    if "WORKSPACE" not in globals() or WORKSPACE is None:
        return
    step_keys = [k for k, v in (result.get("steps") or {}).items()
                 if isinstance(v, dict) and v.get("status") not in ("skipped", None)]
    step_durations = {}
    for k in step_keys:
        s = result["steps"].get(k, {})
        d = s.get("duration_sec")
        if isinstance(d, (int, float)) and d > 0:
            step_durations[k] = float(d)
    record_checkpoint(
        workspace=WORKSPACE,
        status=result.get("status", "unknown"),
        duration_sec=result.get("elapsed_sec", 0.0),
        origin=getattr(args, "task_origin", "manual"),
        step_keys=step_keys,
        contract_hashes=result.get("contract_hashes") or {},
        step_durations=step_durations,
        gate_run=getattr(args, "gate_run", False),
    )


def cli_expectations(expect, expect_patterns, require_tgl):
    """legacy CLI/config 叠加断言 → 合成保留 ID 行 (spec §5.3), 保证
    --json 门禁证据完整。清单模式下 config expect* 不参与, 仅显式 CLI 断言叠加。"""
    items = []
    for i, t in enumerate(expect or []):
        items.append({"id": f"CLI-TEXT-{i:02d}", "texts": [t]})
    for i, p in enumerate(expect_patterns or []):
        items.append({"id": f"CLI-PAT-{i:02d}", "patterns": [p]})
    if require_tgl:
        items.append({"id": "CLI-REQUIRE-TGL", "patterns": [r"TGL \d+"]})
    return items


def verify(output: str, expect: list[str], description: str = "", expect_patterns: list[str] = None) -> dict:
    """步骤 5: AI 验证 (机器预处理 + 留给 Claude 最终判断)

    expect: 子串匹配列表; expect_patterns: 正则匹配列表 (需至少命中 1 次,
    如 ["TGL \\\\d+"] — 2026-08-16 review M1: 破坏 toggle 行为但不影响 init 的
    回归此前静默 PASS, 门禁必须能断言功能级事件)
    """
    matched = []
    missing = []
    for pattern in expect:
        if pattern in output:
            matched.append(pattern)
        else:
            missing.append(pattern)

    pat_matched = []
    pat_missing = []
    for pattern in (expect_patterns or []):
        if re.search(pattern, output):
            pat_matched.append(pattern)
        else:
            pat_missing.append(pattern)

    all_found = len(missing) == 0 and len(pat_missing) == 0
    return {
        "status": "ok" if all_found else "fail",
        "all_expected_found": all_found,
        "matched": matched,
        "missing": missing,
        "missing_patterns": pat_missing,
        "description": description,
        "needs_ai_judgement": True  # Claude 做最终判断
    }


_LOG_PREFIX_RE = re.compile(r'^(Info|Warn|Error|Debug)\s*:', re.IGNORECASE)
_CAPTURE_STATUS_KW = ["Listening on port", "halted due to", "shutdown command",
                      "GDB", "accepting", "dropped", "semihosting is enabled",
                      "target state:", "DEPRECATED",
                      "Licensed under GNU", "For bug reports",
                      "xPSR:", "http://", "Info :", "Warn :", "xPack"]


def _filter_capture_lines(raw: str) -> list:
    """从 OpenOCD stdout+stderr 提取 semihosting 正文行。

    OpenOCD 的 log 行以 "Info:/Warn:/Error:/Debug:" 开头, semihosting 输出是
    裸文本行; 正常结束与超时收尸两条路径必须共用同一套过滤口径 (F-003)。"""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _LOG_PREFIX_RE.match(stripped):
            continue
        if any(kw in stripped for kw in _CAPTURE_STATUS_KW):
            continue
        lines.append(stripped)
    return lines


def resolve_capture_timeout(cli_timeout, capture_cfg: dict | None) -> int:
    """F-016: 采集窗优先级 CLI --timeout > 契约 capture.duration_sec > 默认 10。

    真人按键类期望 (如 FR-KEY-01) 10s 硬窗几乎必错过——2026-08-30 插板终判
    三轮空采实锤; 窗口长度属工程契约, 应可写进 config.json 而非每次背 CLI。"""
    if cli_timeout is not None:
        return cli_timeout
    d = (capture_cfg or {}).get("duration_sec")
    if isinstance(d, int) and not isinstance(d, bool) and d > 0:
        return d
    return 10


def _finish_capture_timeout(proc, result: dict, capture_timeout: int,
                            max_retries: int, as_json: bool):
    """F-003: OpenOCD 卡死超时 — 回收部分输出并诚实判 capture_failed。

    旧行为丢弃已收输出并按 capture ok(lines=0) 入账, 把"采集工具超时"
    伪装成"程序无输出"归因。正常路径 OpenOCD 必然经 sleep+halt+shutdown
    退出, 超时只发生在工具自身卡死 — 输出不可信但部分留证仍有价值。
    待真机终判: 修复前后需各跑一次真机确认归因链。"""
    proc.kill()
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except Exception:
        stdout, stderr = "", ""
    partial = _filter_capture_lines((stdout or "") + (stderr or ""))
    result["steps"]["capture"] = {
        "status": "error", "method": "semihosting",
        "timeout_sec": capture_timeout,
        "lines": len(partial),
        "partial_output": _sanitize_text("\n".join(partial))[:2000],
        "error": (f"OpenOCD 未在 {capture_timeout + 30}s 内退出 — 采集超时"
                  "是工具故障, 非'程序无输出' (F-003)"),
    }
    result["status"] = "capture_failed"
    result["error"] = "capture 超时: OpenOCD 卡死, 部分输出已存失败现场"
    _save_failure_context(result, max_retries, capture_text="\n".join(partial))
    _output(result, as_json)
    sys.exit(1)


def _save_failure_context(result: dict, max_retries: int, capture_text: str = ""):
    """Save structured failure context for Agent analysis.

    Written to .workbench/build/last_failure.json so that
    Claude Code agents can read and analyze the failure before
    retrying with code fixes.

    capture_text: 完整 semihosting 输出原文落盘 (人类可读输出被截断到 500 字符,
    --json 才有完整文本 — 2026-08-16 TGL 验证教训, 失败现场必须完整可取证)
    """
    failure_path = os.path.join(WORKSPACE, ".workbench", "build", "last_failure.json")
    os.makedirs(os.path.dirname(failure_path), exist_ok=True)

    # Extract key diagnostic info
    ctx = {
        "status": result.get("status", "unknown"),
        "error": result.get("error", ""),
        "steps": {},
        "agent_hint": "",
    }
    if capture_text:
        ctx["captured_output"] = capture_text

    build_s = result.get("steps", {}).get("build", {})
    if build_s.get("status") == "build_failed":
        ctx["steps"]["build"] = {
            "attempts": build_s.get("attempts", []),
            "last_errors": build_s.get("errors", "?"),
            "last_warnings": build_s.get("warnings", "?"),
        }
        ctx["agent_hint"] = (
            "Build failed. Check the build log at .workbench/build/ for "
            "compiler errors. Common causes: missing include paths, ARMCC V5 "
            "C90 incompatibility (no C++ comments, no mixed decl+code), "
            "undefined symbols. Run /review:build if errors are unmatched in KB."
        )

    flash_s = result.get("steps", {}).get("flash", {})
    if flash_s.get("status") == "flash_failed":
        ctx["steps"]["flash"] = {
            "attempts": flash_s.get("attempts", []),
        }
        ctx["agent_hint"] = (
            "Flash failed. Check: ST-Link connected? Board powered? "
            "SWD pins (PA13/SWDIO, PA14/SWCLK) not reconfigured as GPIO? "
            f"Try: python {os.path.join(TOOLKIT_ROOT, 'scripts', 'hardfault.py')} "
            "to check connectivity."
        )

    # 采集失败: 写入 capture 步骤现场
    if result.get("status") == "capture_failed":
        ctx["steps"]["capture"] = result.get("steps", {}).get("capture", {})
        ctx["agent_hint"] = (
            "Capture failed. Check: ST-Link connected? OpenOCD target "
            "examine succeeded? Run: python "
            f"{os.path.join(TOOLKIT_ROOT, 'scripts', 'hardfault.py')} "
            "to check SWD connectivity, then retry."
        )

    # 验证失败 (含 TIMING_FAIL): 写入 capture + verify + physical_gate 现场
    if result.get("status") in ("fail", "timing_fail"):
        steps = result.get("steps", {})
        ctx["steps"]["capture"] = steps.get("capture", {})
        ctx["steps"]["verify"] = steps.get("verify", {})
        if steps.get("physical_gate", {}).get("status") not in (None, "skipped"):
            ctx["steps"]["physical_gate"] = steps["physical_gate"]
        if result["status"] == "timing_fail":
            ctx["agent_hint"] = (
                "printf output matched but GPIO toggle frequency deviated "
                "from expected. Check clock tree: HSE 8MHz -> PLL x9 -> 72MHz "
                "(Core/Src/main.c SystemClock_Config). Roll back to Drafter "
                "to adjust clock configuration."
            )
        else:
            xpass_ids = steps.get("verify", {}).get("xpass_ids") or []
            if xpass_ids:
                ctx["agent_hint"] = (
                    f"XPASS detected: {xpass_ids}. 功能已落地而清单仍标 xfail — "
                    "把 .workbench/expectations.json 对应条目改为 "
                    "xfail:false 后重跑."
                )
            else:
                missing = steps.get("verify", {}).get("missing", [])
                ctx["agent_hint"] = (
                    f"Semihosting OK but expected patterns missing: {missing}. "
                    "Check registry registration order and printf format in "
                    "modules/*/registry entries."
                )

    ctx["max_retries"] = max_retries
    ctx["timestamp"] = now_iso()

    try:
        with open(failure_path, 'w', encoding='utf-8') as f:
            json.dump(ctx, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # Non-critical


# ---------------------------------------------------------------------------
# 环境预检 --doctor (F-041): 打印工具链环境矩阵, 诊断专用。
# 定位: release.py G0.5 "区分环境未备/固件真坏" 之前的自检; 报障随 issue 附
# --doctor --json, 消灭"环境不同"类往返。是报告不是门禁 —— 退出码恒 0,
# 占位路径永不执行 (test_doctor 安全钉死)。

_DOCTOR_KEYS = ("uv4_exe", "openocd_exe", "gcc_path", "make_exe")


def _first_version_line(cmd: list) -> tuple:
    """运行版本命令, 返回 (ok, 首个非空行或错误串)。stdout/stderr 合并取行
    (OpenOCD 版本行打印在 stderr)。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, str(e)
    lines = [ln.strip() for ln in ((r.stdout or "") + (r.stderr or "")).splitlines()
             if ln.strip()]
    return (r.returncode == 0 or bool(lines)), (lines[0] if lines else "")


def _check_tool(machine: dict, key: str, bare: str, version_args: tuple) -> dict:
    """单工具检查。空/占位 → skipped (永不执行占位路径, 安全钉在 test_doctor);
    键为目录 (gcc_path 型) → 目录下找可执行 (Windows 优先 .exe), 找不到 → warn;
    键为文件 → 直接用; 版本命令失败 → warn (诊断报告不判门禁红)。"""
    val = (machine.get(key) or "").strip()
    if not val:
        return {"status": "skipped", "detail": f"{key} 为空"}
    if val.startswith("<"):
        return {"status": "skipped",
                "detail": f"{key} 为占位路径 (复制 machine.example.json 后填写)"}
    if os.path.isdir(val):
        exe = None
        for name in ((bare + ".exe") if os.name == "nt" else bare, bare):
            cand = os.path.join(val, name)
            if os.path.isfile(cand):
                exe = cand
                break
        if exe is None:
            return {"status": "warn",
                    "detail": f"{key} 目录下未找到 {bare}[.exe]: {val}"}
    elif os.path.isfile(val):
        exe = val
    else:
        return {"status": "warn", "detail": f"{key} 指向的路径不存在: {val}"}
    ok, line = _first_version_line([exe, *version_args])
    if not ok:
        return {"status": "warn", "detail": f"版本命令失败: {exe}", "error": line[:200]}
    return {"status": "ok", "detail": exe, "version": line[:120]}


# F-048: fixture 体检 (2026-09-02 方案四-5)
#   - 检查 tests/fixtures/contract/{config,expectations}.json 是否在
#   - 用 sha256 对比本地 vs 仓库默认分支版, 漂移 = warn
#   - 缺失 = fail (没有 fixture, 契约测试就缺锚点)
#   整段离线, 只读 git 仓 (git show <base>:tests/fixtures/contract/<file>)
# 自审 (2026-09-03) 修: 此前硬编码 main 分支, 但本仓默认是 master,
# CI runner fresh clone 上 main 不存在, 静默返空 dict → 误判 ok
def _detect_default_branch() -> str:
    """拿仓默认分支名. 优先 symbolic-ref origin/HEAD, fallback master, main.

    返回: 分支名字符串 (e.g. 'master', 'main', 'unknown')
    """
    try:
        r = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
            encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            # refs/remotes/origin/master → master
            return r.stdout.strip().rsplit("/", 1)[-1]
    except (OSError, subprocess.TimeoutExpired):
        pass
    # fallback: master 先, main 后 (本仓 master 是真默认, main 是老 GitHub 习惯)
    for cand in ("master", "main"):
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{cand}"],
                capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
                encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "unknown"


def _fixture_main_sha(fixture_dir: str) -> dict:
    """读 git 默认分支上的 fixture 文件 sha256, 失败回空 dict.

    用 `git show <base>:<path>` 而非 checkout —— 不污染工作树.
    默认分支通过 _detect_default_branch() 推断, 支持 master/main.
    """
    out = {}
    try:
        rel = os.path.relpath(fixture_dir, TOOLKIT_ROOT).replace(os.sep, "/")
    except ValueError:
        return out
    base = _detect_default_branch()
    if base == "unknown":
        return out   # 无法推断默认分支 → 静默返空, 漂移检测跳过
    for name in ("config.json", "expectations.json"):
        try:
            r = subprocess.run(
                ["git", "show", f"{base}:{rel}/{name}"],
                capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
                encoding="utf-8", errors="replace")
            if r.returncode == 0 and r.stdout:
                h = hashlib.sha256()
                h.update(r.stdout.encode("utf-8"))
                out[f"{name.replace('.json', '')}_sha256"] = h.hexdigest()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return out


def fixture_health(fixture_dir: str, *, skip_drift_check: bool = False) -> dict:
    """F-048 体检: fixture 在场性 + 漂移检测.

    Args:
        fixture_dir: 工程 fixture 目录 (含 config.json + expectations.json)
        skip_drift_check: True 时跳过 git main 对比 (测试场景: 占位时不应跑子进程)

    Returns:
        {status, config, expectations, drift}
        status ∈ {ok, warn, fail, skipped}
        - fail: 至少一个关键文件缺失
        - warn: 文件在但与 main 漂移
        - ok: 都在且无漂移
        - skipped: 非 git 仓 (无法做漂移检测, 视作"无漂移信号")
    """
    config_p = os.path.join(fixture_dir, "config.json")
    exp_p = os.path.join(fixture_dir, "expectations.json")
    config_s = "ok" if os.path.isfile(config_p) else "missing"
    exp_s = "ok" if os.path.isfile(exp_p) else "missing"

    # 漂移检测: 本地 sha256 vs main sha256
    drift = {"detected": False, "mismatches": []}
    if config_s == "ok" and exp_s == "ok" and not skip_drift_check:
        local = {}
        for name, key in (("config.json", "config_sha256"),
                          ("expectations.json", "expectations_sha256")):
            try:
                with open(os.path.join(fixture_dir, name), "rb") as f:
                    local[key] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                pass
        main_sha = _fixture_main_sha(fixture_dir)
        if main_sha:
            for k in ("config_sha256", "expectations_sha256"):
                if k in local and k in main_sha and local[k] != main_sha[k]:
                    drift["detected"] = True
                    drift["mismatches"].append(k)
    # 状态聚合
    if config_s == "missing" or exp_s == "missing":
        status = "fail"
    elif drift["detected"]:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "config": {"status": config_s, "path": config_p},
        "expectations": {"status": exp_s, "path": exp_p},
        "drift": drift,
    }


def doctor_report(probe: bool = True, *, skip_drift_check: bool = False) -> dict:
    """环境矩阵收集 (F-041)。machine.json 缺失时经 load_machine 回退链取占位值,
    各工具按占位/缺失跳过 —— 本函数永不执行占位路径。probe=True 且 openocd
    在场时做单次 SWD 探测 (attempts=1; 门禁 G0.5 用 3 次重试版)。"""
    machine = load_machine()
    machine_file = os.path.join(TOOLKIT_ROOT, "machine.json")
    example_file = os.path.join(TOOLKIT_ROOT, "machine.example.json")
    if os.path.isfile(machine_file):
        mode = "machine.json"
    elif os.path.isfile(example_file):
        mode = "fallback: machine.example.json (占位值, 真机步骤会明确报错)"
    else:
        mode = "missing"

    keys = {}
    for k in _DOCTOR_KEYS:
        v = (machine.get(k) or "").strip()
        keys[k] = {"value_set": bool(v),
                   "placeholder": v.startswith("<"),
                   "path_exists": os.path.exists(v) if v else None}

    tools = {"gcc": _check_tool(machine, "gcc_path", "arm-none-eabi-gcc", ("--version",)),
             "openocd": _check_tool(machine, "openocd_exe", "openocd", ("--version",)),
             "make": _check_tool(machine, "make_exe", "make", ("--version",))}

    oc = (machine.get("openocd_exe") or "").strip()
    if not oc or oc.startswith("<") or not os.path.isfile(oc):
        swd = {"status": "skipped",
               "detail": "openocd_exe 未配置/占位/不存在, 跳过 SWD 探测"}
    elif probe:
        ok, tail = swd_probe(oc, attempts=1)
        swd = {"status": "ok" if ok else "fail", "detail": tail}
    else:
        swd = {"status": "skipped", "detail": "未请求探测"}

    # F-048: fixture 体检 (2026-09-02 方案四-5) — 复用 TOOLKIT_ROOT 的 fixture 目录
    #   不传 workspace 是因为 fixture 跟工具库同仓, 体检只看 tests/fixtures/contract/
    #   skip_drift_check 让测试场景 (占位时不许跑子进程) 显式跳过 git 调用
    fixture = fixture_health(os.path.join(TOOLKIT_ROOT, "tests", "fixtures", "contract"),
                             skip_drift_check=skip_drift_check)
    statuses = [tools[n]["status"] for n in ("gcc", "openocd", "make")] \
        + [swd["status"], fixture["status"]]
    summary = {k: statuses.count(k) for k in ("ok", "warn", "fail", "skipped")}
    summary["fixture"] = fixture["status"]   # F-048: fixture 子项与 tools/swd 平级
    return {"tool": "doctor", "toolkit_version": toolkit_version(),
            "python": sys.version.split()[0],
            "machine": {"mode": mode, "keys": keys},
            "tools": tools, "swd": swd, "fixtures": fixture, "summary": summary}


def _print_doctor(rep: dict) -> None:
    print("== embedded-toolkit doctor ==")
    print(f"toolkit : {rep['toolkit_version']}   python: {rep['python']}")
    print(f"machine : {rep['machine']['mode']}")
    for k, v in rep["machine"]["keys"].items():
        flags = [lbl for lbl, on in (("空", not v["value_set"]),
                                     ("占位", v["placeholder"]),
                                     ("路径在场", v["path_exists"])) if on]
        print(f"  {k:<11}: {', '.join(flags) if flags else '-'}")
    for name in ("gcc", "openocd", "make"):
        t = rep["tools"][name]
        line = f"  {name:<9}: {t['status']}"
        if t.get("version"):
            line += f" — {t['version']}"
        elif t.get("detail"):
            line += f" — {t['detail']}"
        if t.get("error"):
            line += f" | {t['error']}"
        print(line)
    print(f"swd     : {rep['swd']['status']} — {rep['swd']['detail'][:120]}")
    # F-048: fixture 体检行 (与 tools/swd 平级)
    fx = rep.get("fixtures", {})
    if fx:
        drift_note = ""
        if fx.get("drift", {}).get("detected"):
            mm = ", ".join(fx["drift"].get("mismatches", []))
            drift_note = f" (drift: {mm})"
        miss = []
        if fx.get("config", {}).get("status") == "missing":
            miss.append("config")
        if fx.get("expectations", {}).get("status") == "missing":
            miss.append("expectations")
        miss_note = f" (missing: {', '.join(miss)})" if miss else ""
        print(f"fixtures: {fx.get('status', '?')}{drift_note}{miss_note}")
    s = rep["summary"]
    print(f"summary : ok={s['ok']} warn={s['warn']} fail={s['fail']} skipped={s['skipped']}"
          + (f" fixture={s['fixture']}" if "fixture" in s else ""))
    print("(doctor 为诊断报告, 不做门禁判定; 报障请附 --doctor --json 输出)")


def main():
    parser = argparse.ArgumentParser(
        description="闭环验证 — Build → Analyze → Flash → Capture → Verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python verify.py                         # 完整流程 (捕获 10s)
  python verify.py --timeout 15            # 捕获 15 秒
  python verify.py --no-build              # 跳过编译
  python verify.py --no-build --no-flash   # 仅采集+验证
  python verify.py --json | jq .verdict    # JSON 输出
        """
    )
    parser.add_argument("--timeout", type=int, default=None,
                        help="采集超时秒数 (优先 config capture.duration_sec, 再默认 10)")
    parser.add_argument("--project", default=None, help="工程根目录 (默认从 cwd 向上发现)")
    parser.add_argument("--no-build", action="store_true", help="跳过编译步骤")
    parser.add_argument("--no-flash", action="store_true", help="跳过烧录步骤")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--retry", type=int, default=0,
                        help="构建/烧录失败自动重试次数 (默认 0, 最大 3)")
    parser.add_argument("--retry-delay", type=int, default=2,
                        help="重试间隔秒数 (默认 2)")
    parser.add_argument("--require-tgl", action="store_true",
                        help="断言 capture 中至少 1 条 TGL 事件 (手动按键验证用, "
                             "2026-08-16 review M1 门禁; 纯 boot 验证勿用)")
    parser.add_argument("--rebuild", action="store_true",
                        help="编译前先 clean (仅 builder=gcc; 发布门禁用)")
    parser.add_argument("--gate-run", dest="gate_run", action="store_true",
                        help="发布门禁发起的运行: 跳过 feedback_db 落账")
    parser.add_argument("--doctor", action="store_true",
                        help="环境预检: 打印 toolkit/Python/machine.json 四键/gcc/openocd/"
                             "make/SWD 连通性矩阵后退出 (诊断报告, 不做门禁判定, 退出码恒 0)")
    parser.add_argument("--task-origin", dest="task_origin",
                        choices=list(HIL_ORIGINS), default="manual",
                        help="F-046 HIL 任务来源 (manual=手动, schedule=定时/CI, "
                             "dispatch=事件/Harness), 默认 manual")
    parser.add_argument("--require-schedule-origin",
                        dest="require_schedule_origin", action="store_true",
                        help="F-046 硬卡旗标: 开启后拒绝 task_origin=manual, "
                             "CI / release 门禁脚本默认加这个旗标")
    args = parser.parse_args()

    if args.doctor:
        # F-041: 诊断分支先于工程发现 —— doctor 不依赖 .workbench 工程
        report = doctor_report()
        if args.json:
            output_json(report)
        else:
            _print_doctor(report)
        return

    # 工程根: --project > cwd 向上发现
    global WORKSPACE
    WORKSPACE = args.project or find_project_root(os.getcwd())
    if not WORKSPACE:
        print("错误: 未找到工程根 (含 .workbench/config.json), 请在工程目录内运行或用 --project 指定",
              file=sys.stderr)
        sys.exit(1)
    WORKSPACE = os.path.abspath(WORKSPACE)
    try:
        config = load_config(WORKSPACE)
    except ConfigError as e:
        print(f"错误: 工程配置非法: {e}", file=sys.stderr)
        sys.exit(1)
    builder = config.get("builder", "gcc")   # 构建后端 (gcc | keil[legacy], 2026-08-28 默认翻转为 gcc)

    # 工具库版本检查: 工程要求的最低版本
    cfg_min = config.get("toolkit_min_version")
    if cfg_min and not version_ok(toolkit_version(), cfg_min):
        print(f"错误: 工具库版本 {toolkit_version()} 低于工程要求 {cfg_min}", file=sys.stderr)
        sys.exit(1)

    # Clamp retry
    max_retries = max(0, min(args.retry, 3))
    retry_delay = max(1, args.retry_delay)

    started_at = now_iso()
    started_ts = time.time()

    verify_cfg = config.get("verify", {})
    expect = verify_cfg.get("expect", [])
    description = verify_cfg.get("description", "")

    # 期望清单模式: .workbench/expectations.json 存在则优先,
    # 否则回退 legacy config.verify (blink/toggle 不受影响)
    try:
        expectations = load_expectations(WORKSPACE)
    except ExpectationError as e:
        print(f"错误: 期望清单非法: {e}", file=sys.stderr)
        sys.exit(1)
    expect_mode = "manifest" if expectations is not None else "legacy"

    result = {
        "pipeline": "build → analyze → flash → capture → verify",
        "started_at": started_at,
        "workspace": WORKSPACE,
        "toolkit_version": toolkit_version(),
        "expect_mode": expect_mode,
        "contract_hashes": contract_hashes(WORKSPACE, expect_mode == "manifest"),
        "expect": expect,
        "description": description,
        "retry_config": {"max_retries": max_retries, "retry_delay": retry_delay},
        "steps": {}
    }

    # ---- Step 1-2: Build + Analyze (with retry) ----
    if not args.no_build:
        build_t0 = time.time()  # F-050: step-level timing, 给 duration_profile 用
        build_attempts = []
        build_ok = False
        analyze = None   # F-008: build 循环内的分析结果, 循环后复用不再双跑
        for attempt in range(max_retries + 1):
            build = step_build(config, builder, rebuild=args.rebuild)
            build_info = {
                "attempt": attempt + 1,
                "status": build.get("status", "error"),
                "errors": build.get("metrics", {}).get("errors", -1),
                "warnings": build.get("metrics", {}).get("warnings", -1),
            }
            build_attempts.append(build_info)

            if build.get("status") == "ok":
                log_file = build.get("details", {}).get("log_file", "")
                hex_file = build.get("details", {}).get("hex_file", "")

                if log_file or builder == "gcc":
                    analyze = step_analyze(log_file, builder, build.get("metrics"))
                    if analyze.get("status") == "ok":
                        build_ok = True
                        break
            # else: retry
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not build_ok:
            result["steps"]["build"] = {
                "status": "build_failed",
                "attempts": build_attempts,
                "retry_count": len(build_attempts) - 1,
            }
            result["status"] = "build_failed"
            result["error"] = f"Build failed after {len(build_attempts)} attempt(s)"
            # Save failure context for Agent analysis
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        result["steps"]["build"] = {
            "status": "ok",
            "summary": build.get("summary", ""),
            "errors": build.get("metrics", {}).get("errors", -1),
            "warnings": build.get("metrics", {}).get("warnings", -1),
            "log_file": log_file,
            "hex_file": hex_file,
            "attempts": build_attempts,
            "retry_count": len(build_attempts) - 1,
            "duration_sec": round(time.time() - build_t0, 1),  # F-050
        }

        # ---- Step 2: Analyze ----
        # F-008: 复用 build 循环内已算出的 analyze (keil 后端曾双跑 keil_analyze);
        # 循环正常 break 时 analyze 必已赋值, None 仅在异常组合下出现
        if analyze is None:
            analyze = {"status": "error"}
        result["steps"]["analyze"] = {
            "status": analyze.get("status", "error"),
            "errors": analyze.get("summary", {}).get("errors", 0),
            "warnings": analyze.get("summary", {}).get("warnings", 0),
            "matched": analyze.get("summary", {}).get("matched", 0),
            "unmatched": analyze.get("summary", {}).get("unmatched", 0),
        }
        if analyze.get("status") == "error":
            result["status"] = "build_has_errors"
            result["error"] = f"Build has {analyze.get('summary', {}).get('errors', 0)} error(s)"
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        if analyze.get("summary", {}).get("unmatched", 0) > 0:
            result["steps"]["analyze"]["review_needed"] = True
            result["steps"]["analyze"]["review_command"] = "/review:build"
            result["steps"]["analyze"]["review_note"] = (
                "One or more build errors were not found in the knowledge base. "
                "Use /review:build to run adversarial review before applying fixes."
            )
    else:
        # 从 state.json 读取上次构建产物 (gcc/keil 后端 build 时写入)
        # F-007: 无产物走 step_flash 的明确报错, 不再回落 blink 退役残留路径
        hex_file = ""
        try:
            state_path = os.path.join(WORKSPACE, ".workbench", "state.json")
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                hex_file = state.get("last_build", {}).get("hex_file", "")
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            hex_file = ""   # state.json 损坏不再裸 traceback, 走无产物报错
        result["steps"]["build"] = {"status": "skipped"}
        result["steps"]["analyze"] = {"status": "skipped"}

    # ---- Step 3: Flash (with retry) ----
    # F-046: HIL 入口守卫 — 拒 manual 时给友好提示, exit 2 (区别于 0=成功/1=失败)
    if not args.no_flash:
        flash_t0 = time.time()  # F-050: step-level timing
        # F-046 守卫 (F-050 自审发现: 此前曾误写两行同参数调用, 已删冗余)
        allowed, deny_reason = enforce_hil_origin(
            args.task_origin, args.require_schedule_origin)
        if not allowed:
            print(f"错误: {deny_reason}", file=sys.stderr)
            sys.exit(2)
        flash_attempts = []
        flash_ok = False
        for attempt in range(max_retries + 1):
            flash = step_flash(hex_file)
            flash_info = {
                "attempt": attempt + 1,
                "status": flash.get("status", "error"),
                "message": flash.get("stderr", flash.get("stdout", ""))[-200:],
            }
            flash_attempts.append(flash_info)
            if flash.get("status") == "ok":
                flash_ok = True
                break
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not flash_ok:
            result["steps"]["flash"] = {
                "status": "flash_failed",
                "attempts": flash_attempts,
                "retry_count": len(flash_attempts) - 1,
            }
            result["status"] = "flash_failed"
            result["error"] = f"Flash failed after {len(flash_attempts)} attempt(s)"
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        result["steps"]["flash"] = {
            "status": "ok",
            "message": flash.get("stderr", flash.get("stdout", ""))[-300:],
            "attempts": flash_attempts,
            "retry_count": len(flash_attempts) - 1,
            "origin": args.task_origin,   # F-046: 审计标记, release audit 一眼可辨手动 vs CI
            "duration_sec": round(time.time() - flash_t0, 1),  # F-050
        }
        # F-046: 台账落盘 (audit-only, 失败不阻断主流程)
        append_audit_entry(WORKSPACE, args.task_origin, "flash", "ok",
                           " ".join(sys.argv))
    else:
        result["steps"]["flash"] = {"status": "skipped"}

    # ---- Step 4: Capture (semihosting 默认 | capture.backend=rtt) ----
    # 共同原则: reset halt 确定性起点 (2026-08-16 教训), 行过滤后进 verify()
    # F-046: capture 也是 HIL 步骤 — 守卫幂等, 第二次调用也是放行结果
    capture_t0 = time.time()  # F-050: step-level timing
    allowed_capture, deny_reason_capture = enforce_hil_origin(
        args.task_origin, args.require_schedule_origin)
    if not allowed_capture:
        print(f"错误: {deny_reason_capture}", file=sys.stderr)
        sys.exit(2)
    capture_started = time.time()
    capture_timeout = resolve_capture_timeout(args.timeout, config.get("capture", {}))
    # F-016: 预告窗口 (stderr, 不污染 --json 的 stdout); 人工输入期望需知何时按键
    print("[capture] 采集窗 %ds 自烧录/复位起开启 — 含人工输入期望请全程按键"
          % capture_timeout, file=sys.stderr)
    cap_backend = (config.get("capture", {}) or {}).get("backend", "semihosting")
    captured_lines = []
    captured_text = ""

    if cap_backend == "rtt":
        cap = _step_capture_rtt(capture_timeout, config.get("capture", {}), WORKSPACE)
        if cap.get("status") != "ok":
            result["steps"]["capture"] = {
                k: v for k, v in cap.items() if not k.startswith("_")
            }
            result["status"] = "capture_failed"
            result["error"] = cap.get("error", "rtt capture failed")
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        captured_text = cap.pop("_text", "")
        captured_lines = [ln for ln in captured_text.splitlines() if ln.strip()]
        cap["origin"] = args.task_origin   # F-046: 审计标记
        cap["duration_sec"] = round(time.time() - capture_t0, 1)  # F-050
        result["steps"]["capture"] = cap
        # F-046: 台账落盘 (RTT 后端独立标记 origin, release audit 可按 origin 聚合)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))
    else:
        # 直接调 OpenOCD: init → reset halt → semihosting enable → resume → sleep → halt → shutdown
        # 这是手工验证过的可靠方式（曾有独立 openocd_semihosting.py，F-028 删除，git 史可回放）
        # reset halt: 确定性起点 — 目标可能停在上一会话的 BKPT 冻结处 (printf 中途)
        # 或 boot 中段 (I2C2 BUSY 等待), 仅 halt 续跑会得到不完整 boot 输出 (2026-08-16 教训)
        openocd_cmd = [
            _openocd_exe(),
            "-f", "interface/stlink.cfg",
            "-f", "target/stm32f1x.cfg",
            "-c", "transport select swd",
            "-c", "init",
            "-c", "reset halt",
            "-c", "arm semihosting enable",
            "-c", "resume",
            "-c", f"sleep {capture_timeout * 1000}",  # OpenOCD sleep 单位是 ms
            "-c", "halt",
            "-c", "shutdown",
        ]

        try:
            proc = subprocess.Popen(
                openocd_cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                cwd=WORKSPACE
            )
            stdout, stderr = proc.communicate(timeout=capture_timeout + 30)
            captured_lines = _filter_capture_lines(stdout + stderr)

        except subprocess.TimeoutExpired:
            _finish_capture_timeout(proc, result, capture_timeout,
                                    max_retries, args.json)
        except Exception as e:
            result["steps"]["capture"] = {
                "status": "error", "method": "semihosting", "error": str(e)
            }
            result["status"] = "capture_failed"
            result["error"] = str(e)
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        captured_text = "\n".join(captured_lines)
        capture_elapsed = time.time() - capture_started

        result["steps"]["capture"] = {
            "status": "ok",
            "method": "semihosting",
            "timeout_sec": capture_timeout,
            "lines": len(captured_lines),
            "duration_sec": round(capture_elapsed, 1),
            "raw_length": len(captured_text),
            "origin": args.task_origin,   # F-046: 审计标记
        }
        result["steps"]["capture"]["duration_sec"] = round(
            time.time() - capture_t0, 1)  # F-050: 含守卫 + OpenOCD 全部耗时
        # F-046: 台账落盘 (semihosting 后端, 同上)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))

    # ---- Step 4b: HardFault 自动检测 ----
    # 触发条件 (修复 2026-08-12):
    #   capture 空 ≠ HardFault — --no-build/--no-flash 时空输出是预期行为,
    #   旧逻辑在此场景误触发诊断并污染反馈库 (hf_20260812_100345 事件)。
    #   仅当输出含显式 HARDFAULT 标记 (C 级 handler 打印的 === HARDFAULT ===)
    #   或"本次确实烧录过但完全无输出"时才运行诊断, 归因以诊断结果为准。
    has_hardfault = ("HARDFAULT" in captured_text)
    flash_ran = (not args.no_flash) and \
        result.get("steps", {}).get("flash", {}).get("status") == "ok"
    capture_empty = (len(captured_lines) == 0)
    if has_hardfault or (capture_empty and flash_ran):
        hf_path = os.path.join(TOOLKIT_ROOT, "scripts", "hardfault.py")
        if os.path.exists(hf_path):
            try:
                hf_result = subprocess.run(
                    [sys.executable, hf_path, "--json"],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace',
                    timeout=60, cwd=WORKSPACE
                )
                if hf_result.returncode == 0 and hf_result.stdout.strip():
                    hf_data = json.loads(hf_result.stdout)
                    hf_fault_type = hf_data.get("fault_type", "no_fault")
                    # 兜底诊断: 无 HARDFAULT 标记但诊断出真实故障位 → 视为 HardFault
                    if hf_fault_type != "no_fault":
                        has_hardfault = True
                    result["steps"]["hardfault"] = {
                        "status": ("hardfault_detected" if hf_fault_type != "no_fault"
                                   else "checked_no_fault"),
                        "fault_type": hf_fault_type,
                        "diagnosis": _sanitize_text(hf_data.get("diagnosis", "")),
                        "registers": hf_data.get("registers", {}),
                        "fault_registers": hf_data.get("fault_registers", {}),
                        "resolved": hf_data.get("resolved", {}),
                    }
                    # 注入点 ②: HardFault 检测到 → 标记需要对立审查
                    if hf_fault_type != "no_fault":
                        result["steps"]["hardfault"]["review_needed"] = True
                        result["steps"]["hardfault"]["review_command"] = "/review:hardfault"
                        result["steps"]["hardfault"]["review_note"] = (
                            "HardFault detected. Use /review:hardfault to run "
                            "adversarial review of the root cause analysis before fixing code."
                        )
                else:
                    result["steps"]["hardfault"] = {
                        "status": "error",
                        "message": ("Diagnosis failed" +
                                    (f": {hf_result.stderr[-200:]}" if hf_result.stderr else ""))
                    }
            except Exception as e:
                result["steps"]["hardfault"] = {
                    "status": "error", "message": str(e)
                }

    # ---- Step 4c: 物理层门控 (TIMING_FAIL) ----
    # GPIO Toggle 频率检测: 验证时序正确性 (代码在正确的时间做了该做的事)
    physical = step_physical_gate(config.get("physical_gate", {}), timeout=capture_timeout, workspace=WORKSPACE)
    result["steps"]["physical_gate"] = physical

    # ---- Step 5: Verify ----
    # 如果有 HardFault，自动判定失败
    if has_hardfault and "hardfault" in result.get("steps", {}):
        verification_result = {
            "status": "fail",
            "all_expected_found": False,
            "matched": [],
            "missing": expect,
            "description": f"HardFault detected: {result['steps']['hardfault'].get('fault_type', 'unknown')}",
            "needs_ai_judgement": True,
        }
    elif physical.get("status") == "timing_fail":
        # 物理层门控失败: printf 通过但 GPIO 翻转频率超差 → 强制 TIMING_FAIL
        verification_result = {
            "status": "fail",
            "all_expected_found": False,
            "matched": [],
            "missing": ["physical timing gate"],
            "description": physical.get("error", "GPIO toggle frequency out of tolerance"),
            "needs_ai_judgement": True,
        }
    elif expect_mode == "manifest":
        # 期望清单模式: 四态判定; config expect* 不参与, 仅显式 CLI 断言叠加 (spec §5.3)
        cli_items = cli_expectations([], [], getattr(args, "require_tgl", False))
        ev = evaluate_expectations(captured_text, list(expectations) + cli_items)
        verification_result = {
            "status": ev["verdict"],
            "all_expected_found": ev["verdict"] == "ok",
            "matched": [r["id"] for r in ev["results"] if r["status"] == "pass"],
            "missing": [r["id"] for r in ev["results"] if r["status"] == "fail"],
            "results": ev["results"],
            "xpass_ids": ev["xpass_ids"],
            "description": description,
            "needs_ai_judgement": True,
        }
        # capture 空兜底 (与 legacy 同款归因)
        if capture_empty and flash_ran:
            verification_result["description"] = (
                "程序无输出（无 HardFault 迹象）: "
                + verification_result.get("description", "")
            )
    else:
        # 正则断言: 配置键 verify.expect_patterns (缺省空) + CLI --require-tgl 注入
        expect_patterns = list(verify_cfg.get("expect_patterns", []) or [])
        if getattr(args, "require_tgl", False):
            expect_patterns.append(r"TGL \d+")
        verification_result = verify(captured_text, expect, description,
                                     expect_patterns=expect_patterns or None)
        # capture 空兜底: 确实烧录过但无输出且无 HardFault 迹象 → 归因准确
        if capture_empty and flash_ran:
            verification_result["description"] = (
                "程序无输出（无 HardFault 迹象）: "
                + verification_result.get("description", "")
            )
    result["steps"]["verify"] = verification_result

    # ---- Final result ----
    result["captured_output"] = _sanitize_text(captured_text)
    if has_hardfault:
        result["status"] = "hardfault"
    elif physical.get("status") == "timing_fail":
        # TIMING_FAIL 优先于 verify 的 fail — 时序错误是更严重的失败
        result["status"] = "timing_fail"
        result["error"] = physical.get("error", "Physical gate timing failure")
    elif physical.get("status") in ("probe_error", "insufficient_samples"):
        # 探测失败不谎报 pass/fail — 保持现状验证结论, 但标记探测异常
        result["status"] = verification_result["status"]
        result["physical_gate_error"] = physical.get("error", physical.get("status"))
    else:
        result["status"] = verification_result["status"]
    result["elapsed_sec"] = round(time.time() - started_ts, 1)

    # 验证失败 (fail/timing_fail) 时保存失败现场供 Agent 分析
    if result["status"] in ("fail", "timing_fail"):
        _save_failure_context(result, max_retries, capture_text=captured_text)

    # 注入点 ③: 自动记录反馈事件（异步，失败不影响主流程结论，但必须留痕 — F-004）。
    # --gate-run 跳过: 门禁重跑/豁免运行不得污染校准统计 (spec 2026-08-26 §5)
    result["feedback"] = _log_feedback_event(
        result, getattr(args, "gate_run", False))

    # F-047: 进度台账 — 双写 checkpoints.jsonl + state.json last_checkpoint
    #   step_keys 收集本次实际跑过的步骤 (状态非 skipped), 给后续审计 "那次跑过哪些步"
    #   contract_hashes 复用已有契约哈希, 把"判绿锚点"和"进度台账"绑一起
    step_keys = [k for k, v in (result.get("steps") or {}).items()
                 if isinstance(v, dict) and v.get("status") != "skipped"]
    record_checkpoint(
        workspace=WORKSPACE,
        status=result.get("status", "unknown"),
        duration_sec=result.get("elapsed_sec", 0.0),
        origin=getattr(args, "task_origin", "manual"),
        step_keys=step_keys,
        contract_hashes=result.get("contract_hashes") or {},
    )

    _output(result, args.json)
    # 退出码契约: ok=0, 其余(fail/timing_fail/hardfault 等)=1
    sys.exit(0 if result.get("status") == "ok" else 1)


def _log_feedback_event(result: dict, gate_run: bool) -> dict:
    """注入点 ③: 反馈落账 — 失败不影响主流程结论, 但必须留痕 (F-004)。

    落账跳过/失败曾是无痕审计盲区: button-toggle 工程 feedback 目录缺失,
    校准数据静默断流数周无人知 (F-001 的放大器)。返回的 feedback 状态字典
    随主流程 JSON 出档, 消费方可据此区分 落账成功/门禁跳过/落账失败。"""
    state = {"logged": False}
    if gate_run:
        state["skipped"] = True
        state["reason"] = "gate_run 不落校准库 (spec 2026-08-26 §5)"
        return state
    has_hardfault = result.get("status") == "hardfault"
    verify_ok = result.get("status") == "ok"
    event = {
        "pipeline": "hardfault" if has_hardfault else "build_fix",
        "error_code": result.get("steps", {}).get("analyze", {}).get("errors", None),
        "fault_type": result.get("steps", {}).get("hardfault", {}).get("fault_type"),
        "build_result": _build_result_str(result),
        "verify_result": "pass" if verify_ok else "fail",
        "outcome": "fixed" if verify_ok and not has_hardfault else "still_broken",
    }
    try:
        proc = subprocess.run(
            [sys.executable, FEEDBACK_DB, "--log", json.dumps(event)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, cwd=WORKSPACE)
        if proc.returncode == 0:
            state["logged"] = True
            try:
                state["event_id"] = json.loads(proc.stdout).get("event_id", "")
            except json.JSONDecodeError:
                pass
        else:
            state["error"] = ((proc.stderr or "") + (proc.stdout or "")).strip()[-200:]
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
    return state


def _build_result_str(result: dict) -> str:
    """从 result 中提取构建结果字符串"""
    build_s = result.get("steps", {}).get("build", {})
    if build_s.get("status") == "skipped":
        return "skipped"
    errors = build_s.get("errors", "?")
    warnings = build_s.get("warnings", "?")
    return f"{errors}e{warnings}w"


def _sanitize_text(text: str) -> str:
    """过滤控制字符和无效 Unicode，避免 JSON 编码错误"""
    return ''.join(c for c in text if c.isprintable() or c in '\n\r\t')


def _output(result: dict, as_json: bool):
    if as_json:
        # Force UTF-8 stdout for JSON output (Windows console uses GBK by default)
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 人类可读输出
        steps = result.get("steps", {})
        print("=" * 60)
        print("  闭环验证报告")
        print("=" * 60)

        build_s = steps.get("build", {})
        print(f"\n[1] Build:    {build_s.get('status', '?').upper()}"
              f"  errors={build_s.get('errors','?')}  warnings={build_s.get('warnings','?')}")

        analyze_s = steps.get("analyze", {})
        if analyze_s.get("status") != "skipped":
            print(f"[2] Analyze:  {analyze_s.get('status', '?').upper()}"
                  f"  matched={analyze_s.get('matched','?')}/{analyze_s.get('matched',0)+analyze_s.get('unmatched',0)}")

        flash_s = steps.get("flash", {})
        print(f"[3] Flash:    {flash_s.get('status', '?').upper()}")

        capture_s = steps.get("capture", {})
        print(f"[4] Capture:  {capture_s.get('status', '?').upper()}"
              f"  lines={capture_s.get('lines','?')}  method={capture_s.get('method','?')}")

        pg_s = steps.get("physical_gate", {})
        if pg_s.get("status") != "skipped":
            pg_info = (f"  measured={pg_s.get('measured_toggles_per_sec','?')} toggles/s"
                       f" (expected {pg_s.get('expected_toggles_per_sec','?')}"
                       f" ±{pg_s.get('tolerance',0)*100:.0f}%)")
            print(f"[4c] Physical: {pg_s.get('status','?').upper()}{pg_info}")

        verify_s = steps.get("verify", {})
        mode_tag = "  mode=manifest" if verify_s.get("results") is not None else ""
        print(f"[5] Verify:   {verify_s.get('status', '?').upper()}{mode_tag}")
        if verify_s.get("matched"):
            print(f"    Found:     {verify_s['matched']}")
        if verify_s.get("missing"):
            print(f"    Missing:   {verify_s['missing']}")
        for r in verify_s.get("results") or []:
            label = {"pass": "[PASS]", "xfail": "[XFAIL]", "xpass": "[XPASS]",
                     "fail": "[FAIL]"}.get(r["status"], "[????]")
            extra = f"  ({r['detail']})" if r.get("detail") else ""
            print(f"    {label} {r['id']}{extra}")
        if verify_s.get("xpass_ids"):
            print(f"    >>> XPASS 落地信号: {', '.join(verify_s['xpass_ids'])}"
                  " - 请翻转对应 xfail 后重跑 <<<")

        captured = result.get("captured_output", "")
        if captured:
            print(f"\n--- Captured Output ({len(captured)} chars) ---")
            print(captured[:500])
            if len(captured) > 500:
                print(f"... ({len(captured) - 500} more chars)")

        print(f"\n{'=' * 60}")
        verdict = "PASS" if result["status"] == "ok" else "FAIL"
        print(f"  Verdict: {verdict}")
        print(f"  Elapsed: {result.get('elapsed_sec', '?')}s")
        print("=" * 60)


if __name__ == "__main__":
    main()
