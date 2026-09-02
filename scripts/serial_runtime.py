"""serial skill 私有运行时工具。"""

from __future__ import annotations

import json
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime_common import (  # noqa: F401  (再导出: 保持 mod.X 调用面, F-029)
    # normalize_path 不并入: serial 自带独立契约 (可带 base、相对输入不 resolve), 见 F-029 T3 裁决
    JSONCorruptError, _first_resolved, _serialize_state_value, is_missing,
    load_json_file, load_json_strict, load_skill_section, load_workspace_state,
    load_workspace_state_for_update, now_iso, output_json,
    project_config_file, save_json_file, save_skill_section,
    workspace_root,
)
from runtime_common import make_result as _common_make_result  # F-029 T3: serial 适配器转调目标
from runtime_common import save_workspace_state as _common_save_workspace_state  # F-029 T4: 序列化钩子绑定
from runtime_common import update_state_entry as _common_update_state_entry  # F-029 T4: 序列化钩子绑定

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = "serial"


def load_local_config() -> dict:
    """加载 TOOLKIT/config/serial.json（环境级配置）"""
    return load_json_file(SKILL_DIR / "config" / f"{SKILL_NAME}.json")


def save_local_config(data: dict) -> None:
    """保存环境级配置到 TOOLKIT/config/serial.json"""
    save_json_file(SKILL_DIR / "config" / f"{SKILL_NAME}.json", data)


def load_project_config(workspace: str | None = None) -> dict:
    """从 workspace/.workbench/config.json 读取本 skill 的工程级配置"""
    return load_skill_section(project_config_file(workspace), SKILL_NAME)


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """写回工程级配置，只更新本 skill 的部分 (F-029 T5 薄壳)

    F-020: 配置损坏时拒绝写回 — 体在 runtime_common.save_skill_section。
    values=None 即 no-op 是 serial 家族独立契约 (wb/ocd 会建空段,
    test_runtime_contract.SaveProjectConfigNoneValuesTests 锁形, 勿'对齐')。"""
    if values is None:
        return
    save_skill_section(project_config_file(workspace), SKILL_NAME, values)


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    """保存状态 (F-029 T4 薄壳): 序列化钩子同 wb (绝对路径→workspace 相对 POSIX)。"""
    return _common_save_workspace_state(state, workspace, serialize=_serialize_state_value)


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    """更新状态条目 (F-029 T4 薄壳): 共享层骨架 + 序列化钩子, 行为逐字节不变
    (原 F-019 隔离重建语义在骨架内)。"""
    return _common_update_state_entry(category, record, workspace,
                                      serialize=_serialize_state_value)


def normalize_path(value: str | None, base: str | Path | None = None) -> str:
    """路径规范化 — serial 独立契约 (F-029 T3 裁决): 相对输入不 resolve、可带
    base; 与 runtime_common.normalize_path (恒 resolve 绝对) 语义不等价,
    非超集非漏改, 勿'统一' (serial_log.py 等消费面依赖此形态)。"""
    if is_missing(value):
        return ""
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve()) if path.is_absolute() else str(path)


def resolve_param(
    name: str,
    cli_value: Any = None,
    local_config: dict | None = None,
    local_keys: list[str] | None = None,
    project_config: dict | None = None,
    project_keys: list[str] | None = None,
    state: dict | None = None,
    state_keys: list[str] | None = None,
    default: Any = None,
) -> tuple[Any, str]:
    """统一参数解析，优先级: CLI > 环境级 > 工程级 > state > default

    serial 家族专属契约 (F-029 T5 裁决: 三份独立, 留本地不并): 位置参形态、
    local:/project:/state:/default 源标签直接进工具输出; 无 normalize、
    无 required 异常 (全 miss 返回 (None, ""))。wb/ocd 同名函数各是独立契约,
    见 test_runtime_contract.ResolveParamContractTests。"""
    if not is_missing(cli_value):
        return cli_value, "cli"

    if local_config and local_keys:
        value, key = _first_resolved(local_config, local_keys)
        if not is_missing(value):
            return value, f"local:{key}"

    if project_config and project_keys:
        value, key = _first_resolved(project_config, project_keys)
        if not is_missing(value):
            return value, f"project:{key}"

    if state and state_keys:
        value, key = _first_resolved(state, state_keys)
        if not is_missing(value):
            return value, f"state:{key}"

    if not is_missing(default):
        return default, "default"

    return None, ""


