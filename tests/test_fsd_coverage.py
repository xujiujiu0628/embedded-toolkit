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

    def _items(self, *ids):
        # F-114/H-2: diff 消费 normalize 后的条目对象 (含 desc/forbidden)
        return [{"id": i, "desc": f"d-{i}", "forbidden": False} for i in ids]

    def test_all_green(self):
        e, w, rows = fsd_coverage.diff(self._reqs("FR-A-01", "FR-B-02"),
                                       self._items("FR-A-01", "FR-B-02"), {})
        self.assertEqual((e, w), ([], []))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["asserted"] for r in rows))

    def test_c1_orphan_assertion(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"),
                                    self._items("FR-A-01", "FR-BOOT-99"), {})
        self.assertTrue(any(x.startswith("C1") and "FR-BOOT-99" in x for x in e))

    def test_c1_orphan_not_waivable(self):
        # 豁免只服务 C2 欠账; 孤儿断言配豁免 → C1+C3 双响 (F-114/M-6 立场钉)
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"),
                                    self._items("FR-A-01", "FR-X-77"),
                                    {"FR-X-77": {"id": "FR-X-77",
                                                 "reason": "r", "evidence": "e"}})
        self.assertTrue(any(x.startswith("C1") for x in e))
        self.assertTrue(any(x.startswith("C3") for x in e))

    def test_c2_requirement_without_assertion(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01", "FR-PWR-01"),
                                    self._items("FR-A-01"), {})
        self.assertTrue(any(x.startswith("C2") and "FR-PWR-01" in x for x in e))

    def test_nfr_without_assertion_is_warning_not_error(self):
        # 首跑实证修正: NFR (性能/构建类) 无断言 → WARNING, 不制造假红
        e, w, _ = fsd_coverage.diff(self._reqs("FR-A-01", "NFR-01"),
                                    self._items("FR-A-01"), {})
        self.assertEqual(e, [])
        self.assertTrue(any("NFR-01" in x for x in w))

    def test_c2_waived_covers(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01", "FR-PWR-01"),
                                    self._items("FR-A-01"),
                                    {"FR-PWR-01": {"id": "FR-PWR-01",
                                                   "reason": "bench-manual",
                                                   "evidence": "docs/FSD.md"}})
        self.assertEqual(e, [])

    def test_c3_waiver_without_reason(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"), [],
                                    {"FR-A-01": {"id": "FR-A-01",
                                                 "evidence": "e"}})
        self.assertTrue(any(x.startswith("C3") and "reason" in x for x in e))

    def test_c3_waiver_without_evidence(self):
        # F-114/M-2: evidence 必填 (spec C3"证据指向"兑现)
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"), [],
                                    {"FR-A-01": {"id": "FR-A-01", "reason": "r"}})
        self.assertTrue(any(x.startswith("C3") and "evidence" in x for x in e))

    def test_c3_orphan_waiver(self):
        e, _, _ = fsd_coverage.diff(self._reqs("FR-A-01"),
                                    self._items("FR-A-01"),
                                    {"FR-GONE-09": {"id": "FR-GONE-09",
                                                    "reason": "x",
                                                    "evidence": "e"}})
        self.assertTrue(any(x.startswith("C3") and "FR-GONE-09" in x for x in e))

    def test_table_rows_cover_all_fsd(self):
        _, _, rows = fsd_coverage.diff(self._reqs("FR-A-01", "FR-B-02"),
                                       self._items("FR-A-01"), {})
        self.assertEqual([r["id"] for r in rows], ["FR-A-01", "FR-B-02"])
        self.assertEqual(rows[0]["asserted"], True)
        self.assertEqual(rows[1]["asserted"], False)
        self.assertEqual(rows[0]["exp_desc"], "d-FR-A-01")   # H-2 双侧并排
        self.assertEqual(rows[1]["exp_desc"], "—")

    def test_table_includes_orphan_rows(self):
        # F-114/H-2: 孤儿断言成行——恰恰是最需要过目语义的对象
        _, _, rows = fsd_coverage.diff(self._reqs("FR-A-01"),
                                       self._items("FR-A-01", "FR-BOOT-99"), {})
        orphan = [r for r in rows if r.get("orphan")]
        self.assertEqual([r["id"] for r in orphan], ["FR-BOOT-99"])
        self.assertEqual(orphan[0]["fsd_title"], "—")

    def test_table_forbidden_flag_column(self):
        # F-112 联动: 对照表含"负断言有无"列 (spec A2 §9.5)
        items = [{"id": "FR-A-01", "desc": "d", "forbidden": True}]
        _, _, rows = fsd_coverage.diff(self._reqs("FR-A-01"), items, {})
        self.assertTrue(rows[0]["forbidden"])


