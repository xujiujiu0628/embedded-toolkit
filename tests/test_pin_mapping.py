r"""pin-mapping 载入钉 (WB-20260927-01 / F-193, F-189 报告 §3 提案落地)。

`data/pin-mapping-f103.json` 是引脚映射的入册处——1:N 数据不进 arch-facts
(F-189 报告 §3.2 论证: 1:N 对 1:1 结构冲突 / F-186 教训 / 消费方不同)。
本钉三面, 独立成测 (简报 T2 批准), 不并入 arch-facts 钉:

  1. **结构钉**    顶层块 ∈ {_meta} ∪ 外设名集 (对账常量键集);
                   每脚条目键集恰为 {function, column, source};
                   column ∈ {main, alternate, additional} 封闭集;
  2. **source 前缀钉**  只认 web:DS5319 / web:DS5792, 全形
                   `web:DS<号>:§<节>:Table <表>:p<页>`, 缺/歪必红
                   (F-199 改名: DS5318 系文档号误记——F-193 T3 已证
                   高密度册实为 DS5792/stm32f103rc.pdf Rev 13; 两号
                   今日均零行入册, 纯语义更正零数据迁移, GAP-F-21①);
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
# F-199 (WB-20260927-07 T2, GAP-F-21① 收口): DS5318 系文档号误记
# (F-193 T3 实证高密度册自标识 = DS5792), 改名纯语义更正零数据迁移;
# 5318→5792 有回滚语义钉 (set 断言), 擅自回滚即红。
_ALLOWED_DS = ("5319", "5792")
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


def _pins_crosscheck(mapping, rel):
    """两档互证比对环 (F-199 T3): 对 X ∈ pin-mapping 外设块 ∩
    ref.json._relationships 键 且 X 带 pins 边者, rel.pins 的
    {"P"+port+str(pin)} 集必须 == pin-mapping 脚键集——两档各自演化
    (给 CAN 补 rel 边 / 给 rel 外设入册引脚行) 时劈叉在此必红
    (F-191 类级互证防线同族)。纯函数: 不读盘不打印, 供双态自证;
    返回劈叉清单 [(外设, mapping 独有脚, rel 独有脚)] (空=一致)。"""
    conflicts = []
    for name in sorted(set(mapping) & set(rel)):
        if name == "_meta":
            continue
        block = rel[name]
        pins_edge = block.get("pins") if isinstance(block, dict) else None
        if not isinstance(pins_edge, dict) or not pins_edge:
            continue
        rel_pins = {"P" + str(sig["port"]) + str(sig["pin"])
                    for sig in pins_edge.values()
                    if isinstance(sig, dict) and "port" in sig
                    and "pin" in sig}
        map_pins = set(mapping[name])
        if rel_pins != map_pins:
            conflicts.append((name, sorted(map_pins - rel_pins),
                              sorted(rel_pins - map_pins)))
    return conflicts


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

    def test_allowed_ds_is_f199_renamed_closed_set(self):
        """F-199 语义钉 (防回滚, GAP-F-21①): 前缀封闭集 = {DS5319,
        DS5792}。DS5318 系文档号误记 (F-193 T3 实证), 回滚即红;
        未来真实扩集 = 钉面变更另单。"""
        self.assertEqual(set(_ALLOWED_DS), {"5319", "5792"})

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


class PinMappingRelCrossCheckTests(_LandedMixin, unittest.TestCase):
    """两档互证钉 (F-199 T3): pin-mapping 脚集 vs ref.json rel.pins。

    **诚实披露**: 今日交集 = ∅——pin-mapping 仅 CAN, 而 CAN 在
    _relationships 无键 (更无 pins 边); rel.pins 的 12 外设
    (ADC1/I2C1/I2C2/SPI1/SPI2/TIM1-4/USART1-3) 无一入册
    pin-mapping → 本钉今日恒真绿, 禁以空集为由 skip。它的价值在
    未来: 任何人给 CAN 补 rel.pins 边、或给既有 rel 外设 (如
    USART1) 入册引脚行时, 两档劈叉必红。有效性由双态自证替代红态
    (简报②): 一致/劈叉两组自建样本喂同一比对环, 验绿/红两态
    (不动真档)。
    """

    REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")

    def test_real_docs_crosscheck_clean(self):
        with open(self.REF_PATH, encoding="utf-8") as f:
            rel = json.load(f).get("_relationships", {})
        conflicts = _pins_crosscheck(self.doc, rel)
        self.assertEqual(
            conflicts, [],
            "pin-mapping 与 ref.json rel.pins 劈叉 (外设, mapping 独有, "
            "rel 独有): " + str(conflicts))

    def test_selfproof_intersect_is_empty_today(self):
        """恒真绿前提的显式披露: 今日真档交集确为空 (钉在位但无咬合
        对象); 若未来交集非空, 本断言提示重审互证语义。"""
        with open(self.REF_PATH, encoding="utf-8") as f:
            rel = json.load(f).get("_relationships", {})
        landed = {k for k in self.doc if k != "_meta"}
        with_pins = {k for k, v in rel.items()
                     if isinstance(v, dict) and isinstance(v.get("pins"),
                                                           dict)
                     and v["pins"]}
        self.assertEqual(landed & with_pins, set(),
                         "两档交集已非空 — 互证钉今日起真实咬合, "
                         "恒真绿披露语句需随数据面更新")

    def test_selfproof_consistent_sample_green(self):
        mapping = {"CAN": {
            "PA11": {"function": "CAN_RX", "column": "alternate",
                     "source": "web:DS5319:§3:Table 5:p31"},
            "PA12": {"function": "CAN_TX", "column": "alternate",
                     "source": "web:DS5319:§3:Table 5:p31"}}}
        rel = {"CAN": {"pins": {
            "RX": {"port": "A", "pin": 11, "mode": "AF_PP"},
            "TX": {"port": "A", "pin": 12, "mode": "AF_PP"}}}}
        self.assertEqual(_pins_crosscheck(mapping, rel), [])

    def test_selfproof_split_sample_red(self):
        """劈叉样本喂真比对环必咬 (方向可辨): rel 独有脚在清单第三位。"""
        mapping = {"USART1": {
            "PA9": {"function": "USART1_TX", "column": "alternate",
                    "source": "web:DS5319:§3:Table 5:p31"}}}
        rel = {"USART1": {"pins": {
            "TX": {"port": "A", "pin": 9, "mode": "AF_PP"},
            "RX": {"port": "A", "pin": 10, "mode": "AF_PP"}}}}
        conflicts = _pins_crosscheck(mapping, rel)
        self.assertEqual(len(conflicts), 1, "劈叉样本必须被咬住")
        name, only_in_mapping, only_in_rel = conflicts[0]
        self.assertEqual(name, "USART1")
        self.assertEqual(only_in_mapping, [])
        self.assertEqual(only_in_rel, ["PA10"])


if __name__ == "__main__":
    unittest.main()
