r"""F-237: svd_to_json 的 CLI 与解析基元补测。

## 覆盖对象

`scripts/svd_to_json.py` 此前 63% 覆盖（2026-11-02 实测）：`main()` 整段
（--list / --periph / --all / --merge / 错误分支）从未执行，另有
`parse_bit_range`、`parse_dim_element_group` 等基元缺测。

## 夹具

临时目录里合成最小 SVD（两个外设：标量寄存器 + dimElementGroup 数组），
不依赖 Keil Pack / ST 官方 SVD，CI 陌生人克隆路径也能跑。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import svd_to_json  # noqa: E402

SVD_XML = """<?xml version="1.0" encoding="utf-8"?>
<device>
  <peripherals>
    <peripheral>
      <name>GPIOA</name>
      <description>General purpose IO</description>
      <baseAddress>0x40010800</baseAddress>
      <registers>
        <register>
          <name>CRL</name>
          <description>Configuration low</description>
          <addressOffset>0x00</addressOffset>
          <fields>
            <field>
              <name>MODE0</name>
              <description>Mode bits</description>
              <bitRange>[1:0]</bitRange>
            </field>
            <field>
              <name>CNF0</name>
              <bitOffset>2</bitOffset>
              <bitWidth>2</bitWidth>
              <access>read-only</access>
              <enumeratedValues>
                <enumeratedValue><name>IN</name><value>0</value></enumeratedValue>
                <enumeratedValue><name>OUT</name><value>1</value><description>Output</description></enumeratedValue>
              </enumeratedValues>
            </field>
          </fields>
        </register>
      </registers>
    </peripheral>
    <peripheral>
      <name>TIM2</name>
      <description>Timer 2</description>
      <baseAddress>0x40000000</baseAddress>
      <registers>
        <register>
          <name>CCR%s</name>
          <description>Capture compare</description>
          <dim>4</dim>
          <dimIncrement>0x4</dimIncrement>
          <dimIndex>1,2,3,4</dimIndex>
          <addressOffset>0x34</addressOffset>
        </register>
      </registers>
    </peripheral>
  </peripherals>
