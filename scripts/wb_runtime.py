"""工作台共享运行时工具。

历史: 2026-08-28 keil_runtime.py 中性化更名为 wb_runtime.py（Keil 退役入
scripts/legacy/keil/，本模块从构建后端特异层上提为 GCC/OCD/serial 三族共享层）；
2026-09-05 Keil 退役区完整拆 archive（F-067b）后进一步去 keil 专属死代码（uv4
路径常量与 auto-detect）——本模块不再含 keil 工具链特异逻辑。

供 gcc_build 等 GCC 主链工具复用：状态引擎（state.json）、JSON 契约输出、工程/
环境级配置读写。SKILL_NAME 仅作各函数的 skill 参数默认值，与"工作台"（wb）命名
对齐。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
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
# 2026-09-05: 改 "wb" (F-067a, 与中性化命名对齐; 旧 "keil" 为历史延续,
# 当前所有调用方均显式传 skill="gcc"/"openocd"/"serial", 默认值仅在
# 显式缺省时回退, 实际从未触发)
SKILL_NAME = "wb"


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

    优先级 cli>config>state; normalize 按 workspace 锚定
    (normalize_path_with_base); required=True 缺值即抛 ValueError。
    ocd/serial 同名函数各是独立契约 (层级/源标签/锚定/异常策略均不同形),
    非漏改, 勿'统一' — 见 test_runtime_contract.ResolveParamContractTests。

    2026-09-05 (F-067a): 删 keil 专属 uv4 特判 (machine:uv4_exe / auto:uv4 两层
    fallback)。Keil 退役区拆 archive 后本模块不再服务 keil 桥, uv4 路径解析
    失去意义; ocd/serial 的"name=='exe'/'file' 特判 + 兜底值"机制各自在
    所属 runtime 内, 不在 wb 这层。
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
    if normalize_as_path and not is_missing(value):
        value = normalize_path_with_base(str(value), workspace_root(workspace))
    if required and is_missing(value):
        raise ValueError(f"缺少必要参数: {name}")
    return value, source
