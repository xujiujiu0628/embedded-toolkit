r"""物理层门控 (F-057) — verify.py 拆分件第四步（防腐方案 §3.3 步骤 4）.

GPIO Toggle 频率检测（TIMING_FAIL）：在真实硬件上轮询 GPIO ODR 翻转频率，
与期望时基比对。堵住"编译通过即正确"幻觉中的物理时序维度——printf 通过
不代表时序正确。仅在 config.json physical_gate.enable=true 时生效。

自 verify.py 整体搬迁，行为逐字节不变；差异仅三点：WORKSPACE 全局改
workspace 参数（verify 调度点传参，TCL 落盘与子进程 cwd 均用之）、openocd
路径经 load_machine 惰性解析（F-054 惯例）、TCL 运行时生成到
<workspace>/.workbench/build/physical_gate_<ts>.tcl。

可测性: subprocess 经 mock.patch.object(physical_gate.subprocess, "Popen")
注入假 OpenOCD（communicate 返回含 PHYS_GATE_RESULT 行的输出），TCL 生成、
结果解析、判定数学（measured/deviation/timing_fail）与各 probe_error 分支
由此成为真单测。
"""
import os
import subprocess
import time
from datetime import datetime

from wb_common import load_machine


def step_physical_gate(pg_cfg: dict, timeout: int, workspace=None) -> dict:
    """步骤 4c: 物理层门控 — GPIO Toggle 频率检测 (TIMING_FAIL)

    在真实硬件上轮询 GPIO ODR 翻转频率，与期望时基比对 (默认 ±5%)。
    堵住"编译通过即正确"幻觉中物理时序维度: printf 通过不代表时序正确。
    仅在 config.json physical_gate.enable=true 时生效, 默认 skipped 零开销。
    F-057: workspace 参数化（原读 verify.WORKSPACE 全局）。
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
    tcl_path = os.path.join(workspace, ".workbench", "build", f"physical_gate_{ts}.tcl")
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
        load_machine()["openocd_exe"],
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
                cwd=workspace
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