def parameter_context(name: str, value: Any, source: str) -> dict:
    """serial 家族独立契约 (F-029 裁决): 与 wb/ocd 同名异物 (入参/返回均
    不同形 — 本版是 name/value/source 三元组, 规范版是 provider context dict),
    非漏改, 勿'统一'。记录参数来源。"""
    return {"name": name, "value": value, "source": source}


def make_result(
    success: bool = True,
    action: str = "",
    summary: str = "",
    details: dict | None = None,
    error: dict | None = None,
) -> dict:
    """serial 家族入口签名 (F-029): success:bool 位置参冻结不变, 输出 status 族
    转调 runtime_common 规范实现。差异点按特征钉保留: 空 details **省略键**
    (规范版恒带), details/error **原样透传** (规范版走 compact_dict) —
    六个 serial 工具消费面字节兼容, 见 test_runtime_contract。"""
    result = _common_make_result(status="ok" if success else "error",
                                 action=action, summary=summary)
    result.pop("details")
    if details:
        result["details"] = details
    if error:
        result["error"] = error
    return result


def make_timing(start_time: float) -> dict:
    """serial 家族独立契约 (F-029 裁决): 与 wb/ocd 同名异物 — 本版收 epoch
    float 现算耗时, 规范版收 (started_at, elapsed_ms) 做格式化, 非漏改,
    勿'统一' (serial_monitor.py 消费面依赖本签名)。执行时间记录。"""
    elapsed = datetime.now().timestamp() - start_time
    return {
        "started_at": datetime.fromtimestamp(start_time).astimezone().isoformat(timespec="seconds"),
        "finished_at": now_iso(),
        "elapsed_ms": int(elapsed * 1000),
    }


def scan_serial_ports(filter_keyword: str | None = None) -> tuple[list[dict], str | None]:
    """扫描系统串口，返回 (ports, error)"""
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        return [], "pyserial 未安装，请执行 pip install pyserial"

    # 加载 VID/PID -> 芯片名称映射
    chip_map = {}
    try:
        common_devices_path = SKILL_DIR / "data" / "common_devices.json"
        data = json.loads(common_devices_path.read_text(encoding="utf-8"))
        for entry in data.get("usb_serial_chips", []):
            key = (entry["vid"].upper(), entry["pid"].upper())
            chip_map[key] = entry["name"]
    except Exception:
        pass

    ports = []
    for p in sorted(comports(), key=lambda x: x.device):
        vid = f"{p.vid:04X}" if p.vid else ""
        pid = f"{p.pid:04X}" if p.pid else ""
        chip_name = chip_map.get((vid, pid), "")

        info = {
            "port": p.device,
            "description": p.description or "",
            "vid": vid,
            "pid": pid,
            "chip": chip_name,
            "serial_number": p.serial_number or "",
            "location": p.location or "",
        }

        if filter_keyword:
            text = " ".join(str(v) for v in info.values()).lower()
            if filter_keyword.lower() not in text:
                continue

        ports.append(info)

    return ports, None


