r"""RTT 采集后端 (F-056) — verify.py 拆分件第三步（防腐方案 §3.3 步骤 3）.

SEGGER RTT over OpenOCD rtt server：telnet 驱动持久会话 + RTT TCP 通道采集。
自 verify.py 整体搬迁（原 `_step_capture_rtt` 及其助手），行为逐字节不变；
差异仅两点：WORKSPACE 全局改 workspace 参数（verify 调度点传参）、
openocd 路径经 load_machine 惰性解析（F-054 惯例）。

wire 兼容: verify `from capture_rtt import step_capture_rtt as _step_capture_rtt`
再导出（旧私有名保持），3 处测试钉零修改——其中 F-031 运行时钉 patch 的是
sys/subprocess/time 共享模块对象，对本模块同样生效。

可测性: 不做构造注入，测试经 mock.patch.object 钉本模块可见的共享模块对象
（subprocess.Popen / socket.create_connection / time.sleep）即可驱动全流程，
RTT 时序断言（下）由此成为真单测。
"""
import socket
import subprocess
import sys
import threading
import time

from runtime_common import OpenocdCfgError, resolve_openocd_cfg
from wb_common import load_machine

_RTT_TELNET_PORT = 4444
# 环指针死锁（2026-11-17 实测）: 固件 ~1.2KB/s 写入、上行环只有 512B 时，
# OpenOCD 每 100ms 才排空一次，目标侧在两次轮询之间把环写回绕，RdOff 会
# 越过 WrOff（实测 RdOff=93 > WrOff=87），SEGGER 判定"空间不足 5 字节"，
# 之后每条 120B 的行被整条丢弃 —— 表现为"固件活着但采集只回启动几行"。
# 拉快到 10ms 从源头降低概率；端到端的判定见 _stall_seconds()。
_RTT_POLL_INTERVAL_MS = 10
# 窗口结束前若已静默这么久且有数据，判定为可疑停顿（不是异常，是告警）
_RTT_STALL_SEC = 2.0
# 与 hardfault.py 同源的适配器致命错误串
_RTT_CRITICAL_ERRORS = ["open failed", "init mode failed", "no device found",
                        "cannot connect", "error connecting dp", "examination failed"]


def _stall_seconds(last_data_at, now, have_data: bool,
                   threshold: float = _RTT_STALL_SEC) -> float:
    """窗口结束时的静默秒数；无数据或不足阈值返回 0.0。

    分开成纯函数是为了能单测——这个判据的价值全在"别把停顿当正常"：
    2026-11-17 采集只回 4 行却报 status=ok，我据此把"固件卡死"当成了结论，
    白查了一轮。停顿必须显式出现在结果里。
    """
    if not have_data or last_data_at is None:
        return 0.0
    idle = now - last_data_at
    return round(idle, 1) if idle >= threshold else 0.0


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


def step_capture_rtt(timeout_s: int, rtt_cfg: dict, workspace=None) -> dict:
    """步骤 4 (capture.backend=rtt): telnet 驱动持久会话 + RTT TCP 通道采集.

    时序保证（为什么这样排）:
      reset halt → resume → sleep boot_delay → rtt setup → rtt start → server start
      ① rtt start 放在 resume+宽限之后: F103 SRAM 跨 NRST 保持, 若在 halt 态启动
         会接上上一轮残留控制块 → 陈旧输出冲进捕获造成假 PASS；
      ② TCP 连接在 server start 之后: 未读字节留在目标侧环形缓冲里,
         接入后一次性补发, 早期输出零丢失。
    返回契约与 semihosting 分支一致: steps.capture.{status,method,lines,...},
    正文经私有键 "_text" 带回（派发方 pop 后写入 result["captured_output"]）。
    F-056: workspace 参数化（原读 verify.WORKSPACE 全局），作为 OpenOCD 子进程 cwd。
    """
    port = int(rtt_cfg.get("port", 19021))
    sram_base = rtt_cfg.get("sram_base", "0x20000000")
    sram_size = int(rtt_cfg.get("sram_size", 2048))
    cb_id = rtt_cfg.get("id", "SEGGER RTT")
    boot_delay_ms = int(rtt_cfg.get("boot_delay_ms", 300))
    connect_wait = float(rtt_cfg.get("connect_timeout_s", 3.0))

    # cfg 组装单一事实源 (WB-20260919-06); 非法配置显式报错不静默回落 (F-103)
    try:
        pair = resolve_openocd_cfg(workspace=workspace)
    except OpenocdCfgError as e:
        return {"status": "error", "method": "rtt", "lines": 0, "error": str(e)}
    base_cmd = [load_machine()["openocd_exe"], "-c", "bindto 127.0.0.1",
                "-f", pair["interface"], "-f", pair["target"]]
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
                creationflags=creationflags, cwd=workspace)

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
                "rtt start", f"rtt polling_interval {_RTT_POLL_INTERVAL_MS}",
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
            last_data_at = None
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                data_sock.settimeout(max(0.05, min(0.5, deadline - time.time())))
                try:
                    chunk = data_sock.recv(4096)
                    if chunk:
                        buf += chunk
                        last_data_at = time.time()
                except socket.timeout:
                    pass
            data_sock.close()

            text = buf.decode("utf-8", errors="replace")
            result = {
                "status": "ok", "method": "rtt",
                "timeout_sec": timeout_s,
                "lines": len([ln for ln in text.splitlines() if ln.strip()]),
                "duration_sec": round(time.time() - started, 1),
                "raw_length": len(text),
                "_text": text,
            }
            stall = _stall_seconds(last_data_at, time.time(), bool(buf))
            if stall:
                result["stall_sec"] = stall
                result["warning"] = (
                    f"RTT 输出在窗口结束前已静默 {stall}s —— 先怀疑环指针死锁"
                    "(RdOff>WrOff, 写入被整条跳过) 或固件停止输出，"
                    "不要据此判定固件卡死；复位/断电重上再采一次")
            return result

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
