"""runtime 共享层 (F-029): wb/openocd/serial 三 runtime 的单一事实源。

背景: 三 runtime 曾按"脚本自含"惯例各存一份同源实现, 实测 22 个同名符号中
12 个仅 docstring/换行差异 —— 本模块收编规范版, runtime 侧 import 再导出,
保持 `mod.X` 调用面不变 (test_writeback_guards 的 RUNTIMES 参数化直接受益)。

真分叉符号 (make_result 双契约 / 同名异物的 make_timing/parameter_context /
配置读写路径策略 / resolve_param) 按 F-029 计划 Task 3-5 处理, 不强行合并。

边界 (F-029 全局约束): 本模块仅 stdlib, 不 import 三 runtime 中任何一个 (防环);
与 wb_common (路径解析层) 互不渗透。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

# 状态/配置文件锚 (三 runtime 实测取值一致; 随状态读写族/工程配置族上提, F-029 T4/T5)
STATE_DIR_NAME = ".workbench"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE_NAME = "config.json"

# F-222: file_lock 由 wb_common 单点提供 (Layer 0)。wb_common 只依赖标准库,
# 不 import 本模块 → 无循环依赖。锁共享而非各脚本各抄一份, 是 D3/D6 与
# save_skill_section 三处写入方能互斥的前提: **锁必须按目标文件由所有
# 写入方共用**, 两处各抄一把锁等于没锁。
from wb_common import file_lock  # noqa: E402  (F-222)


class JSONCorruptError(ValueError):
    """JSON 文件损坏/非 UTF-8/顶层非对象 — 读改写场景必须显式处理。

    load_json_file 的"损坏返回 {}"对只读消费方是容错 (F-007), 对读改写方
    是数据清空器: 当空读入 → 合并写入 → 存量内容无声蒸发 (F-020)。"""


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def workspace_root(workspace: str | None = None) -> Path:
    if not is_missing(workspace):
        return Path(str(workspace)).expanduser().resolve()
    return Path.cwd().resolve()


def normalize_path(value: str | None) -> str:
    """路径规范化 (wb/ocd 规范版): 恒 expanduser+resolve 成绝对路径。

    注意: serial_runtime.normalize_path 是独立契约 (可带 base、相对输入不
    resolve), 同名异物——见 F-029 T3 裁决, 勿'统一'进本函数。"""
    if is_missing(value):
        return ""
    return str(Path(str(value)).expanduser().resolve())


def _first_resolved(mapping: dict, keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        value = mapping.get(key)
        if not is_missing(value):
            return value, key
    return None, None


def load_json_file(path: str | Path) -> dict:
    """加载 JSON 文件，不存在返回空字典"""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_json_strict(path: str | Path) -> dict:
    """读改写专用加载: 损坏即抛 JSONCorruptError, 不存在返回 {}。"""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise JSONCorruptError(f"{file_path} 不可解析: {e}") from e
    if not isinstance(data, dict):
        raise JSONCorruptError(f"{file_path} 顶层须为 JSON 对象")
    return data


def save_json_file(path: str | Path, data: dict) -> None:
    """原子保存: 先写 .tmp 再 os.replace — 并发读方要么看到旧文件要么看到
    新文件, 不再有半截 JSON (F-019: 撕裂读曾把下游引入"损坏→清空"链)。
    注意: 原子替换只防撕裂, 不防 read-modify-write 丢更新 (F-127, 见 state_write_lock)。
    F-157: newline="\n" 与 wb_common.atomic_write_json 行尾口径统一 (此前
    Windows 上 CRLF/LF 两套并存, 注释固化 + 收敛为 LF)。"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.{os.getpid()}.tmp")  # F-023: pid 防双进程互顶
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    try:
        os.replace(tmp_path, file_path)
    except OSError:
        # F-133/j: 写失败 (目标被锁/盘满等) 不留 .tmp 残骸 — 残骸毒化目录
        # 扫描类消费方, 且掩盖失败现场
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# ── workspace state 读改写锁 (F-127, 工单 P1-3) ────────────────────────
# 缺陷: serial_mux start 的"取快照 → 起子进程等数秒 → 旧快照整体覆盖"与
# update_state_entry 的无锁 RMW 互相静默回滚对方写入 (原子替换只防撕裂)。
# 锁: O_CREAT|O_EXCL lockfile + 超时重试 + finally 删除, 零第三方依赖。

