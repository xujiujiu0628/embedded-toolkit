r"""F-244: svd_to_json 的中断/寄存器属性/人读输出补测。

## 覆盖对象

`scripts/svd_to_json.py` 此前 86% 覆盖（2026-11-02 实测）：interrupt 解析、
寄存器的 size/access/reset 非缺省属性、无 addressOffset 的跳过、
`--periph` 人读输出（含 enum 注记）未执行。

## 夹具

合成 SVD：一个带中断与非常规属性的外设 + 一个人读路径。纯 XML 字符串，
不依赖官方 SVD。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import svd_to_json  # noqa: E402

SVD = """<?xml version="1.0" encoding="utf-8"?>
<device><peripherals>
  <peripheral>
    <name>USART1</name><description>USART</description>
    <baseAddress>0x40013800</baseAddress>
    <interrupt><name>USART1_IRQn</name><value>37</value>
      <description>USART1 global</description></interrupt>
    <registers>
      <register>
        <name>SR</name><description>Status</description>
        <addressOffset>0x00</addressOffset>
        <size>16</size><access>read-only</access><resetValue>0xC0</resetValue>
        <fields>
          <field><name>TXE</name><bitRange>[7:7]</bitRange>
            <enumeratedValues>
              <enumeratedValue><name>EMPTY</name><value>1</value></enumeratedValue>
            </enumeratedValues>
          </field>
        </fields>
      </register>
      <register><name>NOOFFSET</name><size>8</size></register>
    </registers>
  </peripheral>
</peripherals></device>
"""


class SvdExtraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.svd = os.path.join(self.tmp.name, "x.svd")
        with open(self.svd, "w", encoding="utf-8") as fh:
            fh.write(SVD)

    def test_interrupts_and_register_attributes(self):
        name, data = svd_to_json.extract_single(self.svd, "USART1")
        self.assertEqual(name, "USART1")
        self.assertEqual(data["interrupts"], [
            {"name": "USART1_IRQn", "value": 37, "desc": "USART1 global"}])
        sr = data["registers"]["SR"]
        self.assertEqual(sr["size"], "16")
        self.assertEqual(sr["access"], "read-only")
        self.assertEqual(sr["reset"], "0xC0")
        self.assertNotIn("NOOFFSET", data["registers"])

    def test_human_periph_output(self):
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["svd_to_json.py", "--svd", self.svd, "--periph", "USART1"]
        try:
            with redirect_stdout(out):
                svd_to_json.main()
        finally:
            sys.argv = old
        text = out.getvalue()
        self.assertIn("=== USART1 ===", text)
        self.assertIn("Interrupts:", text)
        self.assertIn("Registers (1):", text)
        self.assertIn("bit 7: TXE", text)
        self.assertIn("enum: EMPTY", text)


if __name__ == "__main__":
    unittest.main()
