r"""semihosting 采集会话 (F-061) — verify.py 拆分件收官（防腐方案 §3.3 步骤 5d）.

直接调 OpenOCD: init → reset halt → semihosting enable → resume → sleep →
halt → shutdown。这是手工验证过的可靠方式（曾有独立 openocd_semihosting.py，
F-028 删除，git 史可回放）。

自 verify.py main() 内联分支搬迁。控制流契约（关键设计）:
  - 成功 → 返回 (stdout, stderr)
  - 超时 → raise SemihostingTimeout(proc)，**不 kill 不收尸**——收尸权交还
    调用方走 _finish_capture_timeout（F-003 归因链逐字节不变: kill/部分输出
    回收/诚实归因/exit(1) 全在留守函数里）
  - 其他异常 → 原样抛出，由调用方 capture_failed 分支处理（与原行为一致）

reset halt 的理由（2026-08-16 教训）: 目标可能停在上一会话的 BKPT 冻结处
（printf 中途）或 boot 中段（I2C2 BUSY 等待），仅 halt 续跑会得到不完整
boot 输出——只有复位给确定性起点。
"""
import subprocess

from wb_common import load_machine


class SemihostingTimeout(Exception):
    """OpenOCD 未在采集窗+30s 内退出——携带 proc 供调用方收尸 (F-003)"""

    def __init__(self, proc):
        super().__init__("OpenOCD timeout during semihosting session")
        self.proc = proc


def run_semihosting_session(capture_timeout: int, workspace=None) -> tuple:
    """跑一次 semihosting 采集会话, 返回 (stdout, stderr) 原文.

    F-061: 自 main() 内联分支搬迁——cmd 构建/Popen/communicate 在此,
    超时收尸与结果组装留守 verify (派发胶水不下沉)。workspace 作为
    OpenOCD 子进程 cwd (原读 verify.WORKSPACE 全局)。
    """
    openocd_cmd = [
        load_machine()["openocd_exe"],
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

    proc = subprocess.Popen(
        openocd_cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace',
        cwd=workspace
    )
    try:
        stdout, stderr = proc.communicate(timeout=capture_timeout + 30)
    except subprocess.TimeoutExpired:
        # 不 kill 不收尸: F-003 的回收/归因/exit 全在调用方
        # _finish_capture_timeout 里, 逐字节保持原归因链
        raise SemihostingTimeout(proc) from None
    return stdout, stderr
