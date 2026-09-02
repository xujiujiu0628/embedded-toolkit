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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


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