STATE_LOCK_STALE_SECONDS = 30.0
_STATE_LOCK_THREADS = threading.Lock()  # 同进程线程互斥 (lockfile 只辨进程不辨线程)


def _state_lock_path(workspace: str | None = None) -> Path:
    return workspace_root(workspace) / STATE_DIR_NAME / (STATE_FILE_NAME + ".lock")


def _state_lock_is_stale(lock_path: Path) -> bool:
    """陈旧锁回收判据。

    F-117 教训内化: Windows 上 os.kill(pid, 0) 是 TerminateProcess 不是探活
    ——这里绝不重蹈。跨进程判死只在 POSIX 用 os.kill(pid,0); Windows 无法廉价
    探活, 只认超龄 (mtime 超 STATE_LOCK_STALE_SECONDS)。holder==本 pid 不回收
    (线程共享 pid, 误回收会破坏线程互斥), 同样落到超龄兜底。

    F-213: 空/坏锁文件不再回落到 pid=0。原实现 `int(text or "0")` 在锁文件
    为空 (O_EXCL 建锁与写 pid 之间被 kill 的窗口) 时得 holder=0, 而
    os.kill(0, 0) 的语义是"给**当前进程组**发信号 0" —— 必然成功 → 返回
    False (判活) → 空锁永不被回收, 持锁方只能等超时降级。现按超龄兜底处理,
    与其它读不到锁的路径同口径。"""
    try:
        raw = lock_path.read_text().strip()
        mtime = lock_path.stat().st_mtime
    except OSError:
        return True  # 读不到的锁文件按陈旧处理
    if not raw:
        # 空锁 = 建锁后未写完 pid 的窗口, holder 不可知 → 只认超龄
        return time.time() - mtime > STATE_LOCK_STALE_SECONDS
    try:
        holder = int(raw)
    except ValueError:
        return True  # 非数字内容按陈旧处理
    if holder <= 0:
        # 非正 pid 无法探活 (0 = 进程组, 负值 = 进程组), 一律走超龄
        return time.time() - mtime > STATE_LOCK_STALE_SECONDS
    if holder == os.getpid():
        return time.time() - mtime > STATE_LOCK_STALE_SECONDS
    if os.name != "nt":
        try:
            os.kill(holder, 0)   # POSIX 真探活 (信号 0 不杀进程)
            return False
        except ProcessLookupError:
            return True
        except PermissionError:
            return False         # 活着但属于别人
        except OSError:
            return True
    return time.time() - mtime > STATE_LOCK_STALE_SECONDS