</device>
"""


def _write_svd(tmpdir: str, text: str = SVD_XML) -> str:
    path = os.path.join(tmpdir, "mini.svd")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "svd_to_json.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=120,
    )


class ParseBitRangeTests(unittest.TestCase):
    def test_low_nibble(self):
        self.assertEqual(svd_to_json.parse_bit_range("[3:0]"), (0, 4))

    def test_high_nibble(self):
        self.assertEqual(svd_to_json.parse_bit_range("[31:16]"), (16, 16))

    def test_single_bit(self):
        self.assertEqual(svd_to_json.parse_bit_range("[5:5]"), (5, 1))


class ParseDimElementGroupTests(unittest.TestCase):
    def test_plain_register_has_no_dimension(self):
        reg = ET.fromstring("<register><name>CR</name></register>")
        self.assertEqual(svd_to_json.parse_dim_element_group(reg), [(None, None)])

    def test_placeholder_name_uses_dim_index(self):
        reg = ET.fromstring(
            "<register><name>CCR%s</name><dim>4</dim>"
            "<dimIncrement>0x4</dimIncrement><dimIndex>1,2,3,4</dimIndex></register>"
        )
        self.assertEqual(
            svd_to_json.parse_dim_element_group(reg),
            [("1", 0), ("2", 1), ("3", 2), ("4", 3)],
        )

    def test_name_without_placeholder_gets_underscore_suffix(self):
        reg = ET.fromstring(
            "<register><name>CCR</name><dim>2</dim>"
            "<dimIncrement>0x4</dimIncrement></register>"
        )
        self.assertEqual(
            svd_to_json.parse_dim_element_group(reg),
            [("_0", 0), ("_1", 1)],
        )


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svd = _write_svd(self.tmp.name)

    def test_extract_single_returns_fields_and_enums(self):
        name, data = svd_to_json.extract_single(self.svd, "GPIOA")
        self.assertEqual(name, "GPIOA")
        self.assertEqual(data["base"], "0x40010800")
        crl = data["registers"]["CRL"]
        self.assertEqual(crl["offset"], "0x00")
        self.assertEqual(crl["bits"]["0:1"]["name"], "MODE0")
        self.assertEqual(crl["bits"]["2:3"]["access"], "read-only")
        self.assertEqual(crl["bits"]["2:3"]["enum"]["OUT"], {"value": "1", "desc": "Output"})

    def test_register_array_offsets_follow_dim_increment(self):
        _, data = svd_to_json.extract_single(self.svd, "TIM2")
        self.assertEqual(sorted(data["registers"]), ["CCR1", "CCR2", "CCR3", "CCR4"])
        self.assertEqual(data["registers"]["CCR1"]["offset"], "0x34")
        self.assertEqual(data["registers"]["CCR2"]["offset"], "0x0038")
        self.assertEqual(data["registers"]["CCR4"]["offset"], "0x0040")

    def test_extract_single_missing_peripheral_returns_none(self):
        name, data = svd_to_json.extract_single(self.svd, "NOPE")
        self.assertIsNone(name)
        self.assertIsNone(data)

    def test_list_peripherals_reports_name_base_and_desc(self):
        periphs = svd_to_json.list_peripherals(self.svd)
        by_name = {p["name"]: p for p in periphs}
        self.assertEqual(by_name["GPIOA"]["base"], "0x40010800")
        self.assertEqual(by_name["TIM2"]["desc"], "Timer 2")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svd = _write_svd(self.tmp.name)

    def test_missing_svd_exits_one(self):
        proc = _run_cli("--svd", os.path.join(self.tmp.name, "nope.svd"), "--list")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("SVD file not found", proc.stderr)

    def test_list_prints_peripherals(self):
        proc = _run_cli("--svd", self.svd, "--list")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("GPIOA", proc.stdout)
        self.assertIn("Total: 2 peripherals", proc.stdout)

    def test_periph_json_output(self):
        proc = _run_cli("--svd", self.svd, "--periph", "GPIOA", "--json")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["GPIOA"]["base"], "0x40010800")

    def test_periph_human_output(self):
        proc = _run_cli("--svd", self.svd, "--periph", "GPIOA")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("=== GPIOA ===", proc.stdout)
        self.assertIn("Registers", proc.stdout)
        self.assertIn("bit 0:1: MODE0", proc.stdout)

    def test_periph_missing_exits_one(self):
        proc = _run_cli("--svd", self.svd, "--periph", "NOPE")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not found", proc.stderr)

    def test_all_to_out_dir_writes_one_file_per_peripheral(self):
        out = os.path.join(self.tmp.name, "out")
        proc = _run_cli("--svd", self.svd, "--all", "--out", out)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Extracted 2 peripherals", proc.stdout)
        self.assertEqual(sorted(os.listdir(out)), ["gpioa.json", "tim2.json"])

    def test_all_without_out_prints_json(self):
        proc = _run_cli("--svd", self.svd, "--all")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(sorted(data), ["GPIOA", "TIM2"])

    def test_all_merge_into_ref(self):
        ref = os.path.join(self.tmp.name, "ref.json")
        with open(ref, "w", encoding="utf-8") as fh:
            json.dump({"peripherals": {}, "_meta": {}}, fh)
        proc = _run_cli("--svd", self.svd, "--all", "--merge", ref)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Merged 2 new peripherals", proc.stdout)
        with open(ref, encoding="utf-8") as fh:
            merged = json.load(fh)
        self.assertEqual(sorted(merged["peripherals"]), ["GPIOA", "TIM2"])
        self.assertEqual(merged["_meta"]["peripheral_count"], 2)

    def test_all_without_peripherals_element_exits_one(self):
        bad = _write_svd(self.tmp.name, "<device></device>")
        proc = _run_cli("--svd", bad, "--all")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No <peripherals> element", proc.stderr)

    def test_no_action_prints_help(self):
        proc = _run_cli("--svd", self.svd)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--periph", proc.stdout)


if __name__ == "__main__":
    unittest.main()
