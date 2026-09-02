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
    JSONCorruptError, _first_resolved, _serialize_state_value, build_artifacts,
    compact_dict, get_state_entry, hidden_subprocess_kwargs, is_missing,
    load_json_file, load_json_strict, load_skill_section, load_workspace_state,
    load_workspace_state_for_update, make_result, make_timing, normalize_path,
    now_iso, output_json, parameter_context, project_config_file,
    save_json_file, save_skill_section, workspace_root,
)
from runtime_common import save_workspace_state as _common_save_workspace_state  # F-029 T4: 序列化钩子绑定
from runtime_common import update_state_entry as _common_update_state_entry  # F-029 T4: 序列化钩子绑定


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
    return load_skill_section(project_config_file(workspace), skill)


def save_project_config(workspace: str | None = None, values: dict | None = None, skill: str = SKILL_NAME) -> Path | None:
    """写回工程级配置到 workspace/.workbench/config.json 的 <skill> 段

    - 只更新本 skill 的配置部分，不覆盖其他 skill 的配置
    - 目录不存在时自动创建 .workbench/
    - F-020: 配置损坏时**拒绝写回**返回 None — config.json 是验证契约,
      不能被构建行为清空 (旧实现把损坏当空文件, 写回后只剩本 skill 段)
    - F-029 T5: 读改写体在 runtime_common.save_skill_section, 本函数为薄壳
    """
    if values is None:
        values = {}
    return save_skill_section(project_config_file(workspace), skill, values)


def normalize_path_with_base(value: str | None, base: str | Path | None = None) -> str:
    if is_missing(value):
        return ""
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve())


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    """保存状态 (F-029 T4 薄壳): 序列化钩子=绝对路径→workspace 相对 POSIX,
    此系 wb 原生契约 (ocd 原样存为真分叉, 特征钉锁形, 勿'统一')。"""
    return _common_save_workspace_state(state, workspace, serialize=_serialize_state_value)


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    """更新状态条目 (F-029 T4 薄壳): 共享层骨架 + wb 序列化钩子, 行为逐字节不变。"""
    return _common_update_state_entry(category, record, workspace,
                                      serialize=_serialize_state_value)


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
    """参数解析 — wb 构建后端专属契约 (F-029 T5 裁决: 三份独立, 留本地不并)。

    优先级 cli>config>state>machine:uv4_exe>auto:uv4; normalize 按 workspace
    锚定 (normalize_path_with_base); required=True 缺值即抛 ValueError。
    ocd/serial 同名函数各是独立契约 (层级/源标签/锚定/异常策略均不同形),
    非漏改, 勿'统一' — 见 test_runtime_contract.ResolveParamContractTests。
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
