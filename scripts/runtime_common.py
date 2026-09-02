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
from datetime import datetime
from pathlib import Path
from typing import Any

# 状态文件锚 (三 runtime 实测取值一致; 随状态读写族上提, F-029 T4)
STATE_DIR_NAME = ".workbench"
STATE_FILE_NAME = "state.json"


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
    新文件, 不再有半截 JSON (F-019: 撕裂读曾把下游引入"损坏→清空"链)"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.{os.getpid()}.tmp")  # F-023: pid 防双进程互顶
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    os.replace(tmp_path, file_path)


def output_json(data: dict, *, indent: int = 2) -> None:
    """输出 JSON 到 stdout"""
    sys.stdout.reconfigure(encoding="utf-8")
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
