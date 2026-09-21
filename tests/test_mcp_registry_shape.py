r"""MCP 注册表形态与参数投影守卫 (F-182 / F-183)。

本文件把 `scripts/mcp_server.py` 注册表层的隐式约定钉成显式契约, 让未来的
静默退化在测试层即红。

F-182 (WB-20260921-03) 建立三组守卫 (无旗标参数快照 / schema_type 白名单 /
project 属性形态), 当时 **scripts/ 零改动, 守卫只报警**。

F-183 (WB-20260921-04) 按维护者裁决收口两处正门缺陷:
  · **GAP-F-7 闭合 —— 位置投影**: `rm_lookup.py` 的 CLI 真相是
    `parser.add_argument("query", nargs="?")` —— **位置参数**。MCP 层把
    `query` 宣告进 inputSchema 却永不送达 (旧 `_validate_param` 对
    `flag is None` 直接 `return []`, `plan_tool_call` 又只 extend 旗标片段)。
    裁决 = 走**位置参数路线**(不发明旗标): `flag is None` 且非该工具 stdin
    通道的参数 → `_validate_param` 返 `[str(value)]`, `plan_tool_call` 在
    旗标片段之后把位置片段追加到 argv **尾部**。
  · **GAP-F-8 闭合 —— `project` schema 尾逗号**: `props["project"] = { … },`
    的尾逗号使 RHS 成 1-元 tuple → 序列化后 `properties.project` 是 JSON
    **数组**而非对象 (畸形 schema)。裁决 = 去尾逗号, 从 tuple 还原为 dict。

契约 (对应守卫):
  1. 无旗标参数**全集**快照 (GAP-F-3): `flag is None` 的 (tool, param) 集合,
     集合变化即红 (新增无旗标参数必须过设计)。
  2. 无旗标且非 stdin 的**丢值面**快照 (GAP-F-7): 判据 = `_validate_param`
     对该参数**不产任何 argv 片段** —— 值必然送不到 CLI。F-183 后该集合
     必须为 **∅** (全部经位置片段送达)。
  3. schema_type 白名单钉 (GAP-F-6): 全注册表 `schema_type` 只能 ∈
     {string, integer, boolean} (`else` 分支把一切非 integer/非 boolean 值
     当 str 校验 —— 当下 fail-closed 无实害, 但新类型静默落 str 语义属
     未经设计的隐式行为)。
  4. `project` 属性**形态**钉 (GAP-F-8): 必须是 schema 对象 (dict), 必备键
     `type` / `description`; 整份 inputSchema 可 JSON 序列化后仍为对象。
  5. **位置投影端到端** (F-183 T1): 值按注册顺序追加到 argv **尾部**;
     不传则不产多余尾巴 (`nargs="?"` 语义); stdin 通道仍**不进** argv;
     真 CLI 冒烟 (只读查询) 证明值确实送达。
"""
import json
import os
import subprocess
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import mcp_server  # noqa: E402

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _script_argv(script_name, *flags):
    """独立于 mcp_server 内部实现的期望 argv 前缀 (钉 wire 形态)。"""
    return [sys.executable, os.path.join(_SCRIPTS, script_name)] + list(flags)


def _flag_none_params(registry):
    """全注册表 `flag is None` 的 (tool, param) 集合。"""
    found = set()
    for tool_name, tool in registry.items():
        for p_name, p_spec in tool["params"].items():
            if p_spec[2] is None:
                found.add((tool_name, p_name))
    return found


