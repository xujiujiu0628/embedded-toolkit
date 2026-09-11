"""fsd_coverage 回归 (F-113, spec 2026-09-11-fsd-coverage-reconciler §7).

纯函数面 (parse_fsd / diff / load_waived) + run_coverage 工程合成 fixture。
C1/C2/C3 三判各正反钉 + 解析边界 (围栏/全半角冒号) + 旧清单无 waived 宽容钉。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import fsd_coverage  # noqa: E402

FSD_BASIC = """
# demo — FSD
## 3. 功能需求
### FR-SYS-01：启动横幅
- 描述: boot
### FR-KEY-02：长短按识别
### FR-PWR-01：关屏实现
### FR-TITLELESS-99：
## 4. 非功能需求
### NFR-01：性能
"""


class ParseFsdTests(unittest.TestCase):
    def test_ids_and_titles(self):
        reqs = fsd_coverage.parse_fsd(FSD_BASIC)
        self.assertEqual([r["id"] for r in reqs],
                         ["FR-SYS-01", "FR-KEY-02", "FR-PWR-01",
                          "FR-TITLELESS-99", "NFR-01"])
        self.assertEqual(reqs[0]["title"], "启动横幅")
        self.assertEqual(reqs[3]["title"], "")   # 无冒号 → 不匹配 (如实空)

    def test_halfwidth_colon_and_hash2(self):
        reqs = fsd_coverage.parse_fsd("## FR-A-01: x\n#### FR-B-02：y")
        self.assertEqual([r["id"] for r in reqs], ["FR-A-01", "FR-B-02"])

    def test_code_fence_skipped(self):
        # 模板 §4 YAML 示例块内的 id: FR-UART-08 与标题样行不得入账
        md = "```yaml\nid: FR-UART-08\n### FR-FAKE-01：围栏内假需求\n```\n### FR-REAL-01：真需求"
        reqs = fsd_coverage.parse_fsd(md)
        self.assertEqual([r["id"] for r in reqs], ["FR-REAL-01"])

    def test_inline_mention_not_matched(self):
        # 行中提及 (非标题行) 不算需求
        self.assertEqual(fsd_coverage.parse_fsd("见 FR-SYS-01 的描述。"), [])

    def test_dup_id_takes_first(self):
        reqs = fsd_coverage.parse_fsd("### FR-A-01：一\n### FR-A-01：二")
        self.assertEqual(len(reqs), 1)


class DiffTests(unittest.TestCase):
    def _reqs(self, *ids):
        return [{"id": i, "title": i} for i in ids]

    def test_all_green(self):
        e, w, rows = fsd_coverage.diff(self._reqs("FR-A-01", "FR-B-02"),
                                       ["FR-A-01", "FR-B-02"], {})
        self.assertEqual((e, w), ([], []))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["asserted"] for r in rows))

    def test_c1_orphan_assertion(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"),
                                    ["FR-A-01", "FR-BOOT-99"], {})
        self.assertTrue(any(x.startswith("C1") and "FR-BOOT-99" in x for x in e))

    def test_c2_requirement_without_assertion(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01", "FR-PWR-01"),
                                    ["FR-A-01"], {})
        self.assertTrue(any(x.startswith("C2") and "FR-PWR-01" in x for x in e))

    def test_nfr_without_assertion_is_warning_not_error(self):
        # 首跑实证修正: NFR (性能/构建类) 无断言 → WARNING, 不制造假红
        e, w, _ = fsd_coverage.diff(self._reqs("FR-A-01", "NFR-01"),
                                    ["FR-A-01"], {})
        self.assertEqual(e, [])
        self.assertTrue(any("NFR-01" in x for x in w))

    def test_c2_waived_covers(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01", "FR-PWR-01"),
                                    ["FR-A-01"],
                                    {"FR-PWR-01": {"id": "FR-PWR-01",
                                                   "reason": "bench-manual"}})
        self.assertEqual(e, [])

    def test_c3_waiver_without_reason(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"), [],
                                    {"FR-A-01": {"id": "FR-A-01"}})
        self.assertTrue(any(x.startswith("C3") and "reason" in x for x in e))

    def test_c3_orphan_waiver(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"), ["FR-A-01"],
                                    {"FR-GONE-09": {"id": "FR-GONE-09",
                                                    "reason": "x"}})
        self.assertTrue(any(x.startswith("C3") and "FR-GONE-09" in x for x in e))

    def test_xfail_counts_as_assertion(self):
        # xfail 是已建断言 (欠条), 不触发 C2 —— diff 只看 id 在场, 语义与
        # expectations loader 一致
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"), ["FR-A-01"], {})
        self.assertEqual(e, [])

    def test_table_rows_cover_all_fsd(self):
        _, _, rows = fsd_coverage.diff(self._reqs("FR-A-01", "FR-B-02"),
                                       ["FR-A-01"], {})
        self.assertEqual([r["id"] for r in rows], ["FR-A-01", "FR-B-02"])
        self.assertEqual(rows[0]["asserted"], True)
        self.assertEqual(rows[1]["asserted"], False)


class LoadWaivedTests(unittest.TestCase):
    def test_missing_key_tolerated(self):
        # 旧清单无 waived 顶层键 → 空豁免, 不炸 (向后兼容钉)
        self.assertEqual(fsd_coverage.load_waived({"expectations": []}), {})
        self.assertEqual(fsd_coverage.load_waived(None), {})

    def test_malformed_entries_skipped(self):
        w = fsd_coverage.load_waived({"waived": ["str-junk",
                                                 {"reason": "no id"},
                                                 {"id": "FR-A-01",
                                                  "reason": "r"}]})
        self.assertEqual(list(w.keys()), ["FR-A-01"])


class RunCoverageProjectTests(unittest.TestCase):
    """合成工程目录端到端 (tempfile, 不触现役工程)。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "docs"))
        os.makedirs(os.path.join(self.tmp, ".workbench"))

    def _write(self, rel, text):
        with open(os.path.join(self.tmp, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def test_green_project(self):
        self._write("docs/FSD.md", FSD_BASIC)
        self._write(".workbench/expectations.json", json.dumps(
            {"expectations": [{"id": i, "desc": "d", "texts": ["x"]}
                              for i in ("FR-SYS-01", "FR-KEY-02",
                                        "FR-PWR-01", "FR-TITLELESS-99",
                                        "NFR-01")]},
            ensure_ascii=False))
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["verdict"], "clean", r["errors"])

    def test_missing_files_skipped_not_error(self):
        # 存量工程无 FSD/无 manifest = 无对账面 → SKIPPED (谎红会让
        # HANDOFF 秒检对 legacy 工程不可用), 但 warnings 如实记
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["verdict"], "skipped")
        self.assertEqual(r["errors"], [])
        self.assertTrue(r["warnings"])

    def test_counts_field(self):
        self._write("docs/FSD.md", FSD_BASIC)
        self._write(".workbench/expectations.json", json.dumps(
            {"expectations": [{"id": "FR-SYS-01", "desc": "d", "texts": ["x"]}],
             "waived": [{"id": "FR-KEY-02", "reason": "manual"},
                        {"id": "FR-PWR-01", "reason": "bench"},
                        {"id": "FR-TITLELESS-99", "reason": "legacy"},
                        {"id": "NFR-01", "reason": "n/a"}]}))
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["counts"], {"fsd": 5, "assertions": 1, "waived": 4})
        self.assertEqual(r["verdict"], "clean", r["errors"])


if __name__ == "__main__":
    unittest.main()
