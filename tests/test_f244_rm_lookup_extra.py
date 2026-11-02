r"""F-244: rm_lookup 的 pin-mapping 载入校验 / 人读输出 / CLI 互斥提示补测。

## 覆盖对象

`scripts/rm_lookup.py` 此前 89% 覆盖（2026-11-02 实测）：`load_pin_mapping`
的缺失/损坏/结构六种拒绝、`format_pins_result` 的入册与未入册两种输出、
`run_pins_mode` 的 rc 0/1/2、`main` 的 `--pins ""` 用法错误与同级互斥提示
未执行。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import rm_lookup  # noqa: E402


class LoadMappingTests(unittest.TestCase):
    def _load(self, payload, raw=False):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pins.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(payload if raw else json.dumps(payload))
            return rm_lookup.load_pin_mapping(path)

    def test_missing_file(self):
        with self.assertRaises(rm_lookup.PinMappingError) as ctx:
            rm_lookup.load_pin_mapping(os.path.join(tempfile.gettempdir(), "no-pins.json"))
        self.assertIn("不存在", str(ctx.exception))

    def test_corrupt_json(self):
        with self.assertRaises(rm_lookup.PinMappingError):
            self._load("{broken", raw=True)

    def test_top_level_not_object(self):
        with self.assertRaises(rm_lookup.PinMappingError):
            self._load([1, 2])

    def test_block_not_object(self):
        with self.assertRaises(rm_lookup.PinMappingError):
            self._load({"CAN": [1]})

    def test_entry_not_object(self):
        with self.assertRaises(rm_lookup.PinMappingError):
            self._load({"CAN": {"PA11": "CANRX"}})

    def test_missing_required_key(self):
        with self.assertRaises(rm_lookup.PinMappingError) as ctx:
            self._load({"CAN": {"PA11": {"function": "CANRX"}}})
        self.assertIn("缺必需键", str(ctx.exception))

    def test_valid_mapping(self):
        data = self._load({"CAN": {"PA11": {"function": "CANRX", "column": "1",
                                            "source": "DS5319"}}})
        self.assertIn("CAN", data)


class FormatPinsTests(unittest.TestCase):
    def test_registered_rows(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rm_lookup.format_pins_result({
                "query": "can", "registered": True,
                "rows": [{"pin": "PA11", "function": "CANRX",
                          "column": "1", "source": "DS5319"}]})
        text = out.getvalue()
        self.assertIn("=== pin-mapping: CAN ===", text)
        self.assertIn("PA11", text)
        self.assertIn("CANRX", text)

    def test_unregistered_points_to_changelog(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rm_lookup.format_pins_result(
                {"query": "SPI", "registered": False, "known": ["CAN", "I2C1"]})
        text = out.getvalue()
        self.assertIn("未入册", text)
        self.assertIn("CAN, I2C1", text)
        self.assertIn("F-189/F-193", text)


class RunPinsModeTests(unittest.TestCase):
    def test_empty_query_returns_two(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(rm_lookup.run_pins_mode("  "), 2)
        self.assertIn("非空外设名", err.getvalue())

    def test_missing_data_returns_one(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = rm_lookup.run_pins_mode(
                "CAN", path=os.path.join(tempfile.gettempdir(), "no-pins.json"))
        self.assertEqual(rc, 1)
        self.assertIn("Error:", err.getvalue())

    def test_registered_json_returns_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = rm_lookup.run_pins_mode("CAN", json_mode=True)
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out.getvalue())["registered"])


class MainMutualExclusionTests(unittest.TestCase):
    def _run(self, argv):
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

    def test_empty_pins_is_usage_error(self):
        rc, _, err = self._run(["--pins", ""])
        self.assertEqual(rc, 2)
        self.assertIn("非空外设名", err)

    def test_query_plus_pins_note(self):
        rc, _, err = self._run(["CAN", "--pins", "CAN", "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("query 与 --pins 同给", err)

    def test_list_plus_pins_note(self):
        rc, out, err = self._run(["--list", "--pins", "CAN"])
        self.assertIsNone(rc)
        self.assertIn("--pins 本次未执行", err)
        self.assertIn("参考手册知识库", out)


if __name__ == "__main__":
    unittest.main()
