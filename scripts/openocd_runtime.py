"""openocd skill 私有运行时工具。"""

from __future__ import annotations

import json
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from shutil import which
from typing import Any

from runtime_common import (  # noqa: F401  (再导出: 保持 mod.X 调用面, F-029)
    JSONCorruptError, _first_resolved, build_artifacts, compact_dict,
    get_state_entry, hidden_subprocess_kwargs, is_missing, load_json_file,
    load_json_strict, load_skill_section, load_workspace_state,
    load_workspace_state_for_update, make_result, make_timing, normalize_path,
    now_iso, output_json, parameter_context, project_config_file,
    save_json_file, save_skill_section, save_workspace_state,
    update_state_entry, workspace_root,
)

# ocd 侧状态读写 = 共享层默认语义 (原样存, 无序列化钩子);
# 该分叉系实测真语义差 (wb==serial 才序列化), 见 test_runtime_contract
SKILL_NAME = "openocd"


def default_config_path(script_file: str) -> Path:
    # 阶段2: 脚本已折入工具库，环境级配置改读 TOOLKIT/config/<skill>.json
    return Path(script_file).resolve().parents[1] / "config" / f"{SKILL_NAME}.json"


def load_local_config(script_file: str = "") -> dict:
    """加载 skill/config.json（环境级配置）"""
    if script_file:
        config_path = default_config_path(script_file)
    else:
        # 尝试从调用栈推断路径
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get("__file__", "")
            if caller_file:
                config_path = default_config_path(caller_file)
            else:
                config_path = Path(__file__).resolve().parents[1] / "config" / f"{SKILL_NAME}.json"
        else:
            config_path = Path(__file__).resolve().parents[1] / "config" / f"{SKILL_NAME}.json"
    return load_json_file(config_path)


def save_local_config(data: dict, script_file: str = "") -> None:
    """保存环境级配置到 TOOLKIT/config/<skill>.json"""
    if script_file:
        config_path = default_config_path(script_file)
    else:
        config_path = Path(__file__).resolve().parents[1] / "config" / f"{SKILL_NAME}.json"
    save_json_file(config_path, data)


def load_project_config(workspace: str | None = None) -> dict:
    """从 workspace/.workbench/config.json 读取本 skill 的工程级配置
    参数: workspace - 工作区路径，None 时使用 cwd
    返回: 该 skill 对应的配置字典
    """
    return load_skill_section(project_config_file(workspace), SKILL_NAME)


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """写回工程级配置到 workspace/.workbench/config.json
    - 只更新本 skill 的配置部分，不覆盖其他 skill 的配置
    - 目录不存在时自动创建 .workbench/
    - openocd_runtime 中 skill_name 硬编码为 "openocd"
    - F-020: 配置损坏时拒绝写回 (体在 runtime_common.save_skill_section,
      F-029 T5 上提; 旧实现把损坏当空文件会让其他段无声蒸发)
    """
    if values is None:
        values = {}
    save_skill_section(project_config_file(workspace), SKILL_NAME, values)


def _machine_openocd_exe() -> str:
    """机器路径只允许存在于 machine.json (全局约束)。

    从 wb_common.load_machine() 读取; wb_common 不可用时返回 "" 走 PATH 检测。
    """
    try:
        from wb_common import load_machine
        return str(load_machine().get("openocd_exe") or "")
    except Exception:
        return ""