class LoadWaivedTests(unittest.TestCase):
    def test_missing_key_tolerated(self):
        # 旧清单无 waived 顶层键 → 空豁免, 不炸 (向后兼容钉)
        self.assertEqual(fsd_coverage.load_waived({"expectations": []}), {})
        self.assertEqual(fsd_coverage.load_waived(None), {})

    def test_validate_waived_illegal_entries_are_errors_not_swallowed(self):
        # F-114/M-2: 损坏豁免必须响 (原 load_waived 静默吞 = 禁止行为)
        errs, waived = fsd_coverage.validate_waived(
            {"waived": ["str-junk", {"reason": "no id"},
                        {"id": "FR-A-01", "reason": "r", "evidence": "e"},
                        {"id": "FR-A-01", "reason": "dup"}]})
        self.assertTrue(any(e.startswith("C3") for e in errs))
        self.assertTrue(any("非空 id" in e for e in errs))
        self.assertEqual(list(waived.keys()), ["FR-A-01"])   # 合法项保留

    def test_validate_waived_non_list(self):
        errs, _ = fsd_coverage.validate_waived({"waived": "nope"})
        self.assertTrue(any(e.startswith("C3") for e in errs))


class NormalizeExpectationsTests(unittest.TestCase):
    """F-114/H-1: 损坏清单结构化报 C0, 不裸崩。"""

    def test_top_level_array(self):
        # 位置参数面 manifest 顶层为数组 → reconcile 报 C0 不崩 (F-114/H-1)
        r = fsd_coverage.reconcile("### FR-A-01：t", [{"id": "A"}])
        self.assertEqual(r["verdict"], "error")
        self.assertTrue(any(e.startswith("C0") for e in r["errors"]))

    def test_missing_id_entry_c0(self):
        errs, items = fsd_coverage.normalize_expectations(
            {"expectations": [{"desc": "no id"}, {"id": "FR-A", "desc": "d"}]})
        self.assertTrue(any(e.startswith("C0") for e in errs))
        self.assertEqual([i["id"] for i in items], ["FR-A"])

    def test_empty_array_c0(self):
        errs, _ = fsd_coverage.normalize_expectations({"expectations": []})
        self.assertTrue(any(e.startswith("C0") for e in errs))


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

    def test_broken_manifest_is_error_not_traceback(self):
        # F-114/H-1 三探针钉: 坏 JSON / 顶层数组 / 条目缺 id
        self._write("docs/FSD.md", FSD_BASIC)
        self._write(".workbench/expectations.json", "{not json")
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["verdict"], "error")
        self.assertTrue(any(e.startswith("C0") for e in r["errors"]))
        self._write(".workbench/expectations.json", json.dumps(
            {"expectations": [{"desc": "缺 id"}]}))
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertTrue(any(e.startswith("C0") for e in r["errors"]))
        self._write(".workbench/expectations.json", '[{"id": "FR-SYS-01"}]')
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["verdict"], "error")

    def test_fsd_path_config_override(self):
        # F-114/M-1: config.json fsd_path 字段覆盖默认路径
        self._write("docs/SPEC.md", FSD_BASIC)
        self._write(".workbench/config.json", '{"fsd_path": "docs/SPEC.md"}')
        self._write(".workbench/expectations.json", json.dumps(
            {"expectations": [{"id": i, "desc": "d", "texts": ["x"]}
                              for i in ("FR-SYS-01", "FR-KEY-02", "FR-PWR-01",
                                        "FR-TITLELESS-99", "NFR-01")]}))
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertIn(r["verdict"], ("clean", "warn"), r["errors"])
        self.assertEqual(r["counts"]["fsd"], 5)

    def test_counts_field(self):
        self._write("docs/FSD.md", FSD_BASIC)
        self._write(".workbench/expectations.json", json.dumps(
            {"expectations": [{"id": "FR-SYS-01", "desc": "d", "texts": ["x"]}],
             "waived": [{"id": "FR-KEY-02", "reason": "manual",
                         "evidence": "e"},
                        {"id": "FR-PWR-01", "reason": "bench",
                         "evidence": "e"},
                        {"id": "FR-TITLELESS-99", "reason": "legacy",
                         "evidence": "e"},
                        {"id": "NFR-01", "reason": "n/a", "evidence": "e"}]}))
        r = fsd_coverage.run_coverage(self.tmp)
        self.assertEqual(r["counts"], {"fsd": 5, "assertions": 1, "waived": 4})
        self.assertEqual(r["verdict"], "clean", r["errors"])


if __name__ == "__main__":
    unittest.main()
