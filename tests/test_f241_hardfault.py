r"""F-241: hardfault 的 main / --no-probe / 人读报告补测。

## 覆盖对象

`scripts/hardfault.py` 此前 61% 覆盖（2026-11-02 实测）：`main()` 整段
（live 探针解析、--raw、--fault-text、JSON/人读输出）、`_diagnose_from_text`
（--no-probe 仅解析通道）与 `_print_readable` 未执行。

## 夹具

`run_openocd_diag` / `parse_map_symbols` / `_default_map_path` /
`_map_degradation_note` / `resolve_address` 模块引用替换；寄存器原文按
OpenOCD 真实格式合成，不接探针。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hardfault  # noqa: E402

RAW = """pc (/32): 0x0800012a
lr (/32): 0x08000200
sp (/32): 0x20001000
xpsr (/32): 0x01000000
msp (/32): 0x20001000
psp (/32): 0x20002000
r0 (/32): 0x00000001
r1 (/32): 0x00000002
r2 (/32): 0x00000003
r3 (/32): 0x00000004
0xe000ed28: 00000002
0xe000ed2c: 40000000
0xe000ed38: 00000000
0xe000ed34: 0x00000000
"""

SYMBOLS = [{"name": "main", "addr": 0x08000000, "size": 0x400},
           {"name": "fault_handler", "addr": 0x08000100, "size": 0x100}]


def _run_main(argv, *, raw=RAW, symbols=None, note=None):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["hardfault.py", *argv]
    try:
        with mock.patch.object(hardfault, "run_openocd_diag", return_value=raw), \
                mock.patch.object(hardfault, "parse_map_symbols",
                                  return_value=SYMBOLS if symbols is None else symbols), \
                mock.patch.object(hardfault, "_default_map_path", return_value="fw.map"), \
                mock.patch.object(hardfault, "_map_degradation_note", return_value=note), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rc = hardfault.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class MainLiveTests(unittest.TestCase):
    def test_openocd_failure_exits_one(self):
        rc, out, _ = _run_main([], raw="")
        self.assertEqual(rc, 1)
        self.assertIn("OpenOCD failed to connect", out)

    def test_raw_output_returns_early(self):
        rc, out, _ = _run_main(["--raw"])
        self.assertIsNone(rc)
        self.assertIn("pc (/32)", out)

    def test_json_report_fields(self):
        rc, out, _ = _run_main(["--json"])
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "hardfault_detected")
        self.assertIn("registers", payload)
        self.assertIn("sticky_hygiene", payload)
        self.assertIn("diagnosis", payload)
        self.assertEqual(payload["_meta"]["map_file"], "fw.map")

    def test_resolved_addresses(self):
        rc, out, _ = _run_main(["--json"])
        payload = json.loads(out)
        self.assertIn("pc", payload["resolved"])
        self.assertRegex(payload["resolved"]["pc"], r"^(main|fault_handler)\+")

    def test_zero_pc_adds_note(self):
        raw = RAW.replace("pc (/32): 0x0800012a", "pc (/32): 0x00000000")
        rc, out, _ = _run_main(["--json"], raw=raw)
        payload = json.loads(out)
        self.assertIn("_note", payload)

    def test_degradation_note_goes_to_stderr(self):
        rc, _, err = _run_main(["--json"], note="符号表为空")
        self.assertIn("WARNING: 符号表为空", err)

    def test_readable_output(self):
        rc, out, _ = _run_main([])
        self.assertIsNone(rc)
        self.assertIn("HardFault 诊断报告", out)
        self.assertIn("Fault Type:", out)
        self.assertIn("Diagnosis:", out)

    def test_fault_text_site_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cap.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[HF] PC=0800012A LR=08000200\n")
            rc, out, _ = _run_main(["--json", "--fault-text", path])
        payload = json.loads(out)
        self.assertIn("fault_site", payload)
        self.assertEqual(payload["fault_site"]["source"], "layer1_stacked_frame")
        self.assertIn("pc_sym", payload["fault_site"])

    def test_unreadable_fault_text_warns(self):
        rc, out, err = _run_main(["--json", "--fault-text",
                                  os.path.join(tempfile.gettempdir(), "no-such-cap.txt")])
        self.assertIsNone(rc)
        self.assertIn("不可读", err)
        self.assertNotIn("fault_site", json.loads(out))


class NoProbeTests(unittest.TestCase):
    def _run(self, argv, text=None):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["hardfault.py", *argv]
        try:
            with mock.patch.object(hardfault, "parse_map_symbols",
                                   return_value=SYMBOLS), \
                    mock.patch.object(hardfault, "_default_map_path", return_value="fw.map"), \
                    mock.patch.object(hardfault, "_map_degradation_note", return_value=None), \
                    redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = hardfault.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()

    def test_no_probe_requires_fault_text(self):
        rc, out, _ = self._run(["--no-probe"])
        self.assertEqual(rc, 1)
        self.assertIn("需要配 --fault-text", out)

    def test_no_probe_parses_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cap.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[HF] PC=0800012A LR=08000200\n")
            rc, out, _ = self._run(["--no-probe", "--fault-text", path, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "parsed_text_only")
        self.assertIn("fault_site", payload)

    def test_no_probe_without_marker_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cap.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("no fault here\n")
            rc, out, _ = self._run(["--no-probe", "--fault-text", path, "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "no_fault_marker")


class PrintReadableTests(unittest.TestCase):
    def test_sticky_marks(self):
        report = {
            "fault_type": "BusFault",
            "registers": {"pc": "0x0800012A"},
            "fault_registers": {
                "cfsr": {"raw": "0x2", "bits": {"DACCVIOL": "x"}},
                "hfsr": {"raw": "0x40000000", "bits": {}},
                "bfar": "N/A", "mmfar": "N/A",
            },
            "sticky_hygiene": {
                "cfsr": {"before": "0x2", "after": "0x0", "cleared": True},
                "hfsr": {"before": "0x1", "after": "0x1", "cleared": False},
            },
            "resolved": {"pc": "main+0x12a"},
            "fault_site": {"pc": "0x0800012A", "lr": "0x08000200",
                           "pc_sym": "main+0x12a", "live_pc_note": "note"},
            "diagnosis": "diag text",
            "symbols_total": 2,
            "_note": "zero pc",
        }
        out = io.StringIO()
        with redirect_stdout(out):
            hardfault._print_readable(report)
        text = out.getvalue()
        self.assertIn("已清除", text)
        self.assertIn("仍残值!", text)
        self.assertIn("Fault Site", text)
        self.assertIn("note", text)
        self.assertIn("Note: zero pc", text)


if __name__ == "__main__":
    unittest.main()