def resolve_param(
    name: str,
    cli_value: Any,
    *,
    config: dict | None = None,
    config_keys: list[str] | None = None,
    state_record: dict | None = None,
    state_keys: list[str] | None = None,
    required: bool = False,
    normalize_as_path: bool = False,
) -> tuple[Any, str]:
    """参数解析 — openocd 家族专属契约 (F-029 T5 裁决: 三份独立, 留本地不并)。

    优先级 cli>config>state>machine:openocd_exe>path>default("openocd");
    normalize 用 plain resolve (按 cwd 锚定, 与 wb 的 workspace 锚定不同);
    required=True 缺值即抛。wb/serial 同名函数各是独立契约,
    见 test_runtime_contract.ResolveParamContractTests。
    """
    if not is_missing(cli_value):
        value = cli_value
        source = "cli"
    else:
        value = None
        source = ""
        if config and config_keys:
            value, config_key = _first_resolved(config, config_keys)
            if not is_missing(value):
                source = f"config:{config_key}"
        if is_missing(value) and state_record and state_keys:
            value, state_key = _first_resolved(state_record, state_keys)
            if not is_missing(value):
                source = f"state:{state_key}"
        if is_missing(value) and name == "exe":
            value = _machine_openocd_exe()
            if not is_missing(value):
                source = "machine:openocd_exe"
        if is_missing(value) and name == "exe":
            discovered = which("openocd") or which("openocd.exe")
            if discovered:
                value = discovered
                source = "path"
            else:
                value = "openocd"
                source = "default"
    if normalize_as_path and not is_missing(value):
        value = normalize_path(str(value))
    if required and is_missing(value):
        raise ValueError(f"缺少必要参数: {name}")
    return value, source


def emit_stream_record(*, source: str, channel_type: str, text: str, as_json: bool, stream_type: str = "text", channel: int | None = None, extra: dict | None = None) -> None:
    if as_json:
        record = {
            "timestamp": now_iso(),
            "source": source,
            "channel_type": channel_type,
            "stream_type": stream_type,
            "text": text.rstrip("\r\n"),
        }
        if channel is not None:
            record["channel"] = channel
        if extra:
            record.update(compact_dict(extra))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    else:
        print(text, end="" if text.endswith(("\n", "\r")) else "\n", flush=True)


def swd_probe(openocd_exe: str, attempts: int = 3) -> tuple[bool, str]:
    """SWD 连通性探测 (秒级)。原 release.py 私有实现下沉共享 (F-041):
    发布门禁 G0.5 与 verify.py --doctor 共用同一命令与判据, 防两处口径漂移。

    判定走内容而非返回码 (对齐 hardfault.py 哲学): OpenOCD 关键行在 stderr,
    克隆适配器偶发非零退出; 连接失败形态是 "init mode failed / unable to connect"。
    attempts: 门禁默认 3 次重试 (ST-Link 释放竞态纪律); doctor 传 1 做单次快探。"""
    cmd = [openocd_exe,
           "-f", "interface/stlink.cfg",
           "-f", "target/stm32f1x.cfg",
           "-c", "transport select swd",
           "-c", "init", "-c", "targets", "-c", "shutdown"]
    last = ""
    for attempt in range(max(1, attempts)):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=20)
            last = ((r.stdout or "") + (r.stderr or ""))
            if "shutdown command invoked" in last \
                    and "init mode failed" not in last:
                return True, last[-200:]
        except subprocess.TimeoutExpired:
            last = f"attempt {attempt + 1}: SWD 探测超时"
        except Exception as e:
            last = str(e)
        if attempt < attempts - 1:
            time.sleep(1)
    return False, f"{last[-200:]}" if isinstance(last, str) else str(last)


# ── F-091: openocd 家族同源符号收敛（先钉后拆, 特征钉见 test_openocd_dedup） ──

