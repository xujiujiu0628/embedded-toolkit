r"""sim 采集会话 (F-150) — qemu-system-arm 驱动 (总工单 v2 C-1; spike F-149 GO)。

仿真器直接加载 elf 内核执行——**无烧录步骤、无探针在场**: flash 步骤
skipped、不持 F-145 设备锁、不落 F-046 HIL 台账、不跑 HIL origin 守卫
(sim 是非硬件判定后端, CI 可跑)。判定逻辑零改动: 同一份
expectations.json 既判真机又判仿真 (这正是 sim 的价值——同一契约双后端)。

命令形态 (F-149 spike 实证, QEMU 11.1.0):
  qemu-system-arm -M <machine> -kernel <elf> -nographic
    -semihosting-config enable=on,target=native -no-reboot
  - semihosting SYS_WRITE0 输出走 **stderr** (与 OpenOCD semihosting 的
    stdout+stderr 合并采集口径一致);
  - 固件收尾必须用 SYS_EXIT_EXTENDED(0x20) (r1 → 64 位 {reason, 0} 块)
    ——旧 SYS_EXIT(0x18) 在 M-profile 被 qemu 无声忽略, 进程永不退出;
  - 自旋固件靠外层 timeout kill, 部分输出已排空留证 (F-003 同款归因)。

控制流契约与 capture_semihosting 同款:
  成功 → 返回 (stdout, stderr)
  超时 → raise SimTimeout(proc)——不 kill 不收尸, 收尸权在调用方
        (verify._finish_capture_timeout, method="sim"/tool="qemu")
  其他异常 → 原样抛出。
communicate(timeout=...) 双管道有内部线程排空——F-123 的 readline 阻塞
地雷不在本路径, 但 stdin 显式 DEVNULL (防 qemu 监视器吞住交互终端)。
"""
from __future__ import annotations

import subprocess

from runtime_common import hidden_subprocess_kwargs
from shutil import which

DEFAULT_MACHINE = "stm32vldiscovery"
DEFAULT_QEMU = "qemu-system-arm"


class SimTimeout(Exception):
    """qemu 未在采集窗+30s 内退出——携带 proc 供调用方收尸 (F-003 口径)"""

    def __init__(self, proc):
        super().__init__("qemu timeout during sim session")
        self.proc = proc


def resolve_qemu(sim_cfg: dict | None = None) -> tuple[str, str]:
    """qemu 可执行解析链 (诚实溯源): config capture.sim.exe >
    machine.json qemu_exe > PATH > 缺省名。返回 (exe, source)。"""
    sim_cfg = sim_cfg or {}
    exe = sim_cfg.get("exe")
    if exe:
        return str(exe), "config:sim.exe"
    try:
        from wb_common import load_machine
        m_exe = load_machine().get("qemu_exe")
    except Exception:
        m_exe = ""
    if m_exe:
        return str(m_exe), "machine:qemu_exe"
    found = which(DEFAULT_QEMU) or which(DEFAULT_QEMU + ".exe")
    if found:
        return found, "path"
    return DEFAULT_QEMU, "default"


def run_sim_session(capture_timeout: int, machine: str, kernel: str, *,
                    qemu_exe: str | None = None,
                    sim_cfg: dict | None = None,
                    workspace: str | None = None) -> tuple:
    """跑一次 sim 采集会话, 返回 (stdout, stderr) 原文。

    machine/kernel 来自工程 config capture.sim 段与构建 elf 产物;
    超时 = capture_timeout + 30s (F-003 同款宽限)。"""
    sim_cfg = sim_cfg or {}
    exe = qemu_exe or resolve_qemu(sim_cfg)[0]
    cmd = [
        exe,
        "-M", machine,
        "-kernel", kernel,
        "-semihosting-config", "enable=on,target=native",
        "-nographic",
        "-no-reboot",
    ]
    cmd.extend(str(a) for a in sim_cfg.get("extra_args") or [])
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            cwd=workspace,
            **hidden_subprocess_kwargs(),
        )
    except OSError as e:
        # WinError 2 裸抛不可行动 — 点名 exe 与解析来源 (诚实化惯例)
        exe_src = "config:sim.exe/machine:qemu_exe/PATH" if qemu_exe is None \
            else "调用方显式传入"
        raise RuntimeError(
            f"qemu 不可启动 ({e}): exe={cmd[0]!r} "
            f"— 检查 capture.sim.exe / machine.json qemu_exe / PATH "
            f"(解析链: {exe_src})") from e
    try:
        stdout, stderr = proc.communicate(timeout=capture_timeout + 30)
    except subprocess.TimeoutExpired:
        # 不 kill 不收尸: F-003 的回收/归因/exit 全在调用方
        # _finish_capture_timeout 里, 归因链口径不变
        raise SimTimeout(proc) from None
    return stdout, stderr
