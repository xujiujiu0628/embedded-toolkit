r"""F-237: phase_minus_one 的 CLI、占用表三态与裁定出口补测。

## 覆盖对象

`scripts/phase_minus_one.py` 此前 63% 覆盖（2026-11-02 实测）：`cmd_list`、
`main` 派发、`load_fixed_pins` 的损坏/非对象分支、以及 BLOCKED 退出码
（F-196 T2 的 fail-loud 出口）从未执行。

## 夹具

- 占用表三态：无 workspace / 文件在场合法 / 文件在场但损坏 —— 直接调
  `load_fixed_pins`，不依赖真实工程；
- CLI：临时工程只放 `.workbench/config.json`（+ 可选 `fixed_pins.json`），
  真实 `data/stm32f103-ref.json` 只读消费。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SCRIPT = os.path.join(SCRIPTS, "phase_minus_one.py")
sys.path.insert(0, SCRIPTS)

import phase_minus_one  # noqa: E402


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=cwd, timeout=120, env=env,
    )


class FixedPinsTests(unittest.TestCase):
    def test_no_workspace_returns_none(self):
        self.assertIsNone(phase_minus_one.load_fixed_pins(None))

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(phase_minus_one.load_fixed_pins(tmp))

    def test_valid_map_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".workbench"))
            with open(os.path.join(tmp, ".workbench", "fixed_pins.json"), "w", encoding="utf-8") as fh:
                json.dump({"PB6": "I2C1 SCL"}, fh)
            self.assertEqual(phase_minus_one.load_fixed_pins(tmp), {"PB6": "I2C1 SCL"})

    def test_corrupt_json_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".workbench"))
            path = os.path.join(tmp, ".workbench", "fixed_pins.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            result = phase_minus_one.load_fixed_pins(tmp)
        self.assertIsInstance(result, phase_minus_one.FixedPinsCorrupt)
        self.assertEqual(result.path, path)

    def test_non_object_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".workbench"))
            with open(os.path.join(tmp, ".workbench", "fixed_pins.json"), "w", encoding="utf-8") as fh:
                json.dump(["PB6"], fh)
            result = phase_minus_one.load_fixed_pins(tmp)
        self.assertIsInstance(result, phase_minus_one.FixedPinsCorrupt)


class CmdListTests(unittest.TestCase):
    def test_lists_full_and_partial_counts(self):
        ref = {
            "peripherals": {"USART1": {"bus": "APB2", "base": "0x40013800"}},
            "_relationships": {"I2C1": {"bus": "APB1", "pins": ["PB6"]}},
        }
        buf = StringIO()
        with redirect_stdout(buf):
            phase_minus_one.cmd_list(ref)
        out = buf.getvalue()
        self.assertIn("USART1", out)
        self.assertIn("I2C1", out)
        self.assertIn("FULL:  1 peripherals", out)
        self.assertIn("PARTIAL: 1 peripherals", out)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.proj, ".workbench"))
        with open(os.path.join(self.proj, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")

    def _write_fixed_pins(self, content: str) -> None:
        with open(os.path.join(self.proj, ".workbench", "fixed_pins.json"), "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_list_flag_prints_coverage(self):
        proc = _run(self.proj, "--list")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FULL:", proc.stdout)
        self.assertIn("STM32F103C8T6", proc.stdout)

    def test_no_arguments_prints_help(self):
        proc = _run(self.proj)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Example:", proc.stdout)

    def test_known_peripheral_json_output(self):
        proc = _run(self.proj, "-p", "USART1", "--json")
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["chip"], "STM32F103C8T6")
        self.assertIn(result["verdict"], {"OK", "OK_WITH_WARNINGS"})
        self.assertEqual(result["checks"]["kb_coverage"]["status"], "FULL")

    def test_unknown_peripheral_blocks_as_unknown(self):
        """不在 KB 的外设 → UNKNOWN → BLOCKED（F-194: 未知不放行）。"""
        proc = _run(self.proj, "-p", "NOPE", "--json")
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["checks"]["kb_coverage"]["status"], "NONE")
        self.assertEqual(result["checks"]["chip_support"]["status"], "UNKNOWN")
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_unavailable_peripheral_blocks_with_exit_one(self):
        proc = _run(self.proj, "-p", "DAC", "--json")
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["checks"]["chip_support"]["status"], "UNAVAILABLE")
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_corrupt_fixed_pins_blocks(self):
        self._write_fixed_pins("{broken")
        proc = _run(self.proj, "-p", "USART1", "--json")
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["checks"]["pin_conflict"]["status"], "CORRUPT")
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_pin_conflict_blocks(self):
        self._write_fixed_pins(json.dumps({"PB6": "I2C1 SCL (OLED)"}))
        proc = _run(self.proj, "-p", "USART1", "--pins", "PB6", "--json")
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertEqual(result["checks"]["pin_conflict"]["status"], "CONFLICT")

    def test_shared_bus_pin_is_not_conflict(self):
        self._write_fixed_pins(json.dumps({"PB6": "I2C1 SCL (OLED)"}))
        proc = _run(self.proj, "-p", "I2C1", "--pins", "PB6", "--json")
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["checks"]["pin_conflict"]["status"], "OK")
        self.assertIn("share bus", result["checks"]["pin_conflict"]["detail"])


if __name__ == "__main__":
    unittest.main()
