r"""pin-mapping 载入钉 (WB-20260927-01 / F-193, F-189 报告 §3 提案落地)。

`data/pin-mapping-f103.json` 是引脚映射的入册处——1:N 数据不进 arch-facts
(F-189 报告 §3.2 论证: 1:N 对 1:1 结构冲突 / F-186 教训 / 消费方不同)。
本钉三面, 独立成测 (简报 T2 批准), 不并入 arch-facts 钉:

  1. **结构钉**    顶层块 ∈ {_meta} ∪ 外设名集 (对账常量键集);
                   每脚条目键集恰为 {function, column, source};
                   column ∈ {main, alternate, additional} 封闭集;
  2. **source 前缀钉**  只认 web:DS5319 / web:DS5318, 全形
                   `web:DS<号>:§<节>:Table <表>:p<页>`, 缺/歪必红;
  3. **行数完备钉**  (防挑选性入册, 提案核心) 每外设脚行集必须与
                   WB-20260925-03 报告引文表全等——引文对账常量
                   (外设→行数→sha256 行集合指纹) 内嵌于本文件:
                   新增行不带引文=红 / 删行不动常量=红 / 列位或出处篡改=指纹红。

指纹口径: sha256("\n".join(sorted("脚|功能|列位|source")))——canonical 行序
= sorted(), 分隔符 "|"; 常量取自报告引文 (独立于被检文件, 防循环自证)。

打桩纪律: 本文件零 mock/patch (纯数据断言), 不触 test_stub_ratchet 判据面。
"""
import hashlib
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from wb_common import TOOLKIT_ROOT  # noqa: E402

MAPPING_PATH = os.path.join(TOOLKIT_ROOT, "data", "pin-mapping-f103.json")

_COLUMNS = ("main", "alternate", "additional")
_SOURCE_RE = re.compile(r"web:DS(\d+):§(\d+):Table (\d+):p(\d+)")
_ALLOWED_DS = ("5319", "5318")
_META_REQUIRED = ("version", "chip", "package", "source_types", "policy",
                  "applicability")

# 引文对账常量 (WB-20260925-03 报告 §2.4 四行; 页位/节号按 DS5319 Rev 20 订正,
# 见 WB-20260927-01 报告 §2)。canonical 行 (sorted 后 join "\n") 即:
#   PA11|CAN_RX|alternate|web:DS5319:§3:Table 5:p31
#   PA12|CAN_TX|alternate|web:DS5319:§3:Table 5:p31
#   PB8|CAN_RX|additional|web:DS5319:§3:Table 5:p33
#   PB9|CAN_TX|additional|web:DS5319:§3:Table 5:p33
QUOTE_LEDGER = {
    "CAN": {
        "table": "DS5319 §3 Table 5 (STM32F103x8/xB pin definitions) p28-33",
        "rows": 4,
        "fingerprint": "7cdba9304de9476b472bb9548947a6ff810e170845a54d2434bd7591ff6efbe3",
    },
}


def _load():
    with open(MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)


def _canonical_rows(doc, periph):
    lines = []
    for pin, entry in doc[periph].items():
        lines.append("|".join((pin, entry["function"], entry["column"],
                               entry["source"])))
    lines.sort()
    return "\n".join(lines)


def _fingerprint(doc, periph):
    return hashlib.sha256(
        _canonical_rows(doc, periph).encode("utf-8")).hexdigest()


class _LandedMixin:
    """未落盘态 = 全红 (简报②三态首跑); 落盘后转绿。"""

    def setUp(self):
        if not os.path.isfile(MAPPING_PATH):
            self.fail("data/pin-mapping-f103.json 未落盘 (T1 数据 commit 转绿)")
        self.doc = _load()


