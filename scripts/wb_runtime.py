"""工作台共享运行时工具（原 keil_runtime.py，2026-08-28 Keil 退役时中性化更名）。

供 gcc_build / legacy keil 桥等所有构建后端复用：状态引擎（state.json）、
JSON 契约输出、工程/环境级配置读写。SKILL_NAME 仅作各函数的 skill 参数默认值，
不代表本模块从属于 Keil。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from shutil import which
from typing import Any

from wb_common import TOOLKIT_ROOT

from runtime_common import (  # noqa: F401  (再导出: 保持 mod.X 调用面, F-029)
    JSONCorruptError, _first_resolved, build_artifacts, compact_dict,
    get_state_entry, hidden_subprocess_kwargs, is_missing, load_json_file,
    load_json_strict, make_result, make_timing, normalize_path, now_iso,
    output_json, parameter_context, save_json_file, workspace_root,
)


STATE_DIR_NAME = ".workbench"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE_NAME = "config.json"

# Skill name for project config
SKILL_NAME = "keil"


def default_config_path(script_file: str | None = None, skill: str = SKILL_NAME) -> Path:
    # 环境级配置统一锚定 TOOLKIT/config/<skill>.json（不再按脚本位置反推层级，
    # 脚本移入任意子目录后路径依然正确；script_file 参数仅为旧调用方兼容，已不使用）
    return Path(TOOLKIT_ROOT) / "config" / f"{skill}.json"


def load_local_config(script_file: str | None = None, skill: str = SKILL_NAME) -> dict:
    """加载 TOOLKIT/config/<skill>.json（环境级配置）

    参数: skill - 配置段名（如 "keil"）；script_file 兼容旧调用位，已不使用。
    """
    config_path = default_config_path(skill=skill)
    return load_json_file(config_path)


def save_local_config(data: dict, script_file: str | None = None, skill: str = SKILL_NAME) -> Path | None:
    """保存环境级配置到 TOOLKIT/config/<skill>.json

    F-021: 配置损坏时**拒绝写回**返回 None — 本函数是读改写族,
    把损坏当空文件会让一次写回清空其余键 (与 save_project_config/F-020 同契约)
    """
    config_path = default_config_path(skill=skill)
    if config_path.exists():
        try:
            existing = load_json_strict(config_path)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 {config_path.name} 以免清空其余键, "
                  f"请手工修复后重试: {e}", file=sys.stderr)
            return None
    else:
        existing = {}
    existing.update(data)
    save_json_file(config_path, existing)
    return config_path


def load_project_config(workspace: str | None = None, skill: str = SKILL_NAME) -> dict:
    """从 workspace/.workbench/config.json 读取指定 skill 段的工程级配置

    参数: workspace - 工作区路径，None 时使用 cwd；skill - 顶层段名（如 "keil"/"gcc"）
    返回: 该 skill 对应的配置字典（如 config["keil"] 或 config["gcc"]）
    """
    ws = workspace_root(workspace)
    config_file = ws / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    data = load_json_file(config_file)
    return data.get(skill, {})


def save_project_config(workspace: str | None = None, values: dict | None = None, skill: str = SKILL_NAME) -> Path | None:
    """写回工程级配置到 workspace/.workbench/config.json 的 <skill> 段

    - 只更新本 skill 的配置部分，不覆盖其他 skill 的配置
    - 目录不存在时自动创建 .workbench/
    - F-020: 配置损坏时**拒绝写回**返回 None — config.json 是验证契约,
      不能被构建行为清空 (旧实现把损坏当空文件, 写回后只剩本 skill 段)
    """
    if values is None:
        values = {}
    ws = workspace_root(workspace)
    config_file = ws / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    if config_file.exists():
        try:
            data = load_json_strict(config_file)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 config.json 以免清空其他配置段, "
                  f"请手工修复后重试: {e}", file=sys.stderr)
            return None
    else:
        data = {}
    data[skill] = {**(data.get(skill, {})), **values}
    save_json_file(config_file, data)
    return config_file


def normalize_path_with_base(value: str | None, base: str | Path | None = None) -> str:
    if is_missing(value):
        return ""
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve())


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


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    ws = workspace_root(workspace)
    file_path = ws / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, _serialize_state_value(state, ws))
    return file_path


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


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
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


def _machine_uv4_exe() -> str:
    """机器路径只允许存在于 machine.json (全局约束)。

    从 wb_common.load_machine() 读取; wb_common 不可用时返回 "" 走 auto-detect。
    """
    try:
        from wb_common import load_machine
        return str(load_machine().get("uv4_exe") or "")
    except Exception:
        return ""


def _auto_detect_uv4() -> str:
    candidates = [
        which("UV4.exe"),
        which("UV4"),
        r"C:\Keil_v5\UV4\UV4.exe",
        r"C:\Keil_v5\ARM\UV4\UV4.exe",
    ]
    keil_root = os.environ.get("KEIL_ROOT", "")
    if keil_root:
        candidates.append(str(Path(keil_root) / "UV4" / "UV4.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
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
    workspace: str | None = None,
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
        if is_missing(value) and name == "uv4":
            value = _machine_uv4_exe()
            if not is_missing(value):
                source = "machine:uv4_exe"
        if is_missing(value) and name == "uv4":
            value = _auto_detect_uv4()
            if not is_missing(value):
                source = "auto:uv4"
    if normalize_as_path and not is_missing(value):
        value = normalize_path_with_base(str(value), workspace_root(workspace))
    if required and is_missing(value):
        raise ValueError(f"缺少必要参数: {name}")
    return value, source
