"""serial skill 私有运行时工具。"""

from __future__ import annotations

import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = "serial"
STATE_DIR_NAME = ".workbench"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE = "config.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_missing(value: Any) -> bool:
    return value is None or value == ""


class JSONCorruptError(ValueError):
    """JSON 文件损坏/非 UTF-8/顶层非对象 — 读改写场景必须显式处理 (F-017)。"""


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
    """保存 JSON 文件，自动创建目录；原子写 (.tmp + os.replace, F-016)"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(file_path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, file_path)


def load_local_config() -> dict:
    """加载 TOOLKIT/config/serial.json（环境级配置）"""
    return load_json_file(SKILL_DIR / "config" / f"{SKILL_NAME}.json")


def save_local_config(data: dict) -> None:
    """保存环境级配置到 TOOLKIT/config/serial.json"""
    save_json_file(SKILL_DIR / "config" / f"{SKILL_NAME}.json", data)


def workspace_root(workspace: str | None = None) -> Path:
    if not is_missing(workspace):
        return Path(str(workspace)).expanduser().resolve()
    return Path.cwd().resolve()


def load_project_config(workspace: str | None = None) -> dict:
    """从 workspace/.workbench/config.json 读取本 skill 的工程级配置"""
    proj_config = load_json_file(workspace_root(workspace) / STATE_DIR_NAME / PROJECT_CONFIG_FILE)
    return proj_config.get(SKILL_NAME, {})


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """写回工程级配置，只更新本 skill 的部分

    F-017: 配置损坏时拒绝写回 (旧实现把损坏当空文件, 写回后 config.json
    只剩 serial 段, 验证/构建等其他段无声蒸发)。"""
    if values is None:
        return
    proj_path = workspace_root(workspace) / STATE_DIR_NAME / PROJECT_CONFIG_FILE
    if proj_path.exists():
        try:
            proj_config = load_json_strict(proj_path)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 config.json 以免清空其他配置段, "
                  f"请手工修复后重试: {e}", file=sys.stderr)
            return
    else:
        proj_config = {}
    proj_config[SKILL_NAME] = {**proj_config.get(SKILL_NAME, {}), **values}
    save_json_file(proj_path, proj_config)


def load_workspace_state(workspace: str | None = None) -> dict:
    """从 workspace/.workbench/state.json 读取状态 (只读: 损坏静默当空)"""
    return load_json_file(workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME)


def load_workspace_state_for_update(workspace: str | None = None) -> dict:
    """读改写前的状态加载 (F-016): 损坏 → 隔离到 .corrupt 保留现场 → 按 {} 继续。

    state.json 是可再生缓存, 不像 config.json 那样拒绝写回; 旧实现
    "损坏当空读入→覆写"会让其他条目无声蒸发。"""
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


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    """保存状态"""
    ws = workspace_root(workspace)
    file_path = ws / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, _serialize_state_value(state, ws))
    return file_path


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    """更新状态条目 (F-016: 损坏隔离后重建, 不再当空文件覆写)"""
    ws = workspace_root(workspace)
    state = load_workspace_state_for_update(workspace)
    state[category] = _serialize_state_value({**record, "timestamp": record.get("timestamp") or now_iso()}, ws)
    file_path = save_workspace_state(state, workspace)
    return {
        "workspace": str(ws),
        "file": str(file_path),
        "updated_keys": [category],
        category: state[category],
    }


def normalize_path(value: str | None, base: str | Path | None = None) -> str:
    """路径规范化"""
    if is_missing(value):
        return ""
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve()) if path.is_absolute() else str(path)


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


def _first_resolved(mapping: dict, keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        value = mapping.get(key)
        if not is_missing(value):
            return value, key
    return None, None


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
    """统一参数解析，优先级: CLI > 环境级 > 工程级 > state > default"""
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
    """记录参数来源"""
    return {"name": name, "value": value, "source": source}


def make_result(
    success: bool = True,
    action: str = "",
    summary: str = "",
    details: dict | None = None,
    error: dict | None = None,
) -> dict:
    """统一结果格式"""
    result = {
        "status": "ok" if success else "error",
        "action": action,
        "summary": summary,
    }
    if details:
        result["details"] = details
    if error:
        result["error"] = error
    return result


def make_timing(start_time: float) -> dict:
    """执行时间记录"""
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


def output_json(data: dict, *, indent: int = 2) -> None:
    """输出 JSON 到 stdout"""
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=indent), flush=True)