def _dropped_value_params(registry):
    """**值必然送不到 CLI** 的 (tool, param) 集合 —— 无旗标且非 stdin 通道,
    且 `_validate_param` 对该参数**不产任何 argv 片段**。

    判据中性化校验器: 校验与投影正交 (`reason` 非空时抛错、否则下行到投影
    分支), 故把 checker 置 None 后只探"是否产片段", 避免逐参数试值时
    "探针值过不了该参数校验器"引入的噪声 —— 那会让判据静默跳过而非报红。

    F-182 基线: {("rm_lookup", "query")} (唯一命中, 值静默丢弃, GAP-F-7)。
    F-183 后: **∅** (位置投影送达)。
    """
    found = set()
    for tool_name, tool in registry.items():
        stdin_param = tool.get("stdin_param")
        for p_name, p_spec in tool["params"].items():
            if p_spec[2] is not None or p_name == stdin_param:
                continue
            schema_type, _checker, flag, desc = p_spec
            probe = 1 if schema_type == "integer" else "PROBE"
            pieces = mcp_server._validate_param(
                tool_name, p_name, (schema_type, None, flag, desc), probe)
            if not pieces:
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
    #     query 无旗标且非 stdin → F-182 时值静默丢弃 (GAP-F-7),
    #     **F-183 已按位置参数路线闭合** → 丢值面为 ∅ (见下方快照)。
    NO_FLAG_SNAPSHOT = {
        ("diagnose_hardfault", "text"),
        ("rm_lookup", "query"),
    }
    # F-183 闭合: query 已位置投影 → 无旗标非 stdin 参数中**不再有**丢值项。
    NO_FLAG_NON_STDIN_DROP_SNAPSHOT = set()

    def test_no_flag_param_set_matches_snapshot(self):
        actual = _flag_none_params(mcp_server._TOOL_REGISTRY)
        self.assertEqual(
            actual, self.NO_FLAG_SNAPSHOT,
            "无旗标参数集变化 —— 新增无旗标参数必须过设计: "
            f"新增 {sorted(actual - self.NO_FLAG_SNAPSHOT)} / "
            f"消失 {sorted(self.NO_FLAG_SNAPSHOT - actual)}")

    def test_no_flag_non_stdin_drop_set_matches_snapshot(self):
        actual = _dropped_value_params(mcp_server._TOOL_REGISTRY)
        self.assertEqual(
            actual, self.NO_FLAG_NON_STDIN_DROP_SNAPSHOT,
            "出现『无旗标 且 非 stdin 且 不产 argv 片段』的参数 —— 其值会被"
            "静默丢弃 (argv 无该值、无报错): "
            f"新增 {sorted(actual - self.NO_FLAG_NON_STDIN_DROP_SNAPSHOT)} / "
            f"消失 {sorted(self.NO_FLAG_NON_STDIN_DROP_SNAPSHOT - actual)} — "
            "F-183 裁决: 这类参数须走**位置片段**投影 (flag=None 时 "
            "_validate_param 应返 [str(value)])")

    def test_snapshot_entries_are_really_flagless(self):
        # 反向自证: 快照内每个 (tool, param) 在注册表真实存在且 flag is None
        for tool_name, p_name in self.NO_FLAG_SNAPSHOT:
            spec = mcp_server._TOOL_REGISTRY[tool_name]["params"][p_name]
            self.assertIsNone(spec[2], f"{tool_name}.{p_name} 的 flag 已非 None")

    def test_stdin_param_excluded_from_danger_set(self):
        # text 走 stdin 通道 (值不丢) → 必须不在丢值面
        owners = [t for t, tool in mcp_server._TOOL_REGISTRY.items()
                  if tool.get("stdin_param") == "text"]
        self.assertEqual(owners, ["diagnose_hardfault"])
        self.assertIn(("diagnose_hardfault", "text"), self.NO_FLAG_SNAPSHOT)
        self.assertNotIn(("diagnose_hardfault", "text"),
                         self.NO_FLAG_NON_STDIN_DROP_SNAPSHOT)


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
    """GAP-F-8 门神 —— F-183 已**翻正**: `properties.project` 必须是 schema
    对象 (JSON object), 不得是数组/tuple。

    F-182 时 `props["project"] = { … },` 的尾逗号使 RHS 成 1-元 tuple →
    JSON 序列化后是**数组** —— 对 MCP 客户端是畸形 schema (properties 的值
    必须是 schema 对象)。该形态曾由本类钉住报警; 维护者裁决「去尾逗号,
    从 tuple 还原为 dict」后, 本类翻正为**正确形态**断言:

      · `properties.project` 是 dict, 必备键 `type` / `description`;
      · `type` 实为 `"string"` —— project 是**固件工程根目录路径字符串**
        (由 `resolve_project` 做目录+`.workbench/config.json` 白名单校验)。
        ⚠ 与 inputSchema **顶层**的 `"type": "object"` 分属两层, 不可混读;
      · 整份 inputSchema `type(schema) is dict` 且序列化后仍为对象。
    """

    PROJECT_OWNERS = ("run_verify", "lint_expectations")

    def test_project_prop_is_schema_object(self):
        for tool_name in self.PROJECT_OWNERS:
            with self.subTest(tool=tool_name):
                prop = mcp_server.tool_input_schema(
                    tool_name)["properties"]["project"]
                self.assertNotIsInstance(
                    prop, tuple,
                    f"{tool_name}.project 仍是 tuple (GAP-F-8 尾逗号复发)")
                self.assertIsInstance(
                    prop, dict,
                    f"{tool_name}.project 须为 schema 对象 (dict), 实为 "
                    f"{type(prop).__name__}")
                for key in ("type", "description"):
                    self.assertIn(key, prop, f"{tool_name}.project 缺必备键 {key}")
                    self.assertIsInstance(prop[key], str, f"{tool_name}.project.{key}")

    def test_project_prop_declares_string_type(self):
        for tool_name in self.PROJECT_OWNERS:
            with self.subTest(tool=tool_name):
                prop = mcp_server.tool_input_schema(
                    tool_name)["properties"]["project"]
                self.assertEqual(prop["type"], "string", prop)

    def test_input_schema_is_json_object(self):
        # `type(schema) 恒 dict` 两工具各一例 + 顶层是 JSON object schema
        for tool_name in self.PROJECT_OWNERS:
            with self.subTest(tool=tool_name):
                schema = mcp_server.tool_input_schema(tool_name)
                self.assertIs(type(schema), dict)
                self.assertEqual(schema["type"], "object")
                self.assertIn("project", schema["required"])

    def test_input_schema_json_roundtrip_keeps_props_objects(self):
        # tuple 会被 json 静默转数组 (不报错) → 只在 roundtrip 后仍为 dict
        # 才算"客户端拿到的 properties 值是对象"。
        for tool_name, _tool in mcp_server._TOOL_REGISTRY.items():
            with self.subTest(tool=tool_name):
                schema = mcp_server.tool_input_schema(tool_name)
                dumped = json.loads(json.dumps(schema))
                for p_name, prop in dumped["properties"].items():
                    self.assertIsInstance(
                        prop, dict,
                        f"{tool_name}.properties.{p_name} 序列化后非对象: "
                        f"{type(prop).__name__}")

    def test_project_prop_only_on_project_tools(self):
        # 反向: 非 requires_project 的工具不得凭空出现 project 属性
        for tool_name, tool in mcp_server._TOOL_REGISTRY.items():
            props = mcp_server.tool_input_schema(tool_name)["properties"]
            if tool.get("requires_project"):
                self.assertIn("project", props, tool_name)
            else:
                self.assertNotIn("project", props, tool_name)


