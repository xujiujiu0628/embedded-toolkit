r"""机器级设备锁 (F-145, 总工单 v2 B-1) — 同一探针/板子同时只被一个 agent 占用。

借鉴 agentic-hil 的 machine-wide lease 与 jumpstarter 的跨团队硬件租借。
这是工单一 P1-3 (F-127 state 写锁) 的**功能级**答案: state 锁防数据竞争,
设备锁防硬件资源竞争——两个并发 verify 同时抢 ST-Link, 后者烧到一半被
前者复位, 这类事故数据锁管不着。

与既有两层的分界 (互不替代, 互不干扰):
  - F-019 save_json_file 原子替换: 防单文件撕裂读;
  - F-127 state_write_lock: 防同一 workspace state.json 读改写丢更新;
  - F-145 设备锁 (本模块): 防跨进程/跨 clone 的物理设备并发占用。

三条纪律 (总工单 v2 修订):
  1. 锁本体 = OS 级文件锁: Windows `msvcrt.locking` / POSIX `fcntl.flock`,
     进程崩溃 = OS 自动释放。**不做 PID 探活** (F-117: Windows os.kill 是
     TerminateProcess 不是探活), **不做 mtime 超期回收** (OS 锁无泄漏,
     不需要兜底); 陈旧 .meta.json 旁车在下次成功获取时整体覆写。
  2. 锁位置 = 机器级用户目录 `%USERPROFILE%\.embedded-toolkit\device-locks\
     <device>.lock` (同一台机的两份 clone 抢同一块板也能互斥), 元数据
     acquired_at/pid/purpose/workspace 写同名 `.meta.json` 旁车。
  3. 冲突 fail-fast → error 含 `resource_busy` 并点名持有者 (purpose +
     acquired_at); `--lease-wait N` / acquire(wait=N) 提供有界等待。

默认锁设备名 "stlink"——verify 与 openocd_run 同名互斥; 多探针机器后续
可经 machine.json 扩展设备名 (登记不实现, 不藏需求)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from runtime_common import now_iso, output_json
from wb_common import TOOLKIT_ROOT

DEFAULT_DEVICE = "stlink"
POLL_INTERVAL = 0.2   # --lease-wait 有界等待的轮询间隔 (秒)
# 机器级用户目录 (跨 clone 共享); ETK_DEVICE_LOCK_DIR 供多环境/测试重定向
DEVICE_LOCK_DIR = os.environ.get("ETK_DEVICE_LOCK_DIR") or os.path.join(
    os.path.expanduser("~"), ".embedded-toolkit", "device-locks")

if os.name == "nt":
    import msvcrt  # noqa: F401  (Windows 主平台: 字节范围锁)
else:
    import fcntl  # noqa: F401  (POSIX: 整文件 flock)


def lock_paths(device: str = DEFAULT_DEVICE) -> tuple[str, str]:
    """设备锁文件与元数据旁车路径 (机器级用户目录, 跨 clone 共享)。"""
    device = "".join(c if c.isalnum() or c in "-_" else "_" for c in device)
    base = os.path.join(DEVICE_LOCK_DIR, f"{device}.lock")
    return base, base + ".meta.json"


def _lock_byte(fd: int) -> None:
    """非阻塞独占锁 1 字节; 被占抛 OSError。"""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_byte(fd: int) -> bool:
    """解锁 1 字节; 返回是否成功。fd 失效 (提前 close/双释放) 不崩——
    如实报 False 由调用方定夺 (F-161 审核退回 M-1: release 契约是恒返回
    dict, verify 收尾 8 处出口依赖它不得 traceback)。"""
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def _read_meta(meta_file: str) -> dict | None:
    """读持有者元数据旁车; 不存在/损坏 → None (崩溃残留, 诚实标注)。"""
    try:
        with open(meta_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(meta_file: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(meta_file), exist_ok=True)
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))


def _holder_message(meta: dict | None, device: str, waited: float) -> str:
    """可行动的冲突报错: 点名持有者 purpose + 获取时间 + 两条出路。"""
    if meta:
        who = (f"purpose={meta.get('purpose')!r} "
               f"pid={meta.get('pid')} "
               f"acquired_at={meta.get('acquired_at')}")
    else:
        who = "持有者元数据缺失 (持锁进程崩溃残留; 锁已随进程退出被 OS 释放, 重试即得)"
    wait_note = f" (已等 {waited:g}s)" if waited else ""
    return (f"resource_busy: 设备锁被占用{wait_note}: device={device!r} "
            f"持有者 {who} — 等其释放或用 --lease-wait N 有界等待; "
            f"若持有进程已死, OS 锁随进程退出自动释放, 直接重试即可")


def acquire(device: str = DEFAULT_DEVICE, *, purpose: str = "",
            workspace: str | None = None, wait: float = 0.0) -> dict:
    """获取设备锁 (OS 级字节锁, 非阻塞尝试 + 可选有界等待)。

    成功返回 {"ok": True, "device", "lock_file", "_fd", ...} —— **_fd 必须
    随 dict 原样保留到 release**: OS 锁的解锁要求同 fd; 进程崩溃则 fd 随
    进程关闭, OS 自动放锁, 无需任何回收机制。
    冲突返回 {"ok": False, "error": "...resource_busy... 持有者..."}。"""
    lock_file, meta_file = lock_paths(device)
    deadline = time.time() + max(0.0, wait)
    waited = 0.0
    while True:
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        except OSError as e:
            return {"ok": False,
                    "error": f"设备锁文件不可开 ({lock_file}): {e}"}
        try:
            _lock_byte(fd)
        except OSError:
            os.close(fd)
            if time.time() >= deadline:
                meta = _read_meta(meta_file)
                return {"ok": False,
                        "error": _holder_message(meta, device, waited)}
            time.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            continue
        break   # 拿到锁

    token = f"{os.getpid():d}-{time.time_ns():d}"
    _write_meta(meta_file, {
        "acquired_at": now_iso(),
        "pid": os.getpid(),
        "token": token,
        "purpose": purpose,
        "workspace": workspace or "",
        "toolkit_root": TOOLKIT_ROOT,
    })
    return {"ok": True, "device": device, "token": token,
            "lock_file": lock_file, "meta_file": meta_file, "_fd": fd,
            "purpose": purpose}


def release(lease: dict | None) -> dict:
    """释放设备锁: 解锁 → 关 fd → 清旁车。只接受 acquire 的原返回值
    (OS 锁只能由持锁 fd 解——别的进程想放也放不掉, 天然防误删)。

    F-161 审核退回:
      M-1: 恒返回 dict 不裸抛——fd 失效 (提前 close/双释放) 走 ok=False,
           锁随 fd 关闭已被 OS 释放, 重取不受影响;
      M-2: 锁本体文件留置不删——删除引入 "A 解锁→B 锁住旧 inode→A remove
           →C 建新 inode" 的共持窗口 (OS 锁锁 inode 不锁路径)。锁信号在
           字节锁不在文件存在性, 空文件留置无害; 只清 meta 旁车。"""
    if not lease or not lease.get("ok"):
        return {"ok": True, "note": "无锁可放 (acquire 未成功)"}
    fd = lease.get("_fd")
    lock_file = lease.get("lock_file", "")
    meta_file = lease.get("meta_file", "")
    if not isinstance(fd, int) or not lock_file:
        return {"ok": False,
                "error": "lease dict 缺 _fd/lock_file — 必须传 acquire 的原返回值"}
    unlocked = _unlock_byte(fd)
    try:
        os.close(fd)
    except OSError:
        pass   # fd 可能已随失效路径关闭
    try:
        os.remove(meta_file)
    except OSError:
        pass   # meta 留置无害 (下次 acquire 覆写)
    if not unlocked:
        return {"ok": False,
                "error": f"解锁失败: fd {fd} 无效 (已被提前 close/双释放); "
                         f"锁已随 fd 关闭由 OS 释放, 重取不受影响"}
    return {"ok": True}


def holder_info(device: str = DEFAULT_DEVICE) -> dict | None:
    """当前持有者元数据 (诊断/CLI status 用)。注意: 持锁进程崩溃后旁车
    残留, 本函数可能返回陈旧信息 — 锁的真实状态以 OS 字节锁为准。"""
    _lock_file, meta_file = lock_paths(device)
    return _read_meta(meta_file)


def main() -> int:
    """人工排查入口: status / acquire / release。自动化调用方走 API
    (verify.py / openocd_run.py 已接入), 本 CLI 供"锁被谁占着"手工排查。"""
    ap = argparse.ArgumentParser(description="机器级设备锁 (F-145)")
    ap.add_argument("--device", default=DEFAULT_DEVICE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="查看当前持有者元数据")
    p_acq = sub.add_parser("acquire", help="手动获取锁 (调试用)")
    p_acq.add_argument("--purpose", required=True)
    p_acq.add_argument("--workspace", default=None)
    p_acq.add_argument("--wait", type=float, default=0.0)
    sub.add_parser("release", help="释放锁 (仅限本进程经本 CLI 所取)")
    args = ap.parse_args()

    if args.cmd == "status":
        info = holder_info(args.device)
        output_json({"ok": True, "device": args.device,
                     "held": info is not None, "holder": info})
        return 0
    if args.cmd == "acquire":
        rs = acquire(args.device, purpose=args.purpose,
                     workspace=args.workspace, wait=args.wait)
        output_json({k: v for k, v in rs.items() if k != "_fd"})
        return 0 if rs.get("ok") else 1
    # release 子命令拿不到上一个 CLI 进程的 fd — OS 锁只认持锁 fd, 如实
    # 说明而不是假装释放; 正常清场 = 持有者自己的工具进程走完, 或进程
    # 退出时 OS 自动放锁。
    output_json({"ok": False,
                 "error": "release CLI 无法跨进程解锁 (OS 锁只认持锁 fd) — "
                          "锁随持有进程退出自动释放; 强杀后重试即可"})
    return 1


if __name__ == "__main__":
    sys.exit(main())
