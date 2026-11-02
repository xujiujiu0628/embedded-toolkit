r"""F-239: rm_lookup 的关系查询与 CLI 路由补测。

## 覆盖对象

`scripts/rm_lookup.py` 此前 71% 覆盖（2026-11-02 实测）：`search_relationships`
的全部关系/类型别名/模糊建议分支、`format_rel_result`，以及 `main()` 的
--rel / --list / 无参帮助路由未执行。pins / 配方 / 人读输出的数据面已由
`test_rm_lookup_pins.py` 与 `test_rm_lookup_human_output.py` 覆盖。

## 夹具

关系查询用合成 ref 字典（分支判定），CLI 路由用仓内真实 ref.json（只读）。
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import rm_lookup  # noqa: E402

REF = {
    "_relationships": {
        "USART1": {"bus": "APB2", "dma": {"tx": "DMA1_CH4"},
                   "pins": ["PA9", "PA10"], "irq": "USART1_IRQn"},
        "I2C1": {"bus": "APB1", "pins": ["PB6", "PB7"]},
    }
}


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["rm_lookup.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = rm_lookup.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class SearchRelationshipsTests(unittest.TestCase):
    def test_no_relationships_data(self):
        result = rm_lookup.search_relationships("USART1 DMA", {})
        self.assertIn("No _relationships", result["error"])

    def test_all_relationships_when_no_type(self):
        result = rm_lookup.search_relationships("USART1", REF)
        self.assertEqual(result["peripheral"], "USART1")
        self.assertIn("dma", result["relationships"])

    def test_type_lookup(self):
        result = rm_lookup.search_relationships("USART1 dma", REF)
        self.assertEqual(result["type"], "dma")
        self.assertEqual(result["data"], {"tx": "DMA1_CH4"})

    def test_type_alias_pin_maps_to_pins(self):
        result = rm_lookup.search_relationships("I2C1 pin", REF)
        self.assertEqual(result["type"], "pins")

    def test_missing_type_lists_available(self):
        result = rm_lookup.search_relationships("I2C1 dma", REF)
        self.assertIn("not available", result["error"])
        self.assertIn("bus", result["error"])

    def test_unknown_peripheral_suggests_close_match(self):
        result = rm_lookup.search_relationships("USART DMA", REF)
        self.assertIn("Did you mean", result["suggestion"])

    def test_unknown_peripheral_without_match(self):
        result = rm_lookup.search_relationships("SPI9 DMA", REF)
        self.assertIn("not in relationships DB", result["error"])


class FormatRelResultTests(unittest.TestCase):
    def test_error_with_suggestion(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rm_lookup.format_rel_result(
                {"query": "USART", "error": "nope", "suggestion": "Did you mean: USART1?"})
        self.assertIn("nope", out.getvalue())
        self.assertIn("Did you mean", out.getvalue())

    def test_all_relationships_render(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rm_lookup.format_rel_result(
                {"query": "USART1", "peripheral": "USART1",
                 "relationships": {"bus": "APB2", "dma": {"tx": "CH4"}}})
        text = out.getvalue()
        self.assertIn("USART1 全部关系", text)
        self.assertIn("bus: APB2", text)
        self.assertIn('"tx": "CH4"', text)

    def test_typed_data_render_dict_and_scalar(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rm_lookup.format_rel_result(
                {"query": "q", "peripheral": "USART1", "type": "dma",
                 "data": {"tx": "CH4"}})
            rm_lookup.format_rel_result(
                {"query": "q", "peripheral": "USART1", "type": "irq",
                 "data": "USART1_IRQn"})
        text = out.getvalue()
        self.assertIn("USART1 → dma", text)
        self.assertIn("tx: CH4", text)
        self.assertIn("USART1_IRQn", text)


class MainRouteTests(unittest.TestCase):
    def test_rel_text_output(self):
        rc, out, _ = _run(["--rel", "USART1 DMA"])
        self.assertIsNone(rc)
        self.assertIn("USART1", out)

    def test_rel_json_output(self):
        rc, out, _ = _run(["--rel", "USART1 DMA", "--json"])
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["peripheral"], "USART1")

    def test_rel_unknown_reports_error(self):
        rc, out, _ = _run(["--rel", "SPI9 DMA"])
        self.assertIsNone(rc)
        self.assertIn("not in relationships DB", out)

    def test_list_prints_peripherals(self):
        rc, out, _ = _run(["--list"])
        self.assertIsNone(rc)
        self.assertIn("STM32F103 参考手册知识库", out)
        self.assertIn("个外设", out)

    def test_no_arguments_prints_help(self):
        rc, out, _ = _run([])
        self.assertIsNone(rc)
        self.assertIn("usage", out.lower())


if __name__ == "__main__":
    unittest.main()