def _lock_identity(lock_path: Path) -> tuple | None:
    """锁文件身份 = (st_dev, st_ino), 供陈旧锁回收做 compare-and-swap。

    F-215: os.replace 无条件移动, 无法区分"搬走的是我判过的那把陈旧锁"与
    "搬走的是别人刚建的活锁"。inode 在 rename 前后保持不变, 故先记身份、
    搬完再验——不等则说明搬错了, 归还即可。

    返回 None = 读不到身份 (文件已消失/无 stat), 调用方须放弃认领。
    """
    try:
        st = lock_path.stat()
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _restore_claimed_lock(claimed: Path, lock_path: Path) -> bool:
    """把 CAS 误搬走的**他人活锁**归还到原位; 返回是否归位。

    F-215 的 CAS 第③步原写法是 `os.link(claimed, lock_path)` + 一个
    `except OSError: pass`。三号复审 N-9 指出: 硬链在 FAT/exFAT/部分 SMB
    上根本不被支持 (EPERM/ENOTSUP), 此时**归还失败被同一个 except 吞掉**
    —— 活锁被晾在 `<lock>.<pid>.claim`, 而 `lock_path` 不存在, 后续竞争者
    照常 O_EXCL 建锁 → 双持锁 (正是 CAS 要防的那件事), 且现场零线索。

    F-232 拆分三条路径:
      FileExistsError → 第三方已建新锁, **让路**是设计内行为, 不告警;
      其它 OSError     → 落 stderr 告警 (点名 os.link 与可能的文件系统),
                         并用 rename 退路归位 (目标不存在时);
      成功             → 删掉 claim 副本。

    退路为何不强求原子: rename 会覆盖第三方锁, 故先探 `lock_path` 不存在
    再搬 —— 竞态窗比硬链大, 但"还原一把活锁"比"静默丢掉锁"更接近原意;
    探到已存在则放弃归位 (放弃也是显式的, 由调用方继续重试争 O_EXCL)。
    """
    try:
        os.link(claimed, lock_path)
    except FileExistsError:
        return False          # 第三方已建新锁 → 让路 (设计内, 不告警)
    except OSError as e:
        print(f"Warning: 锁归还失败, 硬链接不可用 (文件系统可能是 FAT/exFAT/"
              f"部分 SMB; os.link: {e}); 改用 rename 退还: {lock_path}",
              file=sys.stderr)
        if lock_path.exists():
            print(f"Warning: 第三方已建新锁, 放弃归还; 原活锁留痕于 {claimed}",
                  file=sys.stderr)
            return False
        try:
            os.replace(claimed, lock_path)
            return True
        except OSError as e2:
            print(f"Warning: rename 退还也失败 ({e2}); 活锁遗留在 {claimed}",
                  file=sys.stderr)
            return False
    try:
        claimed.unlink()
    except OSError:
        pass
    return True