def resolve_openocd_params(args, project_config: dict, state_lookup: dict) -> dict:
    """解析 OpenOCD 工程级参数，优先级: CLI > 工程配置 > state.json

    F-091: 原为 openocd_gdb/openocd_run/openocd_telnet 三份逐字节相同副本
    （openocd_itm 另有 +27 行的 tpiu/traceclk/pin_freq 扩展变体），按 F-029
    纪律收敛到本模块; 三个消费方 re-export 保持 `openocd_gdb.resolve_openocd_params`
    调用面不变（特征钉钉位）。
    """
    # board: CLI > 工程配置 > state
    board = args.board
    board_source = "cli"
    if is_missing(board):
        board = project_config.get("board")
        board_source = "project_config"
    if is_missing(board):
        board = state_lookup.get("board")
        board_source = "state"

    # interface: CLI > 工程配置 > state
    interface = args.interface
    interface_source = "cli"
    if is_missing(interface):
        interface = project_config.get("interface")
        interface_source = "project_config"
    if is_missing(interface):
        interface = state_lookup.get("interface")
        interface_source = "state"

    # target: CLI > 工程配置 > state
    target = args.target
    target_source = "cli"
    if is_missing(target):
        target = project_config.get("target")
        target_source = "project_config"
    if is_missing(target):
        target = state_lookup.get("target")
        target_source = "state"

    # adapter_speed: CLI > 工程配置 > state
    adapter_speed = args.adapter_speed
    adapter_speed_source = "cli"
    if is_missing(adapter_speed):
        adapter_speed = project_config.get("adapter_speed")
        adapter_speed_source = "project_config"
    if is_missing(adapter_speed):
        adapter_speed = state_lookup.get("adapter_speed")
        adapter_speed_source = "state"

    # transport: CLI > 工程配置 > state
    transport = args.transport
    transport_source = "cli"
    if is_missing(transport):
        transport = project_config.get("transport")
        transport_source = "project_config"
    if is_missing(transport):
        transport = state_lookup.get("transport")
        transport_source = "state"

    return {
        "board": board,
        "board_source": board_source,
        "interface": interface,
        "interface_source": interface_source,
        "target": target,
        "target_source": target_source,
        "adapter_speed": adapter_speed,
        "adapter_speed_source": adapter_speed_source,
        "transport": transport,
        "transport_source": transport_source,
    }


def state_lookup(state: dict) -> dict:
    """F-156 (P2-1): run/gdb/itm/telnet 四入口共用的 last_* 状态映射 —
    三份 _state_lookup 逐字拷贝 + telnet 内联第四份收编为超集单实现
    (gdb 的 gdb_port/telnet_port/elf_file/debug_file + run 的 flash_file
    并入; 各入口按需取键, 多余键无消费方即无害)。"""
    last_build = get_state_entry(state, "last_build")
    last_flash = get_state_entry(state, "last_flash")
    last_debug = get_state_entry(state, "last_debug")
    artifacts = last_build.get("artifacts", {})
    return {
        "board": last_debug.get("board") or last_flash.get("board"),
        "interface": last_debug.get("interface") or last_flash.get("interface"),
        "target": last_debug.get("target") or last_flash.get("target"),
        "search": last_debug.get("search"),
        "adapter_speed": last_debug.get("adapter_speed") or last_flash.get("adapter_speed"),
        "transport": last_debug.get("transport") or last_flash.get("transport"),
        "flash_file": last_build.get("flash_file") or artifacts.get("flash_file"),
        "gdb_port": last_debug.get("gdb_port"),
        "telnet_port": last_debug.get("telnet_port"),
        "elf_file": last_build.get("debug_file") or last_build.get("elf_file") or artifacts.get("debug_file"),
        "debug_file": last_build.get("debug_file") or artifacts.get("debug_file"),
    }


def start_openocd_server(cmd: list) -> subprocess.Popen:
    """启动 OpenOCD 进程（F-091 自 openocd_gdb/openocd_telnet 双副本收敛;
    F-123 收编 openocd_itm 第三份逐字节副本）"""
    popen_kwargs = hidden_subprocess_kwargs()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    if popen_kwargs.get("creationflags"):
        creationflags |= popen_kwargs["creationflags"]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        startupinfo=popen_kwargs.get("startupinfo"),
    )


# ============================================================
# F-123 (工单 P0-7): build_openocd_cmd / wait_server_ready / cleanup 收编
# ============================================================
#
# 缺陷 (gdb:95/telnet:61/itm:107 三份拷贝同病):
#   1. proc.stderr.readline() 在"进程存活但沉默"时无限阻塞, 外层
#      while-timeout 永远检查不到 → timeout 形同虚设;
#   2. ready 后无人再读 stderr (gdb server 常驻 / itm 主循环只读 trace
#      socket) → OpenOCD 刷日志填满管道缓冲 (~64KB) 后自身阻塞 → 全链死锁。
# 正解同 capture_rtt.py F 系列先例: daemon 线程持续排空 stderr 入有界队列,
# 主循环非阻塞取行, 超时由墙钟判定。有界队列满时丢最新行 (保排空活性,
# 长会话内存不增长)——F-166: 旧策略"丢最旧"在启动即爆发刷日志时把队头
# Listening 就绪行逐出, wait 永远等不到就绪 (真缺陷, 非测试抖动)。

