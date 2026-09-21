r"""F-182 (WB-20260921-03) MCP 注册表形态守卫 —— 只报警, 不修本体。

本文件把 `scripts/mcp_server.py` 注册表的两处**隐式约定**钉成显式契约,
让未来的静默退化在测试层即红。**scripts/ 零改动** (守卫只报警不修本体)。

契约:
  1. 无旗标参数快照钉 (GAP-F-3): `_validate_param` 对 `flag is None` 走
     `if not flag: return []` 早退 —— 该参数**不产任何 argv 片段**; 若它
     又不是该工具的 stdin 通道, 其值将被**静默丢弃** (argv 无该值、无报错)。
     现状危险面 = `rm_lookup.query` (实测实证见本单 GAP-F-7: `query` 是
     `rm_lookup.py` 的**位置参数**, 但 `plan_tool_call` 不追加位置参数, 故
     值确被丢弃)。本钉锁"集合形态": 集合若变化即红, 提示须过设计。
  2. schema_type 白名单钉 (GAP-F-6): 全注册表 `schema_type` 只能是
     {string, integer, boolean}。`_validate_param` 的 `else` 分支把一切
     非 integer/非 boolean 值当 str 校验 (当下 fail-closed, 无实害),
     但新类型静默落入 str 语义属**未过设计的隐式行为** → 白名单钉住。
  3. `project` 属性形态钉 (GAP-F-8, 本单新发现, 只列不改):
     `tool_input_schema` 里 `props["project"]` 因 mcp_server.py 尾逗号被赋成
     1-元 tuple → 序列化出的 inputSchema 中 `properties.project` 是 JSON
     **数组**而非对象 (畸形 schema)。本钉把现状钉住并在修好后转红, 提示同步
     更新快照 —— **不修 scripts/ 本体** (守卫只报警)。
"""
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import mcp_server  # noqa: E402


def _flag_none_params(registry):
    """全注册表 `flag is None` 的 (tool, param) 集合。"""
    found = set()
    for tool_name, tool in registry.items():
        for p_name, p_spec in tool["params"].items():
            if p_spec[2] is None:
                found.add((tool_name, p_name))
    return found


def _flag_none_non_stdin_params(registry):
    """`flag is None` 且**非**该工具 stdin 通道的 (tool, param) 集合 ——
    唯一真正会静默丢值的危险面。"""
    found = set()
    for tool_name, tool in registry.items():
        stdin_param = tool.get("stdin_param")
        for p_name, p_spec in tool["params"].items():
            if p_spec[2] is None and p_name != stdin_param:
                found.add((tool_name, p_name))
    return found


def _schema_type_histogram(registry):
    """全注册表 schema_type → 参数个数。"""
    hist = Counter()
    for tool in registry.values():
        for p_spec in tool["params"].values():
            hist[p_spec[0]] += 1
    return hist


class NoFlagParamSnapshotTests(unittest.TestCase):
    """GAP-F-3 门神: 无旗标参数集 = 现场盘点快照 (2026-09-21, 基线 1122803)"""

    # 现场盘点: 6 工具 / 18 参数。
    #   flag is None 全集 = {("diagnose_hardfault","text"), ("rm_lookup","query")}
    #   └ text 是 diagnose_hardfault 的 stdin 通道 → 值经 stdin 送, 不丢;
    #     query **无旗标且非 stdin** → 值静默丢弃 (危险面, 已登记 GAP-F-7)。
    NO_FLAG_SNAPSHOT = {
        ("diagnose_hardfault", "text"),
        ("rm_lookup", "query"),
    }
    NO_FLAG_NON_STDIN_SNAPSHOT = {
        ("rm_lookup", "query"),
    }

    def test_no_flag_param_set_matches_snapshot(self):
        actual = _flag_none_params(mcp_server._TOOL_REGISTRY)
        self.assertEqual(
            actual, self.NO_FLAG_SNAPSHOT,
            "无旗标参数集变化 —— 新增无旗标参数必须过设计: "
            f"新增 {sorted(actual - self.NO_FLAG_SNAPSHOT)} / "
            f"消失 {sorted(self.NO_FLAG_SNAPSHOT - actual)}")

    def test_no_flag_non_stdin_set_matches_snapshot(self):
        actual = _flag_none_non_stdin_params(mcp_server._TOOL_REGISTRY)
        self.assertEqual(
            actual, self.NO_FLAG_NON_STDIN_SNAPSHOT,
            "出现新的『无旗标且非 stdin』参数 —— 其值会被 _validate_param "
            "静默丢弃 (argv 无该值、无报错): "
            f"新增 {sorted(actual - self.NO_FLAG_NON_STDIN_SNAPSHOT)} / "
            f"消失 {sorted(self.NO_FLAG_NON_STDIN_SNAPSHOT - actual)}")

    def test_snapshot_entries_are_really_flagless(self):
        # 反向自证: 快照内每个 (tool, param) 在注册表真实存在且 flag is None
        for tool_name, p_name in self.NO_FLAG_SNAPSHOT:
            spec = mcp_server._TOOL_REGISTRY[tool_name]["params"][p_name]
            self.assertIsNone(spec[2], f"{tool_name}.{p_name} 的 flag 已非 None")

    def test_stdin_param_excluded_from_danger_set(self):
        # text 走 stdin 通道 (值不丢) → 必须不在危险面
        owners = [t for t, tool in mcp_server._TOOL_REGISTRY.items()
                  if tool.get("stdin_param") == "text"]
        self.assertEqual(owners, ["diagnose_hardfault"])
        self.assertIn(("diagnose_hardfault", "text"), self.NO_FLAG_SNAPSHOT)
        self.assertNotIn(("diagnose_hardfault", "text"),
                         self.NO_FLAG_NON_STDIN_SNAPSHOT)