class PinMappingMetaTests(_LandedMixin, unittest.TestCase):

    def test_meta_required_keys(self):
        meta = self.doc.get("_meta")
        self.assertIsInstance(meta, dict, "_meta 缺失")
        for key in _META_REQUIRED:
            self.assertIn(key, meta, "_meta 缺必备键: " + key)

    def test_meta_chip_and_package(self):
        meta = self.doc["_meta"]
        self.assertEqual(meta["chip"], "STM32F103C8T6")
        self.assertEqual(meta["package"], "LQFP48", "封装切片锁定漂移")

    def test_meta_source_types_registered(self):
        self.assertEqual(
            self.doc["_meta"]["source_types"],
            ["web:DS5319:§3:Table 5:<页>"],
            "source_types 未按型登记 (web:DS5319:§<节>:Table <表>:<页> 族)")

    def test_meta_applicability_locks_lqfp48_slice(self):
        note = self.doc["_meta"]["applicability"]
        self.assertIn("LQFP48", note, "适用范围未声明 LQFP48 封装切片")
        self.assertIn("另单", note, "适用范围未声明多封装维度=另单提案")


class PinMappingStructureTests(_LandedMixin, unittest.TestCase):

    def test_top_level_blocks_confined(self):
        unknown = sorted(set(self.doc) - {"_meta"} - set(QUOTE_LEDGER))
        self.assertEqual(unknown, [],
                         "顶层块越出 {_meta}∪对账常量外设集: "
                         + str(unknown))
        missing = sorted(set(QUOTE_LEDGER) - set(self.doc))
        self.assertEqual(missing, [],
                         "对账常量外设缺块: " + str(missing))

    def test_pin_entry_schema(self):
        for periph, spec in QUOTE_LEDGER.items():
            block = self.doc.get(periph, {})
            self.assertIsInstance(block, dict)
            self.assertEqual(len(block), spec["rows"],
                             periph + " 脚行数 != 对账常量")
            for pin, entry in block.items():
                self.assertIsInstance(entry, dict,
                                      periph + "." + pin + " 条目非对象")
                self.assertEqual(set(entry), {"function", "column", "source"},
                                 periph + "." + pin
                                 + " 键集漂移 (提案 schema 恰三键)")
                self.assertIn(entry["column"], _COLUMNS,
                              periph + "." + pin + " column 越出封闭集: "
                              + str(entry.get("column")))
                for key in ("function", "source"):
                    self.assertIsInstance(entry.get(key), str,
                                          periph + "." + pin + "." + key
                                          + " 非字符串")


class PinMappingSourceDisciplineTests(_LandedMixin, unittest.TestCase):
    """『数据无出处不入册』的引脚映射版: 只认官方 DS 锚。"""

    def test_every_pin_source_matches_ds_form(self):
        for periph, block in self.doc.items():
            if periph == "_meta":
                continue
            for pin, entry in block.items():
                m = _SOURCE_RE.fullmatch(entry.get("source") or "")
                self.assertIsNotNone(
                    m,
                    "{0}.{1} source 不合全形 "
                    "web:DS<号>:§<节>:Table <表>:p<页>: {2!r}".format(
                        periph, pin, entry.get("source")))
                self.assertIn(m.group(1), _ALLOWED_DS,
                              periph + "." + pin + " DS 号越出封闭集: DS"
                              + m.group(1))


class PinMappingQuoteLedgerTests(_LandedMixin, unittest.TestCase):
    """行数完备钉: 行集与报告引文表全等 (防挑选性入册)。"""

    def test_each_periph_fingerprint_matches_ledger(self):
        for periph, spec in QUOTE_LEDGER.items():
            self.assertIn(periph, self.doc)
            self.assertEqual(len(self.doc[periph]), spec["rows"],
                             periph + " 行数漂移 (对账常量="
                             + str(spec["rows"]) + ")")
            self.assertEqual(
                _fingerprint(self.doc, periph), spec["fingerprint"],
                periph + " 行集合指纹漂移——新增行不带引文 / 删行未记账 / "
                "function·column·source 被篡改, 三者必居其一")


if __name__ == "__main__":
    unittest.main()