def get_serial_config(
    cli_port: str | None = None,
    cli_baudrate: int | None = None,
    cli_bytesize: int | None = None,
    cli_parity: str | None = None,
    cli_stopbits: int | None = None,
    cli_encoding: str | None = None,
    cli_timeout: float | None = None,
    workspace: str | None = None,
) -> tuple[dict, dict]:
    """
    获取串口配置，按优先级解析参数。
    返回 (config_dict, sources_dict)
    """
    local_cfg = load_local_config()
    proj_cfg = load_project_config(workspace)
    state = load_workspace_state(workspace)

    sources = {}

    # 解析各个参数
    port, src = resolve_param(
        "port", cli_port,
        project_config=proj_cfg, project_keys=["port"],
        state=state, state_keys=["last_serial_port"],
    )
    sources["port"] = src or "unknown"

    baudrate, src = resolve_param(
        "baudrate", cli_baudrate,
        project_config=proj_cfg, project_keys=["baudrate"],
        state=state, state_keys=["last_baudrate"],
        default=115200,
    )
    sources["baudrate"] = src or "default"

    bytesize, src = resolve_param(
        "bytesize", cli_bytesize,
        project_config=proj_cfg, project_keys=["bytesize"],
        default=8,
    )
    sources["bytesize"] = src or "default"

    parity, src = resolve_param(
        "parity", cli_parity,
        project_config=proj_cfg, project_keys=["parity"],
        default="none",
    )
    sources["parity"] = src or "default"

    stopbits, src = resolve_param(
        "stopbits", cli_stopbits,
        project_config=proj_cfg, project_keys=["stopbits"],
        default=1,
    )
    sources["stopbits"] = src or "default"

    encoding, src = resolve_param(
        "encoding", cli_encoding,
        project_config=proj_cfg, project_keys=["encoding"],
        default="utf-8",
    )
    sources["encoding"] = src or "default"

    timeout, src = resolve_param(
        "timeout_sec", cli_timeout,
        project_config=proj_cfg, project_keys=["timeout_sec"],
        default=1.0,
    )
    sources["timeout_sec"] = src or "default"

    # 如果没有指定 port，尝试扫描
    if is_missing(port):
        ports, err = scan_serial_ports()
        if err:
            return None, {"error": err}
        if len(ports) == 1:
            # 唯一候选，自动写入配置
            port = ports[0]["port"]
            sources["port"] = "auto_scan"
            save_project_config(workspace, {"port": port})
        elif len(ports) > 1:
            return None, {
                "error": "找到多个串口，请指定一个",
                "candidates": ports,
                "need_selection": True,
            }
        else:
            return None, {"error": "未找到可用串口"}

    log_dir, src = resolve_param(
        "log_dir", None,
        project_config=proj_cfg, project_keys=["log_dir"],
        default=".workbench/logs/serial",
    )
    sources["log_dir"] = src or "default"

    config = {
        "port": port,
        "baudrate": baudrate,
        "bytesize": bytesize,
        "parity": parity,
        "stopbits": stopbits,
        "encoding": encoding,
        "timeout_sec": timeout,
        "log_dir": log_dir,
    }

    return config, sources


def is_mux_alive(mux_info: dict) -> bool:
    """检查 mux 进程是否存活"""
    for pid_key in ("tcp_pid", "pty_pid"):
        pid = mux_info.get(pid_key, 0)
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
    return True


def get_mux_info(workspace: str | None = None) -> dict | None:
    """获取运行中的 mux 连接信息，未运行返回 None"""
    state = load_workspace_state(workspace)
    mux_info = state.get("serial_mux")
    if not mux_info:
        return None
    if not is_mux_alive(mux_info):
        state.pop("serial_mux", None)
        save_workspace_state(state, workspace)
        return None
    return mux_info


def _normalize_serial_port(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if os.name == "nt":
        return os.path.normcase(text)
    if text.startswith("/"):
        return os.path.realpath(text)
    return text


def config_matches_mux(config: dict, mux_info: dict) -> bool:
    """确认当前串口配置与运行中的 mux 指向同一串口。"""
    if _normalize_serial_port(config.get("port")) != _normalize_serial_port(mux_info.get("real_port")):
        return False

    checks = (
        ("baudrate", 115200),
        ("bytesize", 8),
        ("parity", "none"),
        ("stopbits", 1),
    )
    for key, default in checks:
        if str(config.get(key, default)).lower() != str(mux_info.get(key, default)).lower():
            return False
    return True


def get_matching_mux_info(config: dict, workspace: str | None = None) -> dict | None:
    """仅在 mux 与本次解析出的串口配置一致时返回 mux 信息。"""
    mux_info = get_mux_info(workspace)
    if mux_info and config_matches_mux(config, mux_info):
        return mux_info
    return None


def open_serial_port(config: dict, use_mux: bool = True):
    """根据配置打开串口连接。

    当 mux 运行且串口配置匹配时自动通过 socket:// 连接 TCP 端口，
    从而实现与 minicom 同时访问串口。
    use_mux=False 时跳过 mux 检测，直接打开真实串口。
    """
    import serial

    if use_mux:
        mux = get_matching_mux_info(config)
        if mux:
            url = f"socket://127.0.0.1:{mux['tcp_port']}"
            ser = serial.serial_for_url(url)
            ser.timeout = config.get("timeout_sec", 1.0)
            setattr(ser, "_serial_skill_using_mux", True)
            return ser

    PARITY_MAP = {"none": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}
    parity = PARITY_MAP.get(config.get("parity", "none"), "N")

    return serial.Serial(
        port=config["port"],
        baudrate=config["baudrate"],
        bytesize=config["bytesize"],
        parity=parity,
        stopbits=config["stopbits"],
        timeout=config["timeout_sec"],
    )
