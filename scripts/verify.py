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
    1. Build   → keil_build.py
    2. Analyze → keil_analyze.py  (有 error 则终止)
    3. Flash   → OpenOCD program
    4. Capture → openocd_semihosting.py (采集 printf 输出)
    4c. Physical → OpenOCD ODR 轮询 GPIO 翻转频率 (物理层门控, 默认 skipped)
    5. Output  → 结构化 JSON 结果, Claude 对比期望判断 ✅/❌
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta


WORKSPACE = None  # 工程根, main() 中 --project 或 cwd 向上发现后设置

from wb_common import (TOOLKIT_ROOT, find_project_root, load_machine,
                       toolkit_version, version_ok)

OPENOCD_EXE = load_machine()["openocd_exe"]

KEIL_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "keil_build.py")       # 阶段2: 已折入工具库
KEIL_ANALYZE = os.path.join(TOOLKIT_ROOT, "scripts", "keil_analyze.py")
OPENOCD_SEMIHOSTING = os.path.join(TOOLKIT_ROOT, "scripts", "openocd_semihosting.py")  # 阶段2: 已折入工具库
FEEDBACK_DB = os.path.join(TOOLKIT_ROOT, "scripts", "feedback_db.py")
ERROR_DB_GROW = os.path.join(TOOLKIT_ROOT, "scripts", "error_db_grow.py")


def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def load_config(project_root: str) -> dict:
    """加载工程级配置 (.workbench/config.json, 兜底 .embeddedskills)"""
    for marker in (".workbench/config.json", ".embeddedskills/config.json"):
        config_path = os.path.join(project_root, marker)
        if os.path.isfile(config_path):
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
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


def step_build(config: dict) -> dict:
    """步骤 1: Keil 编译"""
    keil = config.get("keil", {})
    project = keil.get("project", "blink.uvprojx")
    target = keil.get("target", "STM32F103C8_Blink")
    log_dir = keil.get("log_dir", ".embeddedskills/build")

    uv4 = r"D:\KEIL5\UV4\UV4.exe"
    args = ["build", "--uv4", uv4, "--project", project,
            "--target", target, "--log-dir", log_dir, "--json"]
    return run_py(KEIL_BUILD, args, timeout=120)


def step_analyze(log_file: str) -> dict:
    """步骤 2: 编译日志诊断"""
    return run_py(KEIL_ANALYZE, [log_file, "--json"], timeout=30)


def step_flash(hex_file: str) -> dict:
    """步骤 3: OpenOCD 烧录"""
    if not os.path.exists(os.path.join(WORKSPACE, hex_file)):
        return {"status": "error", "message": f"hex file not found: {hex_file}"}

    hex_abs = os.path.join(WORKSPACE, hex_file)
    cmd = [
        OPENOCD_EXE,
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f1x.cfg",
        "-c", f"program {{{hex_abs}}} verify reset exit"
    ]
    return run_cmd(cmd, timeout=30)


def step_capture_semihosting(timeout: int) -> dict:
    """步骤 4: Semihosting 输出采集"""
    args = [
        "--interface", "interface/stlink.cfg",
        "--target", "target/stm32f1x.cfg",
        "--timeout", str(timeout),
        "--reset",
        "--json"
    ]
    return run_py(OPENOCD_SEMIHOSTING, args, timeout=timeout + 30)