_OPENOCD_CRITICAL_KEYWORDS = [
    "open failed",
    "init mode failed",
    "no device found",
    "cannot connect",
    "error connecting dp",
    "examination failed",
    "failed to read memory",
    "failed to write memory",
    "cannot read idr",
    "polling failed",
]

_ITM_CRITICAL_KEYWORDS = [
    "error:",
    "failed to start adapter's trace",
    "not supported by the device",
]

_PUMP_EOF = object()  # stderr EOF 哨兵


def _start_stderr_pump(proc: subprocess.Popen) -> "queue.Queue":
    q: queue.Queue = queue.Queue(maxsize=1000)

    def _pump():
        try:
            for line in proc.stderr:
                # F-166: 满队列丢"最新"而非"最旧"——就绪/Error 行全在流头部,
                # 丢最旧会在启动爆发 (首批 >maxsize 行) 时恰好逐出这些早期行;
                # 丢最新只截断洪水的后段, 排空活性与内存上界不变 (泵仍即时回收)。
                # 代价: 若就绪行本身出现在 >maxsize 行爆发之后, 丢最新将截断之
                # (旧丢最旧反可存活) — OpenOCD 实际启动形态就绪行居首, 判可接受。
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass  # F-166: 满队列丢当前行 (丢最新), 无重试
        except Exception:
            pass  # 进程提前死亡等: 排空职责优先于留痕
        finally:
            while True:
                try:
                    q.put_nowait(_PUMP_EOF)
                    break
                except queue.Full:
                    try:
                        q.get_nowait()  # 腾位保 EOF 送达 (收尾路径, 无早期行风险)
                    except queue.Empty:
                        pass

    threading.Thread(target=_pump, daemon=True).start()
    return q


def wait_server_ready(proc: subprocess.Popen, server_port: int, timeout: int = 15) -> tuple[bool, list[str]]:
    """等待 OpenOCD "Listening on port ..." 就绪 (gdb/telnet 共用口径)。

    F-123 单实现: 语义与 gdb/telnet 旧拷贝对齐 (Error: 行收集 / critical
    词表否决 / 进程退出即 False / ready 判定只看该行之前的输出), 但 readline
    阻塞换成墙钟真超时 + daemon 排空。"""
    started = time.time()
    errors: list[str] = []
    q = _start_stderr_pump(proc)

    while time.time() - started < timeout:
        if proc.poll() is not None:
            for line in _drain_queue(q):
                stripped = line.strip()
                if stripped and "Error:" in stripped:
                    errors.append(stripped)
            return False, errors
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            continue
        if item is _PUMP_EOF:
            continue
        stripped = item.strip()
        if "Error:" in stripped:
            errors.append(stripped)
        if f"Listening on port {server_port}" in stripped or "listening on" in stripped.lower():
            critical = [e for e in errors
                        if any(k in e.lower() for k in _OPENOCD_CRITICAL_KEYWORDS)]
            if critical:
                return False, critical
            return True, errors

    return False, errors


def wait_itm_ready(proc: subprocess.Popen, trace_port: int, timeout: int = 15) -> tuple[bool, list[str]]:
    """ITM 口径的就绪等待 (F-123 自 openocd_itm 收编, 行为契约保留):
    全行收集返回 / critical 词命中即时否决 / trace marker + 1s grace 确认。"""
    started = time.time()
    lines: list[str] = []
    ready = False
    ready_deadline = 0.0
    q = _start_stderr_pump(proc)

    while time.time() - started < timeout:
        if proc.poll() is not None:
            lines.extend(line.strip() for line in _drain_queue(q))
            return False, lines
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            if ready and time.time() >= ready_deadline:
                return True, lines
            continue
        if item is _PUMP_EOF:
            continue
        stripped = item.strip()
        lines.append(stripped)
        lowered = stripped.lower()
        if any(keyword in lowered for keyword in _ITM_CRITICAL_KEYWORDS):
            return False, lines
        if f"port {trace_port}" in lowered or "trace data" in lowered:
            ready = True
            ready_deadline = time.time() + 1.0

    return ready, lines


