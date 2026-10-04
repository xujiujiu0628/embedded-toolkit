"""工作台工具库共享路径解析。

TOOLKIT_ROOT 从本文件位置推导（scripts/ 的父目录）。
工程根发现: 从给定目录向上逐级找 .workbench/config.json
（兜底 .embeddedskills/config.json, 迁移过渡期兼容）。
"""
import json
import os
import sys

TOOLKIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FALLBACK_WARNED = False  # machine.example.json 回退警告只发一次

_PROJECT_MARKERS = (".workbench/config.json", ".embeddedskills/config.json")


def find_project_root(start):
    """从 start 向上逐级查找工程根, 找不到返回 None。"""
    d = os.path.abspath(start)
    while True:
        for marker in _PROJECT_MARKERS:
            if os.path.isfile(os.path.join(d, marker)):
                return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_machine():
    """读 toolkit/machine.json (本机工具链绝对路径, 本机文件不入库)。

    machine.json 缺失时回退到入库模板 machine.example.json 并一次性警告——
    新克隆上测试与离线工具因此直接可跑; 占位路径一旦被真机构建/烧录用到,
    会以自解释的 FileNotFoundError 报错 (显式指引优于静默防御, F-011)。
    两档皆缺 → FileNotFoundError 且信息含可行动指引。"""
    global _FALLBACK_WARNED
    path = os.path.join(TOOLKIT_ROOT, "machine.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    example = os.path.join(TOOLKIT_ROOT, "machine.example.json")
    if os.path.isfile(example):
        if not _FALLBACK_WARNED:
            _FALLBACK_WARNED = True
            print("[machine] machine.json 缺失, 暂用 machine.example.json 的占位路径"
                  " (仅够测试/离线工具)——真机构建/烧录/采集前请复制为 machine.json"
                  " 并填入本机绝对路径", file=sys.stderr)
        with open(example, encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(
        f"未找到 machine.json: {path}——请复制 machine.example.json 为"
        " machine.json 并填入本机工具链绝对路径 (machine.json 为本机文件, 不入库)")


def toolkit_version():
    with open(os.path.join(TOOLKIT_ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def _ver_tuple(s):
    return tuple(int(x) for x in s.split(".")[:2])


def version_ok(actual, minimum):
    return _ver_tuple(actual) >= _ver_tuple(minimum)


def atomic_write_json(path, data):
    """原子 JSON 写 (F-022): 进程级 tmp 名 + os.replace, 强制 LF 行尾。

    release 等独立脚本的读改写落盘统一走这里, 杜绝 truncate 写撕裂
    (撕裂读会喂下游"损坏→清空"链, 同 F-019 教训)。
    2026-09-05 F-067b: 原 error_db_grow 已随 Keil 退役区拆 archive,
    从消费方名单移除。
    tmp 名带 pid = 双进程并发写同一目标不互顶 (F-023, 与 runtime 侧
    save_json_file 同口径; runtime 按脚本自含惯例保留各自拷贝)。
    F-198 T4: dump/序列化中途抛错 → unlink tmp 后原样 raise (F-133/j
    runtime 侧同口径; 残骸毒化目录扫描类消费方且掩盖失败现场)。
    成功路径 os.replace 之后语义零动 (含 replace 失败面, 见 P 面注记)。
    """
    path = str(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except BaseException:
        # BaseException: Ctrl-C 中途同样不留残骸; 原异常原样上抛不吞不裹。
        try:
            os.unlink(tmp)   # missing_ok 语义 (open 未及建文件时吞 FileNotFoundError)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


# ── 跨进程文件锁 (F-219 D3/D6) ───────────────────────────────────────────
# atomic_write_json 防的是**撕裂** (半截文件), 不防**丢更新**: 两个进程
# 各自 load 旧值、各自改、各自 replace, 后写的覆盖先写的, 先写进程的改动
# 无声蒸发。凡「读-改-写」同一 JSON 而无锁, 都有此竞态 (D3 gcc_build 写回
# config.json / D6 hw_lease 写 meta 旁车)。
#
# 锁本体 = 同 hw_lease 口径的 OS 级字节锁: Windows msvcrt.locking /
# POSIX fcntl.flock。**不是** 锁目标文件本身 (那会与 os.replace 打架:
# replace 换 inode, 锁随之失效), 而是锁一把**旁路哨兵文件** ——
# <target>.lock, 只创建不删, 生命周期与目标无关。

try:
    import fcntl as _fcntl          # noqa: F401  (POSIX)
    _HAVE_FCNTL = True
except ImportError:                  # pragma: no cover - Windows 走 msvcrt
    _HAVE_FCNTL = False

if os.name == "nt":
    import msvcrt as _msvcrt         # noqa: F401  (Windows 主平台)


def _lock_fd(fd, blocking):
    if os.name == "nt":
        mode = _msvcrt.LK_LOCK if blocking else _msvcrt.LK_NBLCK
        _msvcrt.locking(fd, mode, 1)
    elif _HAVE_FCNTL:
        op = _fcntl.LOCK_EX if blocking else _fcntl.LOCK_EX | _fcntl.LOCK_NB
        _fcntl.flock(fd, op)
    # 其他平台: 无 OS 级锁 → 退化为不加锁 (best effort, 不假装有保证)


class file_lock:
    """跨进程排他锁的上下文管理器, 锁 <path>.lock 旁路哨兵。

        with file_lock(target_path):
            data = load(target_path)
            data["x"] = 1
            atomic_write_json(target_path, data)

    blocking=False 时抢不到抛 BlockingIOError (供"试一下就走"的场景);
    blocking=True (默认) 阻塞等待。

    **不删哨兵文件**: 删了会让并发者各自新建不同 inode 而锁不到同一把锁。
    哨兵是 0 字节, 常驻无成本。
    """

    def __init__(self, target_path, blocking=True):
        self._path = str(target_path) + ".lock"
        self._blocking = blocking
        self._fh = None

    def __enter__(self):
        d = os.path.dirname(self._path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._fh = open(self._path, "a+b")   # a: 不截断, 跨进程共用同一 inode
        try:
            _lock_fd(self._fh.fileno(), self._blocking)
        except (OSError, BlockingIOError):
            self._fh.close()
            self._fh = None
            raise
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                if os.name == "nt":
                    _msvcrt.locking(self._fh.fileno(), _msvcrt.LK_UNLCK, 1)
                elif _HAVE_FCNTL:
                    _fcntl.flock(self._fh.fileno(), _fcntl.LOCK_UN)
            except OSError:
                pass          # 解锁失败不掩盖主流程异常
            self._fh.close()
            self._fh = None
        return False


REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")


def load_ref():
    """读 55 外设寄存器知识库 (F-157 P2-3: gen_periph/phase_minus_one/
    rm_lookup 三份逐字拷贝收编到 Layer 0)。"""
    with open(REF_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    """文件字节哈希 (F-157 P2-3: release/release_audit 双份收编到 Layer 0)。"""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def force_utf8_streams():
    """stdout/stderr 强制 UTF-8 (F-157 P2-3: 五处 reconfigure 咒语收编)。

    F-025 先例: Windows ANSI 代码页 (GBK) 下 ensure_ascii=False 的中文
    输出会崩或乱码; StringIO 等无 reconfigure 的流静默跳过 (测试缝)。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