class PositionalProjectionTests(unittest.TestCase):
    """F-183 T1 / GAP-F-7 门神: 无旗标非 stdin 参数按**位置片段**送达 CLI。

    裁决依据 (简报 §2 T1): `rm_lookup.py` 的 CLI 真相是
    `parser.add_argument("query", nargs="?")` —— 位置参数。MCP 层宣告了该
    参数却永不送达, 正确映射是把值作为**位置片段**追加, 而非发明旗标。
    """

    def test_query_is_projected_as_trailing_positional(self):
        plan = mcp_server.plan_tool_call("rm_lookup", {"query": "GPIOA"})
        argv = plan["argv"]
        self.assertEqual(
            argv, _script_argv("rm_lookup.py", "--json", "GPIOA"),
            "query 必须作为**末位位置片段**送达 (不发明旗标)")
        self.assertEqual(argv[-1], "GPIOA")
        self.assertEqual(argv.count("GPIOA"), 1, argv)
        self.assertTrue(all(isinstance(a, str) for a in argv), argv)

    def test_query_absent_produces_no_trailing_piece(self):
        # 反向钉: 不传 query → argv 无多余尾巴 (nargs="?" 的 default 语义)
        plan = mcp_server.plan_tool_call("rm_lookup", {})
        argv = plan["argv"]
        self.assertEqual(argv, _script_argv("rm_lookup.py", "--json"), argv)
        self.assertEqual(len(argv), len(_script_argv("rm_lookup.py", "--json")))

    def test_flagged_params_still_use_flags(self):
        # 位置路线**不改**有旗标参数的形态 (回归护栏)
        plan = mcp_server.plan_tool_call(
            "rm_lookup", {"recipe": "I2C", "query": "GPIOA"})
        argv = plan["argv"]
        base = _script_argv("rm_lookup.py", "--json")
        self.assertEqual(argv[:len(base)], base, argv)
        self.assertEqual(argv[argv.index("--recipe") + 1], "I2C")
        self.assertEqual(argv.count("--recipe"), 1, argv)
        self.assertEqual(argv[-1], "GPIOA", argv)

    def test_positional_value_is_str_and_never_bare_type(self):
        # F-180 契约同式: 位置片段同样 str 化 (registry 里 query 是 string,
        # 但类型收口是**统一**契约, 故对整份 argv 断言全 str)。
        plan = mcp_server.plan_tool_call("rm_lookup", {"query": "GPIOA"})
        self.assertTrue(all(isinstance(a, str) for a in plan["argv"]),
                        plan["argv"])
        cmdline = subprocess.list2cmdline(plan["argv"])   # 不得抛
        self.assertIsInstance(cmdline, str)

    def test_stdin_channel_param_still_not_in_argv(self):
        # stdin 通道钉: diagnose_hardfault.text 仍**不进** argv (走 stdin,
        # 现状不变 —— 位置投影只覆盖"非 stdin 通道"的那一类)。
        text = "PROBE_STDIN_SENTINEL [HF] PC=080001CC LR=080002F1"
        plan = mcp_server.plan_tool_call("diagnose_hardfault", {"text": text})
        argv = plan["argv"]
        self.assertEqual(plan["stdin_text"], text)
        self.assertEqual(
            argv,
            _script_argv("hardfault.py", "--json", "--no-probe",
                         "--fault-text", "-"),
            "stdin 通道参数不得出现在 argv")
        self.assertNotIn(text, argv, argv)
        self.assertFalse([a for a in argv if "PROBE_STDIN_SENTINEL" in a], argv)

    def test_real_cli_smoke_query_reaches_the_query_result(self):
        # 真 CLI 冒烟 (§3⑤): 只跑 rm_lookup 只读查询, 不碰其它链, 不触硬件。
        # 旧实现下 argv 无 query → 子进程收不到查询词, 结果与查询无关;
        # 本钉以"真进程 stdout 里的 query 字段 == 传入值"为送达判据。
        plan = mcp_server.plan_tool_call("rm_lookup", {"query": "GPIOA"})
        proc = subprocess.run(
            plan["argv"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
            cwd=plan["cwd"])
        self.assertEqual(proc.returncode, 0,
                         f"rc={proc.returncode} stderr={proc.stderr[-400:]!r} "
                         f"argv={plan['argv']!r}")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["query"], "GPIOA",
                         "CLI 未收到 query (位置片段未送达)")
        self.assertTrue(payload["peripherals"],
                        "GPIOA 查询应至少命中 1 个外设")


if __name__ == "__main__":
    unittest.main()
