"""工作台工具库共享路径解析。

TOOLKIT_ROOT 从本文件位置推导（scripts/ 的父目录）。
工程根发现: 从给定目录向上逐级找 .workbench/config.json
（兜底 .embeddedskills/config.json, 迁移过渡期兼容）。
"""
import json
import os
import sys

TOOLKIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FALLBACK_WARNED = False  # machine.example.json 回退警告只发一次

_PROJECT_MARKERS = (".workbench/config.json", ".embeddedskills/config.json")


def find_project_root(start):
    """从 start 向上逐级查找工程根, 找不到返回 None。"""
    d = os.path.abspath(start)
    while True:
        for marker in _PROJECT_MARKERS:
            if os.path.isfile(os.path.join(d, marker)):
                return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_machine():
    """读 toolkit/machine.json (本机工具链绝对路径, 本机文件不入库)。

    machine.json 缺失时回退到入库模板 machine.example.json 并一次性警告——
    新克隆上测试与离线工具因此直接可跑; 占位路径一旦被真机构建/烧录用到,
    会以自解释的 FileNotFoundError 报错 (显式指引优于静默防御, F-011)。
    两档皆缺 → FileNotFoundError 且信息含可行动指引。"""
    global _FALLBACK_WARNED
    path = os.path.join(TOOLKIT_ROOT, "machine.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    example = os.path.join(TOOLKIT_ROOT, "machine.example.json")
    if os.path.isfile(example):
        if not _FALLBACK_WARNED:
            _FALLBACK_WARNED = True
            print("[machine] machine.json 缺失, 暂用 machine.example.json 的占位路径"
                  " (仅够测试/离线工具)——真机构建/烧录/采集前请复制为 machine.json"
                  " 并填入本机绝对路径", file=sys.stderr)
        with open(example, encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(
        f"未找到 machine.json: {path}——请复制 machine.example.json 为"
        " machine.json 并填入本机工具链绝对路径 (machine.json 为本机文件, 不入库)")


def toolkit_version():
    with open(os.path.join(TOOLKIT_ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def _ver_tuple(s):
    return tuple(int(x) for x in s.split(".")[:2])


def version_ok(actual, minimum):
    return _ver_tuple(actual) >= _ver_tuple(minimum)