class SchemaTypeWhitelistTests(unittest.TestCase):
    """GAP-F-6 门神: schema_type ∈ {string, integer, boolean}"""

    ALLOWED = {"string", "integer", "boolean"}
    # 现场盘点 histogram (2026-09-21): string 10 / integer 6 / boolean 2
    HISTOGRAM_SNAPSHOT = {"string": 10, "integer": 6, "boolean": 2}

    def test_all_schema_types_in_whitelist(self):
        offenders = {}
        for tool_name, tool in mcp_server._TOOL_REGISTRY.items():
            for p_name, p_spec in tool["params"].items():
                if p_spec[0] not in self.ALLOWED:
                    offenders[(tool_name, p_name)] = p_spec[0]
        self.assertEqual(
            offenders, {},
            f"schema_type 越白名单 (须 ∈ {sorted(self.ALLOWED)}): {offenders}")

    def test_schema_type_histogram_matches_snapshot(self):
        actual = dict(_schema_type_histogram(mcp_server._TOOL_REGISTRY))
        self.assertEqual(
            actual, self.HISTOGRAM_SNAPSHOT,
            "schema_type 分布变化 —— 新增参数须过设计并同步本快照")

    def test_tool_input_schema_types_are_whitelisted(self):
        # 端到端: 注册表 → inputSchema, 注册表驱动的每个参数的 type 都须在
        # 白名单。此处按 p_name 取名 (而非遍历 properties 全集), 因为
        # inputSchema 还含注册表外合成项 (requires_project → "project"),
        # 该项的形态另由 ProjectPropShapeTests 钉住。
        for tool_name, tool in mcp_server._TOOL_REGISTRY.items():
            schema = mcp_server.tool_input_schema(tool_name)
            for p_name in tool["params"]:
                prop = schema["properties"][p_name]
                self.assertIn(
                    prop["type"], self.ALLOWED,
                    f"{tool_name}.{p_name} 的 inputSchema type 越白名单: "
                    f"{prop['type']}")


class ProjectPropShapeTests(unittest.TestCase):
    """GAP-F-8 门神 (本单新发现, 只列不改):

    `mcp_server.py` 的

        props["project"] = {
            "type": "string",
            "description": "…"},          ← 尾逗号

    使 RHS 成为 **1-元 tuple**。故 `tool_input_schema("run_verify")` 的
    `properties.project` 是 `({...},)` —— JSON 序列化后是**数组**而非对象,
    对 MCP 客户端是畸形 schema (properties 的值必须是 schema 对象)。
    既有钉 `test_schema_generated_from_registry` 只断言 key 存在, 故未捕捉。

    本钉把当前形态钉住 (报警): 一旦维护者修掉尾逗号, 本钉转红 —— 那正是
    "GAP-F-8 已修"的信号, 请同步更新本快照并关闭该缺口。
    """

    PROJECT_OWNERS = ("run_verify", "lint_expectations")

    def test_project_prop_shape_is_pinned(self):
        for tool_name in self.PROJECT_OWNERS:
            with self.subTest(tool=tool_name):
                prop = mcp_server.tool_input_schema(
                    tool_name)["properties"]["project"]
                self.assertIsInstance(
                    prop, tuple,
                    f"{tool_name}.project 形态已变 ({type(prop).__name__}) —— "
                    "若已修为 dict, 请更新本快照并关闭 GAP-F-8")
                self.assertEqual(len(prop), 1)
                self.assertIsInstance(prop[0], dict)
                self.assertEqual(prop[0].get("type"), "string")

    def test_project_prop_only_on_project_tools(self):
        # 反向: 非 requires_project 的工具不得凭空出现 project 属性
        for tool_name, tool in mcp_server._TOOL_REGISTRY.items():
            props = mcp_server.tool_input_schema(tool_name)["properties"]
            if tool.get("requires_project"):
                self.assertIn("project", props, tool_name)
            else:
                self.assertNotIn("project", props, tool_name)


if __name__ == "__main__":
    unittest.main()