def _drain_queue(q: "queue.Queue", eof_wait: float = 2.0) -> list[str]:
    """排空到 EOF 哨兵 (进程已退/流已关的收尾路径)。

    不等哨兵直接 get_nowait 会与 pump 线程竞态丢行——旧版此处是阻塞的
    proc.stderr.read() (拿到全部剩余), 收编后必须保持同样完整度。"""
    out: list[str] = []
    deadline = time.time() + eof_wait
    while time.time() < deadline:
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            continue
        if item is _PUMP_EOF:
            return out
        out.append(item)
    return out


def build_openocd_cmd(
    exe: str,
    board: str = "",
    interface: str = "",
    target: str = "",
    search: str = "",
    adapter_speed: str = "",
    transport: str = "",
    gdb_port: int | None = 3333,
    telnet_port: int | None = 4444,
    extra_commands: list[str] | None = None,
) -> list[str]:
    """构建 OpenOCD 命令行 (F-123 自 gdb/telnet/run 三份拷贝收编)。

    gdb/telnet 口径: 带端口两参 (默认 3333/4444)。run 口径: gdb_port=
    telnet_port=None 关闭端口行、extra_commands 收尾——两条输出与旧本地
    副本逐元素一致。itm 的 tpiu/trace 扩展版是真分叉 (F-029 裁决), 不强并。"""
    cmd = [exe]
    if search:
        cmd.extend(["-s", search])
    if board:
        cmd.extend(["-f", board])
    else:
        if interface:
            cmd.extend(["-f", interface])
        if target:
            cmd.extend(["-f", target])
    if adapter_speed:
        cmd.extend(["-c", f"adapter speed {adapter_speed}"])
    if transport:
        cmd.extend(["-c", f"transport select {transport}"])
    if gdb_port is not None:
        cmd.extend(["-c", f"gdb_port {gdb_port}"])
    if telnet_port is not None:
        cmd.extend(["-c", f"telnet_port {telnet_port}"])
    for command in extra_commands or []:
        cmd.extend(["-c", command])
    return cmd


# ── F-129 (工单二 A-2): 判定后硬件自恢复 ─────────────────────────────────
# 借鉴 agentic-hil 的失败自恢复: 运行结束后板子状态不留给下一次运行——
# 超时/卡死场景留下的挂着断点或半初始化外设会污染下一次 verify。

_RESET_CFG_DEFAULT = ["interface/stlink.cfg", "target/stm32f1x.cfg"]  # verify.step_flash 同款


def reset_target(exe: str, cfg: list[str] | None = None, *,
                 timeout: int = 20) -> dict:
    """复位目标: openocd -f <cfg...> -c "init" -c "reset run" -c "shutdown"。

    verify.py 在 flash 实际发生过的判定结束后调用; cfg 缺省与 step_flash
    同一套 (stlink + stm32f1x)。exe 由调用方经既有 resolve 链取好传入,
    本函数不读 machine.json——保持纯函数, 测试无需环境桩。
    判据沿 swd_probe 内容口径 (克隆适配器偶发非零退出, 关键行才是真相):
    "shutdown command invoked" 在场且无 init 失败词。失败只返回 status
    留痕, 调用方绝不因复位失败改判 verdict。"""
    cmd = [exe]
    for c in (cfg or _RESET_CFG_DEFAULT):
        cmd.extend(["-f", c])
    cmd.extend(["-c", "init", "-c", "reset run", "-c", "shutdown"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        last = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"reset 超时 ({timeout}s)"}
    except OSError as e:
        return {"status": "error", "message": str(e)}
    if "shutdown command invoked" in last and "init mode failed" not in last:
        return {"status": "ok", "message": last[-200:]}
    return {"status": "error",
            "message": last[-200:] or f"openocd exit {r.returncode}"}


def cleanup(proc: subprocess.Popen | None) -> None:
    """终止 OpenOCD 进程 (F-123 自 gdb/itm cleanup + telnet cleanup_proc
    三份拷贝收编——旧三副本函数体逐字相同)。"""
    if proc and proc.poll() is None:
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()


cleanup_proc = cleanup  # telnet 入口的既有别名 (调用面/身份钉兼容)
