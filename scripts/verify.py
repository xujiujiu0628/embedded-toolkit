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
    4. Capture → verify.py 内置双路: semihosting 内联会话 (默认) | rtt (capture.backend)
    4c. Physical → OpenOCD ODR 轮询 GPIO 翻转频率 (物理层门控, 默认 skipped)
    5. Output  → 结构化 JSON 结果, Claude 对比期望判断 ✅/❌
"""

import argparse
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta


WORKSPACE = None  # 工程根, main() 中 --project 或 cwd 向上发现后设置

from wb_common import (TOOLKIT_ROOT, find_project_root, load_machine,
                       toolkit_version, version_ok)

OPENOCD_EXE = load_machine()["openocd_exe"]

GCC_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "gcc_build.py")         # 默认后端 (builder=gcc)
# Keil 桥 (2026-08-28 退役入 legacy): builder 显式配 "keil" 时按需唤起, 见 scripts/legacy/keil/README.md
KEIL_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "legacy", "keil", "keil_build.py")
KEIL_ANALYZE = os.path.join(TOOLKIT_ROOT, "scripts", "legacy", "keil", "keil_analyze.py")
FEEDBACK_DB = os.path.join(TOOLKIT_ROOT, "scripts", "feedback_db.py")

# ---------------------------------------------------------------------------
# RTT 采集后端 (capture.backend="rtt") — SEGGER RTT over OpenOCD rtt server
# 助手惯例与 openocd_* 系列对齐（本工具库按脚本复制，不做共享模块）
# ---------------------------------------------------------------------------

_RTT_TELNET_PORT = 4444
# 与 hardfault.py 同源的适配器致命错误串
_RTT_CRITICAL_ERRORS = ["open failed", "init mode failed", "no device found",
                        "cannot connect", "error connecting dp", "examination failed"]


def _rtt_read_until_prompt(sock: socket.socket) -> str:
    """读 telnet 直到 OpenOCD 的 '> ' 提示符（或超时/对端关闭）"""
    buf = b""
    while True:
        decoded = buf.decode("utf-8", errors="replace")
        if decoded.endswith("> ") or "\n> " in decoded or "\r> " in decoded:
            pos = max(decoded.rfind("\n> "), decoded.rfind("\r> "))
            if pos == -1 and decoded.endswith("> "):
                pos = len(decoded) - 2
            return decoded[:pos].strip() if pos >= 0 else decoded.strip()
        try:
            chunk = sock.recv(4096)
            if not chunk:
                return buf.decode("utf-8", errors="replace").strip()
            buf += chunk
        except socket.timeout:
            return buf.decode("utf-8", errors="replace").strip()


def _rtt_telnet(port: int, commands: list, timeout: float = 5.0) -> list:
    """连一次 telnet，顺序发送多条命令并收集各自响应"""
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        _rtt_read_until_prompt(sock)
        out = []
        for c in commands:
            sock.sendall((c + "\n").encode("utf-8"))
            out.append(_rtt_read_until_prompt(sock))
        return out
    finally:
        sock.close()


def _rtt_cleanup(proc):
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()


def _step_capture_rtt(timeout_s: int, rtt_cfg: dict) -> dict:
    """步骤 4 (capture.backend=rtt): telnet 驱动持久会话 + RTT TCP 通道采集.

    时序保证（为什么这样排）:
      reset halt → resume → sleep boot_delay → rtt setup → rtt start → server start
      ① rtt start 放在 resume+宽限之后: F103 SRAM 跨 NRST 保持, 若在 halt 态启动
         会接上上一轮残留控制块 → 陈旧输出冲进捕获造成假 PASS；
      ② TCP 连接在 server start 之后: 未读字节留在目标侧环形缓冲里,
         接入后一次性补发, 早期输出零丢失。
    返回契约与 semihosting 分支一致: steps.capture.{status,method,lines,...},
    正文经私有键 "_text" 带回（派发方 pop 后写入 result["captured_output"]）。
    """
    port = int(rtt_cfg.get("port", 19021))
    sram_base = rtt_cfg.get("sram_base", "0x20000000")
    sram_size = int(rtt_cfg.get("sram_size", 2048))
    cb_id = rtt_cfg.get("id", "SEGGER RTT")
    boot_delay_ms = int(rtt_cfg.get("boot_delay_ms", 300))
    connect_wait = float(rtt_cfg.get("connect_timeout_s", 3.0))

    base_cmd = [OPENOCD_EXE, "-c", "bindto 127.0.0.1",
                "-f", "interface/stlink.cfg", "-f", "target/stm32f1x.cfg"]
    # F-027: 该常量仅 Windows 存在, 裸用会让 Linux 在 rtt 分支直接 AttributeError
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    started = time.time()
    last_err = "unknown"

    for attempt in range(3):  # ST-Link 释放竞态重试纪律, 对齐 hardfault.py
        proc = None
        err_lines: list = []
        try:
            proc = subprocess.Popen(
                base_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=creationflags, cwd=WORKSPACE)

            def _drain(p=proc, sink=err_lines):
                for line in p.stderr:
                    sink.append(line.rstrip())

            threading.Thread(target=_drain, daemon=True).start()

            # --- 等 ready: telnet 监听出现且进程存活无致命错误 ---
            ready, why = False, ""
            t0 = time.time()
            while time.time() - t0 < 15.0:
                if proc.poll() is not None:
                    why = "openocd exited during startup"
                    break
                joined = "\n".join(err_lines)
                if f"Listening on port {_RTT_TELNET_PORT}" in joined:
                    # 监听可能先于适配器 init 失败打印 —— 给 0.3s 稳定期再判死刑
                    time.sleep(0.3)
                    bad = [e for e in err_lines
                           if any(k in e.lower() for k in _RTT_CRITICAL_ERRORS)]
                    if proc.poll() is not None:
                        why = "openocd exited right after listen"
                        break
                    if bad:
                        why = "; ".join(bad[-3:])
                        break
                    ready = True
                    break
                time.sleep(0.05)
            if not ready:
                raise RuntimeError(why or "openocd ready timeout")

            # --- telnet 阶段 1: 复位运行 + 建立新鲜控制块的 RTT 服务 ---
            resp = _rtt_telnet(_RTT_TELNET_PORT, [
                "reset halt", "resume", f"sleep {boot_delay_ms}",
                f'rtt setup {sram_base} {sram_size} "{cb_id}"',
                "rtt start", "rtt polling_interval 100",
                f"rtt server start {port} 0"])
            blob = "\n".join(resp)
            low = blob.lower()
            if "control block" in low and "not found" in low:
                # 定性失败, 不空转重试: 多为固件没编进 RTT 或 SRAM 范围不对
                raise ValueError("rtt_control_block_not_found")
            if "error" in low:
                raise RuntimeError(blob.strip().splitlines()[-1][:200] if blob.strip() else "rtt command error")

            # --- TCP 数据通道: 接入后读到 deadline ---
            data_sock = None
            tc0 = time.time()
            while time.time() - tc0 < connect_wait:
                try:
                    data_sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                    break
                except OSError:
                    time.sleep(0.05)
            if data_sock is None:
                raise TimeoutError(f"rtt tcp connect timeout ({connect_wait}s)")

            buf = bytearray()
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                data_sock.settimeout(max(0.05, min(0.5, deadline - time.time())))
                try:
                    chunk = data_sock.recv(4096)
                    if chunk:
                        buf += chunk
                except socket.timeout:
                    pass
            data_sock.close()

            text = buf.decode("utf-8", errors="replace")
            return {
                "status": "ok", "method": "rtt",
                "timeout_sec": timeout_s,
                "lines": len([ln for ln in text.splitlines() if ln.strip()]),
                "duration_sec": round(time.time() - started, 1),
                "raw_length": len(text),
                "_text": text,
            }

        except ValueError as e:
            last_err = str(e)
            break  # 控制块类失败换多少次会话都一样
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}" if not str(e) else str(e)
            if attempt < 2:
                time.sleep(3)
        finally:
            try:
                if proc is not None and proc.poll() is None:
                    _rtt_telnet(_RTT_TELNET_PORT, ["halt", "shutdown"], timeout=2.0)
            except OSError:
                pass
            _rtt_cleanup(proc)

    return {"status": "error", "method": "rtt", "lines": 0, "error": last_err}


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
        OPENOCD_EXE,
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f1x.cfg",
        "-c", f"program {{{hex_abs}}} verify reset exit"
    ]
    return run_cmd(cmd, timeout=30)


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


class ExpectationError(ValueError):
    """期望清单非法 (id 重复 / 缺 xfail_reason / texts+patterns 并存等)"""


class ConfigError(ValueError):
    """工程配置非法 (.workbench/config.json JSON 损坏 / 非 UTF-8)。
    与 M1 的 ExpectationError 同款前置拦截: 损坏文件报友好错误而非裸 traceback"""


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def contract_hashes(workspace: str, has_manifest: bool) -> dict:
    """F-018: 判绿所依据契约的字节级哈希 — 发布记录的"判绿锚点"。

    M2 给 hex 上哈希锚定了"烧的字节", 这里锚定"拿什么判的绿": results 由
    expectations.json + config.json 的具体内容产生, 记录不绑定其哈希则
    无法事后审计 results 与哪个版本的契约对应。config 取与 load_config
    同序的第一个在场 marker; expectations 仅 manifest 模式存在。"""
    out = {}
    for marker in (".workbench/config.json", ".embeddedskills/config.json"):
        p = os.path.join(workspace, marker)
        if os.path.isfile(p):
            out["config_sha256"] = _sha256_file(p)
            break
    if has_manifest:
        out["expectations_sha256"] = _sha256_file(
            os.path.join(workspace, ".workbench", "expectations.json"))
    return out


def load_expectations(workspace):
    """加载 .workbench/expectations.json (spec 2026-08-26 §3)。

    文件不存在返回 None (调用方回退 legacy config.verify);
    清单非法抛 ExpectationError, main() 捕获后退出码 1。
    """
    path = os.path.join(workspace, ".workbench", "expectations.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # JSONDecodeError 是 ValueError 但不是 ExpectationError 子类,
        # 不转译的话 main() 的 except 接不住 → 烧录后裸 traceback (审计 M1)
        raise ExpectationError(f"清单不是合法 JSON/UTF-8: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("expectations"), list) \
            or not data["expectations"]:
        raise ExpectationError("须为含非空 expectations 数组的 JSON 对象")
    seen = set()
    for i, item in enumerate(data["expectations"]):
        where = f"expectations[{i}]"
        if not isinstance(item, dict):
            raise ExpectationError(f"{where}: 须为对象")
        eid = item.get("id")
        if not isinstance(eid, str) or not eid.strip():
            raise ExpectationError(f"{where}: id 必填且非空")
        if eid in seen:
            raise ExpectationError(f"id 重复: {eid}")
        seen.add(eid)
        if not isinstance(item.get("desc"), str) or not item["desc"].strip():
            raise ExpectationError(f"{eid}: desc 必填且非空")
        texts = item.get("texts")
        pats = item.get("patterns")
        ok_texts = isinstance(texts, list) and len(texts) > 0 and \
            all(isinstance(t, str) and t for t in texts)
        ok_pats = isinstance(pats, list) and len(pats) > 0 and \
            all(isinstance(p, str) and p for p in pats)
        if ok_texts == ok_pats:  # 并存或皆缺均非法
            raise ExpectationError(f"{eid}: texts 与 patterns 须二选一(非空字符串数组)")
        if ok_pats:
            for p in pats:
                try:
                    re.compile(p)
                except re.error as e:
                    # 惰性编译会把非法正则拖到烧录后才炸 (审计 M1)
                    raise ExpectationError(f"{eid}: 非法正则 {p!r}: {e}") from e
        if item.get("xfail") and (not isinstance(item.get("xfail_reason"), str)
                                  or not item["xfail_reason"].strip()):
            raise ExpectationError(f"{eid}: xfail=true 时 xfail_reason 必填")
        cg = item.get("capture_group")
        if cg is not None and (isinstance(cg, bool) or not isinstance(cg, int) or cg < 1):
            raise ExpectationError(f"{eid}: capture_group 须为正整数")
        if cg is not None and not ok_pats:
            # texts+capture_group 组合会在评估期 first=None AttributeError (审计 M1)
            raise ExpectationError(f"{eid}: capture_group 须与 patterns 搭配")
        for bound in ("min", "max"):
            v = item.get(bound)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v)):
                # NaN 会绕过全部边界比较恒 pass (审计 M1)
                raise ExpectationError(f"{eid}: {bound} 须为有限数值")
    return data["expectations"]


def _expect_matched(item, output):
    """单条期望匹配判定 (spec §3): texts 全命中 且 patterns 全命中;
    capture_group/min/max 数值断言作用于 patterns[0] 首个 match。
    返回 (matched, 失败细节)。"""
    missing = [t for t in item.get("texts", []) if t not in output]
    if missing:
        return False, f"missing texts: {missing}"
    first = None
    for j, pat in enumerate(item.get("patterns", [])):
        m = re.search(pat, output)
        if not m:
            return False, f"pattern 未命中: {pat!r}"
        if j == 0:
            first = m
    cg = item.get("capture_group")
    if cg is not None:
        try:
            value = float(first.group(cg))
        except (IndexError, TypeError, ValueError):
            return False, f"capture_group={cg} 提取失败"
        lo = item.get("min")
        hi = item.get("max")
        if lo is not None and value < float(lo):
            return False, f"值 {value} < min {lo}"
        if hi is not None and value > float(hi):
            return False, f"值 {value} > max {hi}"
    return True, ""


def evaluate_expectations(output, expectations):
    """四态判定纯函数 (spec §4): PASS=匹配&非xfail; XFAIL=未匹配&xfail;
    XPASS=匹配&xfail(严格红); FAIL=未匹配&非xfail。
    verdict="ok" 当且仅当所有 status ∈ {pass, xfail}。无 IO, 可单测。"""
    results = []
    for item in expectations:
        ok, detail = _expect_matched(item, output)
        xfail = bool(item.get("xfail"))
        if ok and not xfail:
            status = "pass"
        elif ok and xfail:
            status = "xpass"
        elif not ok and xfail:
            status = "xfail"
        else:
            status = "fail"
        r = {"id": item["id"], "status": status}
        if detail and status in ("fail", "xpass"):
            r["detail"] = detail
        results.append(r)
    verdict = "ok" if all(r["status"] in ("pass", "xfail") for r in results) else "fail"
    return {"results": results, "verdict": verdict,
            "xpass_ids": [r["id"] for r in results if r["status"] == "xpass"]}


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
    args = parser.parse_args()

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
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        result["steps"]["flash"] = {
            "status": "ok",
            "message": flash.get("stderr", flash.get("stdout", ""))[-300:],
            "attempts": flash_attempts,
            "retry_count": len(flash_attempts) - 1,
        }
    else:
        result["steps"]["flash"] = {"status": "skipped"}

    # ---- Step 4: Capture (semihosting 默认 | capture.backend=rtt) ----
    # 共同原则: reset halt 确定性起点 (2026-08-16 教训), 行过滤后进 verify()
    capture_started = time.time()
    capture_timeout = resolve_capture_timeout(args.timeout, config.get("capture", {}))
    # F-016: 预告窗口 (stderr, 不污染 --json 的 stdout); 人工输入期望需知何时按键
    print("[capture] 采集窗 %ds 自烧录/复位起开启 — 含人工输入期望请全程按键"
          % capture_timeout, file=sys.stderr)
    cap_backend = (config.get("capture", {}) or {}).get("backend", "semihosting")
    captured_lines = []
    captured_text = ""

    if cap_backend == "rtt":
        cap = _step_capture_rtt(capture_timeout, config.get("capture", {}))
        if cap.get("status") != "ok":
            result["steps"]["capture"] = {
                k: v for k, v in cap.items() if not k.startswith("_")
            }
            result["status"] = "capture_failed"
            result["error"] = cap.get("error", "rtt capture failed")
            _save_failure_context(result, max_retries)
            _output(result, args.json)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        captured_text = cap.pop("_text", "")
        captured_lines = [ln for ln in captured_text.splitlines() if ln.strip()]
        result["steps"]["capture"] = cap
    else:
        # 直接调 OpenOCD: init → reset halt → semihosting enable → resume → sleep → halt → shutdown
        # 这是手工验证过的可靠方式（曾有独立 openocd_semihosting.py，F-028 删除，git 史可回放）
        # reset halt: 确定性起点 — 目标可能停在上一会话的 BKPT 冻结处 (printf 中途)
        # 或 boot 中段 (I2C2 BUSY 等待), 仅 halt 续跑会得到不完整 boot 输出 (2026-08-16 教训)
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
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        captured_text = "\n".join(captured_lines)
        capture_elapsed = time.time() - capture_started

        result["steps"]["capture"] = {
            "status": "ok",
            "method": "semihosting",
            "timeout_sec": capture_timeout,
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