def step_physical_gate(pg_cfg: dict, timeout: int) -> dict:
    """步骤 4c: 物理层门控 — GPIO Toggle 频率检测 (TIMING_FAIL)

    在真实硬件上轮询 GPIO ODR 翻转频率，与期望时基比对 (默认 ±5%)。
    堵住"编译通过即正确"幻觉中物理时序维度: printf 通过不代表时序正确。
    仅在 config.json physical_gate.enable=true 时生效, 默认 skipped 零开销。
    """
    if not pg_cfg.get("enable", False):
        return {"status": "skipped"}

    address = pg_cfg.get("address", "0x4001100C")
    mask = pg_cfg.get("mask", 0x2000)
    expected = float(pg_cfg.get("expected_toggles_per_sec", 4.0))
    tolerance = float(pg_cfg.get("tolerance", 0.05))
    window_ms = int(pg_cfg.get("measurement_window_ms", 10000))
    interval_ms = int(pg_cfg.get("sample_interval_ms", 100))
    min_edges = int(pg_cfg.get("min_edges", 8))

    # 运行时生成 TCL 探测脚本 (工程 .workbench/build/ 已 gitignore, 不污染源码树)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tcl_path = os.path.join(WORKSPACE, ".workbench", "build", f"physical_gate_{ts}.tcl")
    os.makedirs(os.path.dirname(tcl_path), exist_ok=True)
    warmup_ms = int(pg_cfg.get("warmup_ms", 4000))
    tcl = f"""\
# 预热: 等待"闪烁节奏" — 2 个连续边沿间隔 <= 1000ms 才算进入主循环心跳。
# 注意: 复位后 led_init 会有 1 个初始化边沿 (~100ms), 不能当闪烁信号;
# 且 semihosting 逐字符服务 printf 会拖长 boot 墙钟时间 (可达 20s+),
# 所以必须等节奏而非等第一个边沿。最多等 {warmup_ms}ms
set t_warm [clock milliseconds]
set last -1
set last_edge_ms -1
set started 0
while {{[expr {{[clock milliseconds] - $t_warm}}] < {warmup_ms} && !$started}} {{
    set rc [catch {{set vals [read_memory {address} 32 1]}} err]
    if {{$rc == 0}} {{
        set b [expr {{([lindex $vals 0] & {mask}) ? 1 : 0}}]
        if {{$last >= 0 && $b != $last}} {{
            set now_ms [clock milliseconds]
            if {{$last_edge_ms >= 0 && [expr {{$now_ms - $last_edge_ms}}] <= 1000}} {{
                set started 1
            }}
            set last_edge_ms $now_ms
        }}
        set last $b
    }}
    sleep {interval_ms}
}}
if {{!$started}} {{
    puts "PHYS_GATE_RESULT samples=0 edges=0 elapsed_ms=0 fail_reads=0"
    shutdown
}}
# 测量窗口: 复用 $last, 边界边沿不丢失
set t0 [clock milliseconds]
set edges 0
set samples 0
set fail_reads 0
while {{[expr {{[clock milliseconds] - $t0}}] < {window_ms}}} {{
    set rc [catch {{set vals [read_memory {address} 32 1]}} err]
    if {{$rc != 0}} {{
        incr fail_reads
    }} else {{
        set b [expr {{([lindex $vals 0] & {mask}) ? 1 : 0}}]
        if {{$last >= 0 && $b != $last}} {{ incr edges }}
        set last $b
        incr samples
    }}
    sleep {interval_ms}
}}
puts "PHYS_GATE_RESULT samples=$samples edges=$edges elapsed_ms=[expr {{[clock milliseconds] - $t0}}] fail_reads=$fail_reads"
shutdown
"""
    with open(tcl_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(tcl)

    cmd = [
        OPENOCD_EXE,
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f1x.cfg",
        "-c", "transport select swd",
        "-c", "init",
        # reset halt: 确定性起点 — 上一会话可能在 printf 的 BKPT 冻结且状态缓存错乱,
        # 只有复位能给出门控要测的稳态 (全新 boot 的 Main 页 LED 心跳), 不受页面/状态漂移影响
        "-c", "reset halt",
        # 必须开 semihosting: 否则 boot 的 printf 停在 BKPT 等 host 响应, CPU 冻结
        "-c", "arm semihosting enable",
        "-c", "resume",
        "-f", tcl_path,
    ]
    # ST-Link 释放竞态: capture 的 OpenOCD 刚退出, SWD/USB 释放偶尔需数百 ms~数秒,
    # 首次连接失败时短延迟重试, 避免 flaky PROBE_ERROR
    result_line = ""
    last_stderr = ""
    for attempt in range(3):
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                cwd=WORKSPACE
            )
            # 门控总耗时 = 预热(等闪烁节奏) + 测量窗口 + 启动开销, 超时必须覆盖全量
            stdout, stderr = proc.communicate(timeout=(warmup_ms + window_ms) / 1000 + 30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            last_stderr = "OpenOCD timed out during physical gate probe"
            if attempt < 2:
                time.sleep(3)
                continue
            return {"status": "probe_error", "error": last_stderr}

        last_stderr = (stderr or "")[-400:]
        # 解析 PHYS_GATE_RESULT 行
        for line in (stdout + stderr).splitlines():
            if "PHYS_GATE_RESULT" in line:
                result_line = line.strip()
                break
        if result_line:
            break
        if attempt < 2:
            time.sleep(3)

    if not result_line:
        return {"status": "probe_error",
                "error": "no PHYS_GATE_RESULT line in OpenOCD output",
                "stderr_tail": last_stderr}

    import re as _re
    fields = dict(_re.findall(r"(\w+)=(\d+)", result_line))
    samples = int(fields.get("samples", 0))
    edges = int(fields.get("edges", 0))
    elapsed_ms = int(fields.get("elapsed_ms", 0))
    fail_reads = int(fields.get("fail_reads", 0))

    if samples == 0:
        return {"status": "probe_error",
                "error": "no steady blink pattern in warmup (app may be stuck in boot)"}
    if fail_reads / samples > 0.3:
        return {"status": "probe_error", "error": f"too many failed reads: {fail_reads}/{samples}"}
    if edges < min_edges:
        return {"status": "insufficient_samples", "edges": edges, "min_edges": min_edges}

    measured = edges / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0.0
    deviation = abs(measured - expected) / expected if expected > 0 else 0.0

    out = {
        "status": "ok" if deviation <= tolerance else "timing_fail",
        "measured_toggles_per_sec": round(measured, 3),
        "expected_toggles_per_sec": expected,
        "tolerance": tolerance,
        "deviation": round(deviation, 4),
        "edges": edges,
        "samples": samples,
        "fail_reads": fail_reads,
        "elapsed_ms": elapsed_ms,
        "pin": pg_cfg.get("pin", ""),
    }
    if deviation > tolerance:
        out["error"] = (
            f"GPIO toggle frequency {measured:.2f}/s deviates from expected "
            f"{expected:.2f}/s by {deviation*100:.1f}% (tolerance {tolerance*100:.0f}%). "
            "Timing constraints violated — roll back to Drafter to adjust clock tree."
        )
    return out


def extract_semihosting_text(capture_result: dict) -> str:
    """从 openocd_semihosting.py 的返回结果中提取纯文本输出
    openocd_semihosting.py 在 --json 模式下通过 emit_stream_record 输出
    格式为 JSON 行: {"type":"stream","text":"LED ON\\r\\n",...}
    """
    # semihosting 脚本在成功时直接输出到 stdout，不通过 return result
    # 我们需要重新考虑如何捕获...

    # 实际上 openocd_semihosting.py 直接打印 JSON 行到 stdout
    # 而不是返回单个 JSON 对象。run_py 只能解析单个 JSON 对象。
    # 需要用不同方式调用。
    return ""  # 占位，实际在 step_capture_semihosting 中重新实现


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
            "Build failed. Check the build log at .embeddedskills/build/ for "
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
            "Try: python .embeddedskills/hardfault.py to check connectivity."
        )

    # 采集失败: 写入 capture 步骤现场
    if result.get("status") == "capture_failed":
        ctx["steps"]["capture"] = result.get("steps", {}).get("capture", {})
        ctx["agent_hint"] = (
            "Capture failed. Check: ST-Link connected? OpenOCD target "
            "examine succeeded? Run: python .embeddedskills/hardfault.py "
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
    parser.add_argument("--timeout", type=int, default=10, help="采集超时秒数 (默认 10)")
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
    args = parser.parse_args()

    # 工程根: --project > cwd 向上发现
    global WORKSPACE
    WORKSPACE = args.project or find_project_root(os.getcwd())
    if not WORKSPACE:
        print("错误: 未找到工程根 (含 .workbench/config.json), 请在工程目录内运行或用 --project 指定",
              file=sys.stderr)
        sys.exit(1)
    WORKSPACE = os.path.abspath(WORKSPACE)
    config = load_config(WORKSPACE)

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

    result = {
        "pipeline": "build → analyze → flash → capture → verify",
        "started_at": started_at,
        "workspace": WORKSPACE,
        "toolkit_version": toolkit_version(),
        "expect": expect,
        "description": description,
        "retry_config": {"max_retries": max_retries, "retry_delay": retry_delay},
        "steps": {}
    }

    # ---- Step 1-2: Build + Analyze (with retry) ----
    if not args.no_build:
        build_attempts = []
        build_ok = False
        for attempt in range(max_retries + 1):
            build = step_build(config)
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

                if log_file:
                    analyze = step_analyze(log_file)
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
            return

        result["steps"]["build"] = {
            "status": "ok",
            "summary": build.get("summary", ""),
            "errors": build.get("metrics", {}).get("errors", -1),
            "warnings": build.get("metrics", {}).get("warnings", -1),
            "log_file": log_file,
            "hex_file": hex_file,
            "attempts": build_attempts,
            "retry_count": len(build_attempts) - 1,
        }

        # ---- Step 2: Analyze ----
        analyze = step_analyze(log_file) if log_file else {"status": "error"}
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
            return
        if analyze.get("summary", {}).get("unmatched", 0) > 0:
            result["steps"]["analyze"]["review_needed"] = True
            result["steps"]["analyze"]["review_command"] = "/review:build"
            result["steps"]["analyze"]["review_note"] = (
                "One or more build errors were not found in the knowledge base. "
                "Use /review:build to run adversarial review before applying fixes."
            )
    else:
        # 从 state.json 读取上次构建产物 (keil_build 写于工程 .embeddedskills/state.json)
        state_path = os.path.join(WORKSPACE, ".embeddedskills", "state.json")
        if os.path.exists(state_path):
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            last = state.get("last_build", {})
            hex_file = last.get("hex_file", "obj/blink.hex")
        else:
            hex_file = "obj/blink.hex"
        result["steps"]["build"] = {"status": "skipped"}
        result["steps"]["analyze"] = {"status": "skipped"}

    # ---- Step 3: Flash (with retry) ----
    if not args.no_flash:
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
            return

        result["steps"]["flash"] = {
            "status": "ok",
            "message": flash.get("stderr", flash.get("stdout", ""))[-300:],
            "attempts": flash_attempts,
            "retry_count": len(flash_attempts) - 1,
        }
    else:
        result["steps"]["flash"] = {"status": "skipped"}

    # ---- Step 4: Capture Semihosting ----
    # 直接调 OpenOCD: init → reset halt → semihosting enable → resume → sleep → halt → shutdown
    # 这是手工验证过的可靠方式，不走复杂的 openocd_semihosting.py 脚本
    # reset halt: 确定性起点 — 目标可能停在上一会话的 BKPT 冻结处 (printf 中途)
    # 或 boot 中段 (I2C2 BUSY 等待), 仅 halt 续跑会得到不完整 boot 输出 (2026-08-16 教训)
    capture_started = time.time()
    capture_timeout = args.timeout

    openocd_cmd = [
        OPENOCD_EXE,
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

        # 从 stdout+stderr 中提取 semihosting 文本行
        # OpenOCD 的 log 行以 "Info:", "Warn:", "Error:", "Debug:" 开头
        # semihosting 输出是裸文本行
        import re as _re
        _log_prefix = _re.compile(r'^(Info|Warn|Error|Debug)\s*:', _re.IGNORECASE)
        _status_kw = ["Listening on port", "halted due to", "shutdown command",
                       "GDB", "accepting", "dropped", "semihosting is enabled",
                       "target state:", "DEPRECATED",
                       "Licensed under GNU", "For bug reports",
                       "xPSR:", "http://", "Info :", "Warn :", "xPack"]

        captured_lines = []
        for line in (stdout + stderr).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _log_prefix.match(stripped):
                continue
            if any(kw in stripped for kw in _status_kw):
                continue
            captured_lines.append(stripped)

    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        captured_lines = []
    except Exception as e:
        result["steps"]["capture"] = {
            "status": "error", "method": "semihosting", "error": str(e)
        }
        result["status"] = "capture_failed"
        result["error"] = str(e)
        _save_failure_context(result, max_retries)
        _output(result, args.json)
        return

    captured_text = "\n".join(captured_lines)
    capture_elapsed = time.time() - capture_started

    result["steps"]["capture"] = {
        "status": "ok",
        "method": "semihosting",
        "timeout_sec": args.timeout,
        "lines": len(captured_lines),
        "duration_sec": round(capture_elapsed, 1),
        "raw_length": len(captured_text)
    }

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
    physical = step_physical_gate(config.get("physical_gate", {}), timeout=capture_timeout)
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
    else:
        expect_patterns = [r"TGL \d+"] if getattr(args, "require_tgl", False) else None
        verification_result = verify(captured_text, expect, description,
                                     expect_patterns=expect_patterns)
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

    # 注入点 ③: 自动记录反馈事件（异步，失败不影响主流程）
    try:
        feedback_event = {
            "pipeline": "hardfault" if has_hardfault else "build_fix",
            "error_code": result.get("steps", {}).get("analyze", {}).get("errors", None),
            "fault_type": result.get("steps", {}).get("hardfault", {}).get("fault_type"),
            "build_result": _build_result_str(result),
            "verify_result": "pass" if result["status"] == "ok" else "fail",
            "outcome": "fixed" if result["status"] == "ok" else "still_broken",
        }
        if has_hardfault:
            feedback_event["outcome"] = "still_broken"
        subprocess.run(
            [sys.executable, FEEDBACK_DB, "--log", json.dumps(feedback_event)],
            capture_output=True, timeout=10, cwd=WORKSPACE
        )
    except Exception:
        pass  # 反馈记录失败不影响主流程
    finally:
        _output(result, args.json)


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
        print(f"[5] Verify:   {verify_s.get('status', '?').upper()}")
        if verify_s.get("matched"):
            print(f"    Found:     {verify_s['matched']}")
        if verify_s.get("missing"):
            print(f"    Missing:   {verify_s['missing']}")

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