@contextmanager
def state_write_lock(workspace: str | None = None, *, timeout: float = 5.0):
    """workspace state 读改写的进程+线程互斥锁 (best-effort)。

    两层: 进程内 threading 锁 (lockfile 只辨进程不辨线程) + 跨进程
    O_EXCL lockfile。等锁超过 timeout → 向 stderr 诚实告警后降级无锁执行
    ——state.json 是可再生缓存, 工具卡死比丢一次更新更糟。锁文件随 finally 删除。"""
    lock_path = _state_lock_path(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    got_thread = _STATE_LOCK_THREADS.acquire(timeout=timeout)
    acquired = False
    try:
        if not got_thread:
            print(f"Warning: state.json 写锁等待超时 ({timeout}s), "
                  f"降级无锁执行, 并发丢更新风险自担 (本进程内): {lock_path}",
                  file=sys.stderr)
            yield
            return
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
                acquired = True
                break
            except FileExistsError:
                if _state_lock_is_stale(lock_path):
                    # F-215 订正 F-213: F-213 用 os.replace 做"原子占位"并注释
                    # "另一方 rename 失败即知锁已被重建"——**这是错的**。
                    # os.replace 是无条件移动, 不做 compare-and-swap: 目标有无
                    # 竞争者它都照搬。三号复审 Medium-3 实测复现双持锁——
                    # P2 把 P1 刚建好的**活锁**整个搬走, 双双 O_EXCL 成功。
                    #
                    # F-215 改为真正的 CAS 三步:
                    #   ① 记下"我判陈旧时"这把锁的身份 (st_dev, st_ino)
                    #   ② rename 把它挪到 claim 名下 (rename 保持 inode 身份)
                    #   ③ 校验搬走的正是我判过的那把; 不是 → 说明搬走了
                    #      他人的活锁, 用 os.link 原子归还 (目标存在则失败)
                    # 认领成功才删除, 之后回到重试争 O_EXCL。
                    # _lock_identity 内部已把 OSError 兜成 None, 此处不再
                    # 包 try/except (三号复审 N-6: 外层 except 永不触发,
                    # 会让人误以为有两条失败路径)。
                    ident = _lock_identity(lock_path)
                    if ident is None:
                        time.sleep(0.01)
                        continue
                    claimed = lock_path.with_name(
                        lock_path.name + f".{os.getpid()}.claim")
                    try:
                        os.replace(lock_path, claimed)
                    except OSError:
                        continue          # 已被他人搬走 → 重试
                    moved = _lock_identity(claimed)
                    if moved != ident:
                        # 搬走的不是我们判陈旧的那把 = 他人活锁, 立刻归还。
                        # 归还策略与告警收在 _restore_claimed_lock 内
                        # (F-232 N-9: 硬链不可用的失败不再静默)。
                        _restore_claimed_lock(claimed, lock_path)
                        continue
                    try:
                        claimed.unlink()  # 确认是陈旧锁, 安全回收
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    print(f"Warning: state.json 写锁等待超时 ({timeout}s), "
                          f"降级无锁执行, 并发丢更新风险自担: {lock_path}",
                          file=sys.stderr)
                    break
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass
        if got_thread:
            _STATE_LOCK_THREADS.release()


def output_json(data: dict, *, indent: int = 2) -> None:
    """输出 JSON 到 stdout"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass   # F-133/g: StringIO 等重定向流无 reconfigure — 尽力而为
    print(json.dumps(data, ensure_ascii=False, indent=indent), flush=True)


# ── 进程/结果构造族 (F-029 T3) ──────────────────────────────────────
# wb/ocd 两份逐字节相同, 上提为规范版 (wb 原文)。serial 侧: make_result 是
# 转调本模块 make_result 的薄适配器 (success:bool 入参签名冻结);
# make_timing/parameter_context 为同名异物, 契约归 serial 本地 (T3 裁决)。

def hidden_subprocess_kwargs() -> dict:
    """Windows 隐藏控制台 kwargs; 非 win32 恒 {} (F-027 平台守卫随体上提)。"""
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def get_state_entry(state: dict | None, key: str) -> dict:
    if not isinstance(state, dict):
        return {}
    value = state.get(key, {})
    return value if isinstance(value, dict) else {}


def compact_dict(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def build_artifacts(**paths: str) -> dict:
    return {key: normalize_path(str(value)) for key, value in paths.items() if not is_missing(value)}


def make_result(
    *,
    status: str,
    action: str,
    summary: str,
    details: dict | None = None,
    context: dict | None = None,
    artifacts: dict | None = None,
    metrics: dict | None = None,
    state: dict | None = None,
    next_actions: list[str] | None = None,
    timing: dict | None = None,
    error: dict | None = None,
) -> dict:
    result = {"status": status, "action": action, "summary": summary, "details": compact_dict(details)}
    optional = {
        "context": compact_dict(context),
        "artifacts": compact_dict(artifacts),
        "metrics": compact_dict(metrics),
        "state": compact_dict(state),
        "timing": compact_dict(timing),
    }
    for key, value in optional.items():
        if value:
            result[key] = value
    if next_actions:
        result["next_actions"] = [item for item in next_actions if item]
    if error:
        result["error"] = compact_dict(error)
    return result


def make_timing(started_at: str, elapsed_ms: int | float) -> dict:
    return {"started_at": started_at, "finished_at": now_iso(), "elapsed_ms": int(elapsed_ms)}


def parameter_context(*, provider: str, workspace: str | None = None, parameter_sources: dict | None = None, config_path: str | None = None) -> dict:
    context = {"provider": provider, "workspace": str(workspace_root(workspace))}
    if parameter_sources:
        context["parameter_sources"] = compact_dict(parameter_sources)
    if not is_missing(config_path):
        context["config_path"] = normalize_path(str(config_path))
    return context


# ── 状态读写族 (F-029 T4) ──────────────────────────────────────────
# 三件套同源实现上提; save_workspace_state / update_state_entry 的落盘形态是
# 真语义分叉 (实测订正, 非计划原稿的"纯 docstring 差"): wb==serial 序列化
# (绝对路径→workspace 相对 POSIX, 即 _serialize_state_value), ocd 原样存。
# 以 serialize 参数注入 — 默认 None 即 ocd 语义, wb/serial 薄壳绑钩。
# 分叉形状由 test_runtime_contract.StateWireShapeTests 钉住, 防被"顺手统一"。

def _serialize_state_value(value: Any, workspace: Path) -> Any:
    if isinstance(value, dict):
        return {key: _serialize_state_value(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_state_value(item, workspace) for item in value]
    if not isinstance(value, str) or "://" in value:
        return value

    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    try:
        return Path(os.path.relpath(path.resolve(), workspace)).as_posix()
    except ValueError:
        return value


def load_workspace_state(workspace: str | None = None) -> dict:
    return load_json_file(workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME)


def load_workspace_state_for_update(workspace: str | None = None) -> dict:
    """读改写前的状态加载 (F-019): 损坏 → 隔离到 .corrupt 保留现场 → 按 {} 继续。

    state.json 是可再生缓存, 不像 config.json 那样拒绝写回; 隔离保证损坏
    原文可手工恢复, 旧实现"损坏当空读入→覆写"会让其他条目无声蒸发。"""
    ws = workspace_root(workspace)
    file_path = ws / STATE_DIR_NAME / STATE_FILE_NAME
    try:
        return load_json_strict(file_path)
    except JSONCorruptError as e:
        corrupt = file_path.with_name(file_path.name + ".corrupt")
        try:
            os.replace(file_path, corrupt)
            print(f"Warning: state.json 损坏, 原文件移至 {corrupt}, "
                  f"按新内容重建: {e}", file=sys.stderr)
        except OSError:
            print(f"Warning: state.json 损坏且隔离失败, 按新内容重建: {e}",
                  file=sys.stderr)
        return {}


def save_workspace_state(state: dict, workspace: str | None = None, *, serialize=None) -> Path:
    ws = workspace_root(workspace)
    file_path = ws / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, serialize(state, ws) if serialize else state)
    return file_path


def update_state_entry(category: str, record: dict, workspace: str | None = None, *, serialize=None) -> dict:
    ws = workspace_root(workspace)
    # F-127 (工单 P1-3): 持锁 → 读最新 → 改 → 写。旧版无锁 RMW 与并发写者
    # 互相静默回滚 (serial_mux 长快照覆写 / 两个工具同时 update 不同 category)。
    with state_write_lock(workspace):
        state = load_workspace_state_for_update(workspace)
        entry = {**record, "timestamp": record.get("timestamp") or now_iso()}
        state[category] = serialize(entry, ws) if serialize else entry
        file_path = save_workspace_state(state, workspace, serialize=serialize)
    return {
        "workspace": str(ws),
        "file": str(file_path),
        "updated_keys": [category],
        category: state[category],
    }


# ── ESP 后端判据 (F-190/M-1: 三标记 OR 单一事实源) ─────────────────────
# 原 verify.py 私有 _esp_backend_mode 上收: verify import 再导出 (F-057
# 形态, 调用面不变), release G0.5 闸同源消费——两份 OR 逻辑副本即分层违例
# (test_f190_release_chain.T2SingleSourceTests 钉 identity)。

def _uart_capture_is_esp(config) -> bool:
    """capture.backend=uart 是否为 ESP 标记 (F-231).

    缺省/`reset=esptool` 沿用旧语义=ESP (老配置零变化); STM32 工程经
    `reset=openocd|none` 显式声明"复位不归 esptool", 此时 uart 采集是
    Cortex-M 证据线, 不该触发 ESP 闸。取值归一与 esp_runtime 同口径
    (strip+lower), 免得大小写变体一边放行一边拦。
    """
    cap = (config or {}).get("capture") or {}
    if cap.get("backend") != "uart":
        return False
    reset = str(cap.get("reset") or "esptool").strip().lower()
    return reset == "esptool"


def esp_backend_mode(config) -> bool:
    """F-174/I-1 (终审#2): ESP 后端判据——OpenOCD/ST-Link 专属动作的闸根。

    builder=idf / flash.backend=esptool / capture.backend=uart 任一在场
    即为 ESP 运行: post_reset 与 hardfault 层 2 都是占 ST-Link 的 Cortex-M
    动作, 必须整体抑制。三标记 OR 而非 AND: 混配 (漏写其一) 时宁可停
    Cortex 动作, 也不能拿 ESP 目标去跑 OpenOCD。

    F-231 收窄: capture.backend=uart 只在缺省/esptool 复位形态下算 ESP
    标记——STM32 工程的 uart 采集由 `capture.reset=openocd|none` 显式
    声明复位归属 (f103-body 证据线), 否则 F-231 会在入口被 GAP-F-19
    误拦。老配置不写 reset 时行为逐字节不变。"""
    cfg = config or {}
    if cfg.get("builder") == "idf":
        return True
    if (cfg.get("flash") or {}).get("backend") == "esptool":
        return True
    return _uart_capture_is_esp(cfg)



def esp_backend_config_errors(config) -> list:
    """GAP-F-19 (维护者裁定 fail-fast, F-190/T3): ESP 混配配置校验。

    规则: ESP 标记任一在场 (判定根 = esp_backend_mode; F-231 起
    capture.backend=uart 仅在 reset 缺省/esptool 时算标记) → builder、
    flash.backend、capture.backend 三键必须齐且取值在 ESP 合法集
    (builder=idf / flash.backend=esptool / capture.backend∈{uart})。
    合规返回 []; 违规返回逐条人读项 (点名键 + 当前值——键缺席时报缺省
    派发值 + 正确取值), 调用方须在任何构建/烧录动作之前显式报错退出。
    无标记 (STM32 缺省) 恒 []——缺省路径零触碰。"""

    def _current(value, default):
        return repr(value) if value is not None else "缺省 %r" % default

    cfg = config or {}
    if not esp_backend_mode(cfg):
        return []
    errs = []
    builder = cfg.get("builder")
    if builder != "idf":
        errs.append('builder: 当前 %s — 需 "builder": "idf"'
                    % _current(builder, "gcc"))
    flash_backend = (cfg.get("flash") or {}).get("backend")
    if flash_backend != "esptool":
        errs.append('flash.backend: 当前 %s — 需 "flash": {"backend": "esptool"}'
                    % _current(flash_backend, "openocd"))
    capture_backend = (cfg.get("capture") or {}).get("backend")
    if capture_backend != "uart":
        errs.append('capture.backend: 当前 %s — 需 "capture": {"backend": "uart"}'
                    % _current(capture_backend, "semihosting"))
    return errs


# ── 工程配置读写族 (F-029 T5) ──────────────────────────────────────
# 路径策略实测一致 (ws/.workbench/config.json)、读段/读改写体同源 → 上提规范版,
# runtime 侧退为薄壳 (段名/skill 参数、values=None 语义、返回形态按族保留 —
# serial 的 None no-op 是独立契约, 特征钉锁形)。
# 不上提: 环境级 TOOLKIT/config/<skill>.json 族 —— wb merge+守卫 vs ocd/ser 整写
# 系正当设计差异 (整写不读旧档, 无损坏丢键风险, 计划"补守卫"项经实测撤销),
# 见 test_runtime_contract.LocalConfigContractTests。

def project_config_file(workspace: str | None = None) -> Path:
    return workspace_root(workspace) / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME


def load_skill_section(config_file: str | Path, skill: str) -> dict:
    """读工程配置的某 skill 段 (只读消费方: 损坏静默当空, F-007)"""
    return load_json_file(config_file).get(skill, {})


def save_skill_section(config_file: str | Path, skill: str, values: dict) -> Path | None:
    """读改写 config.json 的 skill 段 (F-020 契约): 损坏拒绝写回返回 None。

    段值为 null 时按空段合并 (采纳 ocd 版 `or {}` 防御 —— wb/serial 旧版此处
    会 TypeError, 属崩溃路径增强, 正常写回形态不变)。

    F-222: 整段读-改-写纳入跨进程锁 (与 D3 gcc_build 写回 config.json
    **同一目标文件**的同类竞态)。两处若一个加锁一个不加, 反而互为丢更新
    的对手方 —— 加锁必须按**目标文件**覆盖全部写入方, 不是按脚本覆盖。
    `atomic_write` 只防撕裂不防丢更新, 故仍须锁。
    """
    file_path = Path(config_file)
    with file_lock(file_path):
        if file_path.exists():
            try:
                data = load_json_strict(file_path)
            except JSONCorruptError as e:
                print(f"Warning: 拒绝写回 config.json 以免清空其他配置段, "
                      f"请手工修复后重试: {e}", file=sys.stderr)
                return None
        else:
            data = {}
        data[skill] = {**(data.get(skill) or {}), **values}
        save_json_file(file_path, data)
    return file_path


# ── OpenOCD cfg 组装单一事实源 (WB-20260919-06, F-170 提前行权) ─────────────
# 硬编码沿革: F-108/M-3 grep 全量取证 "6 脚本各一对 interface/stlink.cfg +
# target/stm32f1x.cfg"; F-170 裁决暂缓 (唤起条件 = 第二 ARM 板型 / F-031
# Linux 真机窗口), 本单提前行权。7 处调用点 (capture_rtt/capture_semihosting/
# hardfault/openocd_runtime.swd_probe + _RESET_CFG_DEFAULT/physical_gate/
# verify.step_flash) 收敛到 resolve_openocd_cfg 一次调用, 默认行为逐字节
# 不变 (tests/test_openocd_cfg_param.py 跨点身份钉为证)。
# 放置论证: 消费方横跨 openocd 家族 (swd_probe/reset_target) 与 verify/
# capture/physical_gate 等编排侧 —— 跨族共享逻辑正是本模块职责; 且落
# runtime_common 使 Layer 1 (openocd_runtime) 可合法消费而无需改动
# test_layering_gates 的层表。工具库 cfg 路径经 __file__ 推导 (与
# openocd_runtime.default_config_path 同款), 不引 wb_common (互不渗透
# 边界保持)。

DEFAULT_OPENOCD_INTERFACE_CFG = "interface/stlink.cfg"
DEFAULT_OPENOCD_TARGET_CFG = "target/stm32f1x.cfg"
OPENOCD_CFG_KEYS = ("interface_cfg", "target_cfg")
TOOLKIT_OPENOCD_CFG_FILE = Path(__file__).resolve().parents[1] / "config" / "openocd.json"


class OpenocdCfgError(ValueError):
    """openocd cfg 键类型非法 (非字符串/空白串/含换行) — F-103 纪律:
    显式报错, 禁止静默回落默认。"""


def _validate_openocd_cfg_value(value, key):
    if not isinstance(value, str) or not value.strip() \
            or "\n" in value or "\r" in value:
        raise OpenocdCfgError(
            f"openocd cfg 键 {key} 非法: {value!r} "
            "(须为非空字符串且不含换行 — F-103 显式报错, 不静默回落)")
    return value


def resolve_openocd_cfg(interface=None, target=None, workspace=None, *,
                        project_config=None) -> dict:
    """OpenOCD interface/target cfg 组装单一事实源。

    优先级 (高→低): 显式参数 (CLI/调用方层) > 工程 .workbench/config.json
    openocd 段的 interface_cfg/target_cfg > 工具库 config/openocd.json
    同名键 > 内置默认 (= F-108/M-3 取证的现硬编码两串)。值只透传拼接
    不解释内容 (OpenOCD 自己报错); 任一层提供的值类型非法 → 抛
    OpenocdCfgError, 不静默回落默认。

    返回 {"interface", "target", "interface_source", "target_source"},
    source ∈ {"cli", "project", "toolkit", "default"}。

    workspace=None 时跳过工程层 (swd_probe 类纯预检场景); 调用方已持有
    工程配置时可经 project_config 注入避免重复读盘。

    与 openocd_runtime.resolve_openocd_params 的分界: 后者服务 openocd
    run/gdb/telnet 三个 CLI 的 board/interface/target 参数链
    (cli>工程>state), 本函数服务其余 7 处 cfg 组装点; 新键名
    (interface_cfg/target_cfg) 有意错开既有 interface/target 键, 避免
    两套语义互串。
    """
    project = project_config if project_config is not None else (
        load_skill_section(project_config_file(workspace), "openocd")
        if workspace else {})
    toolkit = load_json_file(TOOLKIT_OPENOCD_CFG_FILE)
    out: dict = {}
    for key, default in (("interface_cfg", DEFAULT_OPENOCD_INTERFACE_CFG),
                         ("target_cfg", DEFAULT_OPENOCD_TARGET_CFG)):
        short = key[:-4]
        for source, value in (("cli", interface if key == "interface_cfg"
                               else target),
                              ("project", project.get(key)),
                              ("toolkit", toolkit.get(key)),
                              ("default", default)):
            if value is None:
                continue
            out[short] = _validate_openocd_cfg_value(value, key)
            out[short + "_source"] = source
            break
    return out


def resolve_openocd_target(machine: dict, workspace=None, gcc_cfg=None) -> dict:
    """按工程 toolchain 选 openocd 可执行与 cfg 列表 (F-235)。

    arm(缺省) → machine.openocd_exe + resolve_openocd_cfg 的双文件 (行为不变)
    wch       → machine.wch_openocd_exe + [machine.wch_openocd_cfg] 单文件
    返回 {"exe", "cfg_list", "source"}; 缺键抛 OpenocdCfgError, 不静默回落。

    wch 分支的歧义纪律: CH32V307 工程若缺 wch_* 两键, 静默回落 arm 会拿
    ST-Link 的 openocd 去连 RISC-V 目标 —— 报错点名缺的 machine.json 键名,
    不猜。单文件 cfg (MounRiver 的 wch-riscv.cfg) 自带 adapter/transport
    声明, 调用方 (swd_probe) 因此不再追加 `transport select swd`。

    工程 toolchain 读法: gcc_cfg 未给时按 workspace 读 .workbench/config.json
    的 gcc 段。此处不走 wb_runtime.load_project_config —— 那是 Layer 1
    (test_layering_gates 禁令 1: 本模块不得 import 上游), 其函数体正是
    load_skill_section(project_config_file(workspace), skill), 结果等价。
    """
    if gcc_cfg is None and workspace:
        gcc_cfg = load_skill_section(project_config_file(str(workspace)), "gcc")
    kind = str((gcc_cfg or {}).get("toolchain") or "arm").strip().lower()
    if kind == "wch":
        exe = (machine.get("wch_openocd_exe") or "").strip()
        cfg = (machine.get("wch_openocd_cfg") or "").strip()
        if not exe:
            raise OpenocdCfgError(
                "machine.json 缺 wch_openocd_exe 键 (toolchain=wch 必需)")
        if not cfg:
            raise OpenocdCfgError(
                "machine.json 缺 wch_openocd_cfg 键 (toolchain=wch 必需)")
        return {"exe": exe, "cfg_list": [cfg], "source": "wch"}
    exe = (machine.get("openocd_exe") or "").strip()
    if not exe:
        raise OpenocdCfgError("machine.json 缺 openocd_exe 键")
    pair = resolve_openocd_cfg(workspace=workspace)
    return {"exe": exe,
            "cfg_list": [pair["interface"], pair["target"]],
            "source": "arm"}
