r"""arch-facts 载入钉 (WB-20260920-05 / F-179, GAP-D-4)。

`data/stm32f103-arch-facts.json` 是 ref.json 未登记的架构常量/位域/编码表的
入册处。本钉只做四件事（不重复文件内容，避免"抄一遍自己"）：

  1. JSON 合法 + `_meta` 必备键齐；
  2. **每条入册项都带 source**，且 source 属三型之一
     （`RM0008:§…` / `CMSIS:…` / `arch-constant:…`）——"数据无出处不入册"；
  3. CRC 的 poly/init 用文件里的值跑一个独立实现的位模 2 除模型，必须重现
     **独立演算**得到的已知答案常数（WB-20260920-02 §四.1 的三个向量），
     以排除"把样例里的数抄两遍自证"（防循环自证）；
  4. 编码表/常量与现场可复核的锚点常数逐条比对（IWDG KR 三键、FLASH KEYR
     两键、PLLMUL 15 行）。

本文件消费方后续单接（简报 §2 T3）；全量回归须证明零既有断言受影响。
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from wb_common import TOOLKIT_ROOT  # noqa: E402

FACTS_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-arch-facts.json")

_SOURCE_PREFIXES = ("RM0008:", "CMSIS:", "arch-constant:")

# 独立演算的已知答案 (WB-20260920-02 §四.1；非运行被检程序所得)
CRC_VEC_EMPTY = 0xFFFFFFFF
CRC_VEC_ALL_ONES = 0x00000000
CRC_VEC_ONE_WORD = 0xA695C4AA          # 0x31323334
CRC_VEC_PAYLOAD = 0x376454AF           # 0x12345678 9ABCDEF0 0F1E2D3C 4B5A6978
CRC_PAYLOAD = [0x12345678, 0x9ABCDEF0, 0x0F1E2D3C, 0x4B5A6978]


def _load():
    with open(FACTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _walk_sources(node, out):
    if isinstance(node, dict):
        if "source" in node:
            out.append(node["source"])
        for v in node.values():
            _walk_sources(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_sources(v, out)
    return out


def _crc_model(words, poly, init_value, reflected=False):
    """位模 2 除 (MSB-first) 独立实现 —— 与被测 JSON 无共享代码。"""
    crc = init_value & 0xFFFFFFFF
    for w in words:
        crc ^= (w & 0xFFFFFFFF)
        for _ in range(32):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ poly) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


class ArchFactsMetaTests(unittest.TestCase):

    def setUp(self):
        self.doc = _load()

    def test_meta_required_keys(self):
        meta = self.doc.get("_meta")
        self.assertIsInstance(meta, dict, "_meta 缺失")
        for key in ("version", "chip", "updated", "scope", "source_types", "policy"):
            self.assertIn(key, meta, "_meta 缺必备键: " + key)
        self.assertEqual(self.doc["_meta"]["chip"], "STM32F103C8T6")

    def test_groups_present(self):
        for group in ("iwdg", "flash", "crc", "rcc_cfgr", "sdio", "dbg"):
            self.assertIn(group, self.doc, "缺分组: " + group)


class ArchFactsSourceDisciplineTests(unittest.TestCase):
    """『数据无出处不入册』的机器化版本。"""

    def setUp(self):
        self.doc = _load()

    def test_every_source_uses_a_legal_prefix(self):
        sources = _walk_sources(self.doc, [])
        self.assertGreaterEqual(len(sources), 30,
                                "带 source 的条目数骤减——文件被掏空?")
        bad = [s for s in sources
               if not isinstance(s, str) or not s.startswith(_SOURCE_PREFIXES)]
        self.assertEqual(bad, [], "source 不属于三型之一:\n" + "\n".join(map(str, bad)))

    def test_required_entries_exist_and_are_sourced(self):
        doc = self.doc
        paths = [
            ("iwdg", "kr_write_access_enable", "value", "0x5555"),
            ("iwdg", "kr_reload", "value", "0xAAAA"),
            ("iwdg", "kr_enable", "value", "0xCCCC"),
            ("flash", "keyr_fpce_key1", "value", "0x45670123"),
            ("flash", "keyr_fpce_key2", "value", "0xCDEF89AB"),
            ("crc", "polynomial", "value", "0x04C11DB7"),
            ("crc", "init_value", "value", "0xFFFFFFFF"),
            ("sdio", "power_pwrctrl_bits", "bits", "0:1"),
        ]
        for group, key, field, expect in paths:
            entry = doc[group][key]
            self.assertEqual(entry.get(field), expect,
                             "{0}.{1}.{2} != {3}".format(group, key, field, expect))
            self.assertTrue(entry.get("source"),
                            "{0}.{1} 无 source".format(group, key))

    def test_pllmul_table_geometry(self):
        table = self.doc["rcc_cfgr"]["pllmul_encoding"]
        self.assertEqual(len(table), 15, "PLLMUL 编码表不是 15 行 (×2..×16)")
        for code in sorted(table):
            m = re.fullmatch(r"0b([01]{4})", code)
            self.assertIsNotNone(m, "非 4 位二进制键: " + code)
            value = int(m.group(1), 2)
            self.assertEqual(table[code]["multiplier"], value + 2,
                             code + " → ×{0}，与 RM 家族 (code+2) 不符".format(
                                 table[code]["multiplier"]))
            self.assertTrue(table[code].get("source"), code + " 无 source")
        self.assertEqual(table["0b0111"]["multiplier"], 9,
                         "简报指定 0111→×9 的锚点移位")


class ArchFactsCrcCrossCheckTests(unittest.TestCase):
    """防循环自证：用文件里的 poly/init 跑独立模型，必须重现独立演算常数。"""

    def setUp(self):
        doc = _load()
        crc = doc["crc"]
        self.poly = int(crc["polynomial"]["value"], 16)
        self.init = int(crc["init_value"]["value"], 16)
        self.reflected = bool(crc["polynomial"].get("reflection", False))

    def test_bit_order_declared_msb_first_unreflected(self):
        self.assertEqual(self.doc_bit_order(), "MSB-first")
        self.assertFalse(self.reflected, "ST F1 硬件 CRC 非反射族")

    def doc_bit_order(self):
        return _load()["crc"]["polynomial"]["bit_order"]

    def test_known_answer_vectors_reproduced(self):
        self.assertEqual(self.poly, 0x04C11DB7)
        self.assertEqual(self.init, 0xFFFFFFFF)
        self.assertEqual(_crc_model([], self.poly, self.init), CRC_VEC_EMPTY)
        self.assertEqual(_crc_model([0xFFFFFFFF], self.poly, self.init),
                         CRC_VEC_ALL_ONES)
        self.assertEqual(_crc_model([0x31323334], self.poly, self.init),
                         CRC_VEC_ONE_WORD)
        self.assertEqual(_crc_model(CRC_PAYLOAD, self.poly, self.init),
                         CRC_VEC_PAYLOAD)


if __name__ == "__main__":
    unittest.main()
