r"""F-245: feedback_db 的相似检索 / 校准导出 / MCP build_server 补测。

## 覆盖对象

- `feedback_db.find_similar` / `export_calibration`（88% →）；
- `mcp_server.build_server` 与 `main` 的 SDK 成功路径（85% →）：用注入的
  假 `mcp` 包驱动，不安装真实 SDK。

## 夹具

临时工程 + sys.modules 注入假 MCP 模块（用完还原）。
"""
import json
import os
import sys
import tempfile
import types
import unittest
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import feedback_db  # noqa: E402
import mcp_server  # noqa: E402


class FindSimilarTests(unittest.TestCase):
    def test_similar_sorted_and_calibration_exported(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            old = os.getcwd()
            os.chdir(ws)
            try:
                feedback_db.log_event({"pipeline": "build_fix", "error_code": "E42",
                                       "outcome": "still_broken"})
                feedback_db.log_event({"pipeline": "build_fix", "error_code": "E42",
                                       "outcome": "fixed"})
                similar = feedback_db.find_similar("E42")
                cal = feedback_db.export_calibration()
            finally:
                os.chdir(old)
        self.assertEqual([s["outcome"] for s in similar], ["fixed", "still_broken"])
        self.assertEqual(cal["build_fix"]["E42"]["attempts"], 2)


class _FakeServer:
    def __init__(self, name):
        self.name = name
        self.handlers = {}

    def list_tools(self):
        def deco(func):
            self.handlers["list"] = func
            return func
        return deco

    def call_tool(self):
        def deco(func):
            self.handlers["call"] = func
            return func
        return deco

    def create_initialization_options(self):
        return {}

    async def run(self, _read, _write, _opts):
        self.ran = True


class _FakeStdio:
    async def __aenter__(self):
        return (None, None)

    async def __aexit__(self, *_x):
        return False


def _inject_mcp(server_cls=_FakeServer):
    mcp = types.ModuleType("mcp")
    server_mod = types.ModuleType("mcp.server")
    server_mod.Server = server_cls
    stdio_mod = types.ModuleType("mcp.server.stdio")
    stdio_mod.stdio_server = lambda: _FakeStdio()
    types_mod = types.ModuleType("mcp.types")
    types_mod.TextContent = lambda **kw: types.SimpleNamespace(**kw)
    types_mod.Tool = lambda **kw: types.SimpleNamespace(**kw)
    server_mod.types = types_mod
    mcp.server = server_mod
    mcp.types = types_mod
    saved = {k: sys.modules.get(k) for k in
             ("mcp", "mcp.server", "mcp.server.stdio", "mcp.types")}
    sys.modules.update({"mcp": mcp, "mcp.server": server_mod,
                        "mcp.server.stdio": stdio_mod, "mcp.types": types_mod})

    def restore():
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return restore


class BuildServerTests(unittest.TestCase):
    def test_list_and_call_tool_wrappers(self):
        restore = _inject_mcp()
        try:
            app = mcp_server.build_server()
        finally:
            restore()
        tools = asyncio.run(app.handlers["list"]())
        self.assertEqual(len(tools), len(mcp_server._TOOL_REGISTRY))
        self.assertIn("name", vars(tools[0]))
        # 未知工具 → 包装层转错误信封，不上抛
        result = asyncio.run(app.handlers["call"]("nope", {}))
        payload = json.loads(result[0].text)
        self.assertFalse(payload["ok"])

    def test_main_runs_stdio_server(self):
        restore = _inject_mcp()
        try:
            rc = mcp_server.main()
        finally:
            restore()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
