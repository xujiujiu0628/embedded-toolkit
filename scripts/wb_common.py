"""工作台工具库共享路径解析。

TOOLKIT_ROOT 从本文件位置推导（scripts/ 的父目录）。
工程根发现: 从给定目录向上逐级找 .workbench/config.json
（兜底 .embeddedskills/config.json, 迁移过渡期兼容）。
"""
import json
import os

TOOLKIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    """读 toolkit/machine.json (本机工具链绝对路径)。"""
    with open(os.path.join(TOOLKIT_ROOT, "machine.json"), encoding="utf-8") as f:
        return json.load(f)


def toolkit_version():
    with open(os.path.join(TOOLKIT_ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def _ver_tuple(s):
    return tuple(int(x) for x in s.split(".")[:2])


def version_ok(actual, minimum):
    return _ver_tuple(actual) >= _ver_tuple(minimum)
