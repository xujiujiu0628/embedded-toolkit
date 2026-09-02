"""openocd skill 私有运行时工具。"""

from __future__ import annotations

import json
import subprocess
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
