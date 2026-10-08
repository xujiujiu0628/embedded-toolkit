r"""F-226 (WB-05 L-3 收口): SVD 位域三风格统一解析 — lsb/msb 收编 + 派生回填不再缺省 0。

病灶 (WB-05 L-3, 登记"仍在, 属另单面"):
  ① extract_fields 主路径只认 <bitRange> / <bitOffset>+<bitWidth>，
     <lsb>/<msb> 风格字段被**静默丢弃**；
  ② 基字段回填路径 (register derivedFrom) 只认 bitOffset/bitWidth 且
     找不到时**缺省 offset=0/width=1** —— bitRange/lsb-msb 风格的基字段
     被静默写成 "bit 0"（多条还会在 key "0" 上互相覆盖）：不是回填失败，
     是编造错误位域。

修复：统一 `_field_bit_key()` 三风格解析；回填路径复用同源解析，无法
解析时响亮告警 (stderr) 并跳过 —— 不产出默认位 0。

范围声明：主路径"完全无位置信息"的畸变字段维持原跳过语义（本轮不动，
见 CHANGELOG F-226 备注）。
"""
import io
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import svd_to_json  # noqa: E402


def _reg(xml):
    return ET.fromstring(xml)


class LsbMsbStyleTests(unittest.TestCase):
    """主路径: <lsb>/<msb> 风格字段必须解析（修前静默丢弃）。"""

    def test_single_bit_field(self):
        reg = _reg('<register><name>SR</name><fields>'
                   '<field><name>TXE</name><lsb>7</lsb><msb>7</msb>'
                   '<description>Tx empty</description></field>'
                   '</fields></register>')
        fields = svd_to_json.extract_fields(reg, {})
        self.assertIn("7", fields)
        self.assertEqual(fields["7"]["name"], "TXE")
        self.assertEqual(fields["7"]["desc"], "Tx empty")

    def test_multi_bit_field(self):
        reg = _reg('<register><name>CR</name><fields>'
                   '<field><name>MODE</name><lsb>4</lsb><msb>7</msb></field>'
                   '</fields></register>')
        fields = svd_to_json.extract_fields(reg, {})
        self.assertIn("4:7", fields)
        self.assertEqual(fields["4:7"]["name"], "MODE")


class DerivedBackfillTests(unittest.TestCase):
    """回填路径: 继承字段必须按真实位域落键，缺省 0 编造必须消失。"""

    def test_bitrange_base_field_inherited_at_real_position(self):
        base = _reg('<register><name>CR1</name><fields>'
                    '<field><name>MODE</name><bitRange>[7:4]</bitRange></field>'
                    '</fields></register>')
        child = _reg('<register derivedFrom="CR1"><name>CR2</name><fields>'
                     '<field><name>OWN</name><bitOffset>1</bitOffset>'
                     '<bitWidth>1</bitWidth></field>'
                     '</fields></register>')
        fields = svd_to_json.extract_fields(child, {"CR1": base})
        self.assertEqual(sorted(fields), ["1", "4:7"],
                         "bitRange 风格基字段必须落真实位域, 不得缺省 0")
        self.assertEqual(fields["4:7"]["name"], "MODE")

    def test_lsb_msb_base_field_inherited(self):
        base = _reg('<register><name>CR1</name><fields>'
                    '<field><name>EN</name><lsb>3</lsb><msb>3</msb></field>'
                    '</fields></register>')
        child = _reg('<register derivedFrom="CR1"><name>CR2</name><fields>'
                     '<field><name>X</name><bitOffset>2</bitOffset></field>'
                     '</fields></register>')
        fields = svd_to_json.extract_fields(child, {"CR1": base})
        self.assertIn("3", fields)
        self.assertEqual(fields["3"]["name"], "EN")

    def test_unresolvable_base_field_warns_and_is_skipped(self):
        base = _reg('<register><name>CR1</name><fields>'
                    '<field><name>GHOST</name></field>'
                    '</fields></register>')
        child = _reg('<register derivedFrom="CR1"><name>CR2</name><fields>'
                     '<field><name>OWN</name><bitOffset>1</bitOffset></field>'
                     '</fields></register>')
        err = io.StringIO()
        with redirect_stderr(err):
            fields = svd_to_json.extract_fields(child, {"CR1": base})
        self.assertNotIn("0", fields, "不许编造默认位 0")
        self.assertNotIn("GHOST", [f.get("name") for f in fields.values()])
        self.assertIn("GHOST", err.getvalue(), "须响亮告警, 不静默")
        self.assertIn("CR2", err.getvalue())

    def test_overridden_field_not_backfilled(self):
        # 防误伤钉: 子寄存器显式定义同名字段 → 不重复回填 (既有语义保持)
        base = _reg('<register><name>CR1</name><fields>'
                    '<field><name>MODE</name><bitRange>[7:4]</bitRange></field>'
                    '</fields></register>')
        child = _reg('<register derivedFrom="CR1"><name>CR2</name><fields>'
                     '<field><name>MODE</name><bitOffset>0</bitOffset>'
                     '<bitWidth>2</bitWidth></field>'
                     '</fields></register>')
        fields = svd_to_json.extract_fields(child, {"CR1": base})
        self.assertEqual(sorted(fields), ["0:1"])
        self.assertEqual(fields["0:1"]["name"], "MODE")


if __name__ == "__main__":
    unittest.main()
