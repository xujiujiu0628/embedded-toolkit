"""openocd skill 私有运行时工具。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from shutil import which
from typing import Any

from runtime_common import (  # noqa: F401  (再导出: 保持 mod.X 调用面, F-029)
    JSONCorruptError, _first_resolved, build_artifacts, compact_dict,
    get_state_entry, hidden_subprocess_kwargs, is_missing, load_json_file,
    load_json_strict, make_result, make_timing, normalize_path, now_iso,
    output_json, parameter_context, save_json_file, workspace_root,
)

STATE_DIR_NAME = ".workbench"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE_NAME = "config.json"
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
    ws_root = workspace_root(workspace)
    project_config_path = ws_root / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    full_config = load_json_file(project_config_path)
    return full_config.get(SKILL_NAME, {})


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """写回工程级配置到 workspace/.workbench/config.json
    - 只更新本 skill 的配置部分，不覆盖其他 skill 的配置
    - 目录不存在时自动创建 .workbench/
    - openocd_runtime 中 skill_name 硬编码为 "openocd"
    - F-020: 配置损坏时拒绝写回 (旧实现把损坏当空文件, 写回后 config.json
      只剩本次写入的段, 其余配置段无声蒸发)
    """
    if values is None:
        values = {}
    ws_root = workspace_root(workspace)
    project_config_path = ws_root / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME

    if project_config_path.exists():
        try:
            full_config = load_json_strict(project_config_path)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 config.json 以免清空其他配置段, "
                  f"请手工修复后重试: {e}", file=sys.stderr)
            return
    else:
        full_config = {}

    # 只更新本 skill 的配置部分
    full_config[SKILL_NAME] = {**(full_config.get(SKILL_NAME) or {}), **values}

    save_json_file(project_config_path, full_config)


def load_workspace_state(workspace: str | None = None) -> dict:
    return load_json_file(workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME)


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    file_path = workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, state)
    return file_path


def load_workspace_state_for_update(workspace: str | None = None) -> dict:
    """读改写前的状态加载 (F-019): 损坏 → 隔离到 .corrupt 保留现场 → 按 {} 继续。

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


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    state = load_workspace_state_for_update(workspace)
    state[category] = {**record, "timestamp": record.get("timestamp") or now_iso()}
    file_path = save_workspace_state(state, workspace)
    return {
        "workspace": str(workspace_root(workspace)),
        "file": str(file_path),
        "updated_keys": [category],
        category: state[category],
    }


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
