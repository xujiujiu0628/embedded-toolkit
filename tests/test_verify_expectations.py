import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (F-054 后 import 期零 IO)


def _write_manifest(ws, expectations):
    wb = os.path.join(ws, ".workbench")
    os.makedirs(wb, exist_ok=True)
    with open(os.path.join(wb, "expectations.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "expectations": expectations}, f,
                  ensure_ascii=False)


class ContractHashTests(unittest.TestCase):
    """F-018: contract_hashes — 判绿所依据契约的字节级哈希"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_bytes(self, rel: str, data: bytes):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def test_manifest_mode_hashes_both(self):
        self._write_bytes(".workbench/config.json", b'{"builder": "gcc"}')
        self._write_bytes(".workbench/expectations.json", b'{"expectations": []}')
        h = verify.contract_hashes(self.tmp, has_manifest=True)
        import hashlib
        self.assertEqual(h["config_sha256"],
                         hashlib.sha256(b'{"builder": "gcc"}').hexdigest())
        self.assertEqual(h["expectations_sha256"],
                         hashlib.sha256(b'{"expectations": []}').hexdigest())

    def test_legacy_mode_omits_expectations(self):
        self._write_bytes(".workbench/config.json", b"{}")
        h = verify.contract_hashes(self.tmp, has_manifest=False)
        self.assertIn("config_sha256", h)
        self.assertNotIn("expectations_sha256", h)

    def test_empty_workspace_gives_empty(self):
        self.assertEqual(verify.contract_hashes(self.tmp, has_manifest=False), {})

    def test_hash_is_byte_sensitive(self):
        # 内容哪怕只差一个换行, 哈希必须不同 (字节级锚点的意义)
        self._write_bytes(".workbench/config.json", b'{"a": 1}')
        h1 = verify.contract_hashes(self.tmp, has_manifest=False)["config_sha256"]
        self._write_bytes(".workbench/config.json", b'{"a": 1}\n')
        h2 = verify.contract_hashes(self.tmp, has_manifest=False)["config_sha256"]
        self.assertNotEqual(h1, h2)


class LoadExpectationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_none(self):
        self.assertIsNone(verify.load_expectations(self.tmp))

    def test_valid_minimal(self):
        _write_manifest(self.tmp,
                        [{"id": "FR-A-01", "desc": "d", "texts": ["x"]}])
        exp = verify.load_expectations(self.tmp)
        self.assertEqual(exp[0]["id"], "FR-A-01")

    def test_dup_id_raises(self):
        _write_manifest(self.tmp, [
            {"id": "A", "desc": "d", "texts": ["x"]},
            {"id": "A", "desc": "d", "texts": ["y"]},
        ])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_xfail_without_reason_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "texts": ["x"], "xfail": True}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_texts_and_patterns_both_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "texts": ["x"], "patterns": ["p"]}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_neither_raises(self):
        _write_manifest(self.tmp, [{"id": "A", "desc": "d"}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_bad_capture_group_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "patterns": ["(\\d+)"],
                          "capture_group": 0}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_capture_group_with_texts_raises(self):
        # 审计 M1: 该组合会在评估期 first=None AttributeError
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "texts": ["x"],
                          "capture_group": 1}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_invalid_regex_raises(self):
        # 审计 M1: 惰性编译会把非法正则拖到烧录后才炸
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "patterns": ["["]}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_broken_json_raises_expectation_error(self):
        # 审计 M1: JSONDecodeError 不是 ExpectationError, main() 接不住
        wb = os.path.join(self.tmp, ".workbench")
        os.makedirs(wb, exist_ok=True)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_nan_bound_raises(self):
        # 审计 M1: NaN 绕过全部边界比较恒 pass
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "patterns": ["(\\d+)"],
                          "capture_group": 1, "min": float("nan")}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)


class EvaluateExpectationsTests(unittest.TestCase):
    def test_pass(self):
        ev = verify.evaluate_expectations("boot ok",
                                          [{"id": "A", "texts": ["ok"]}])
        self.assertEqual(ev["verdict"], "ok")
        self.assertEqual(ev["results"], [{"id": "A", "status": "pass"}])
        self.assertEqual(ev["xpass_ids"], [])

    def test_fail_with_detail(self):
        ev = verify.evaluate_expectations("boot", [{"id": "A", "texts": ["ok"]}])
        self.assertEqual(ev["verdict"], "fail")
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertIn("missing texts", ev["results"][0]["detail"])

    def test_xfail_keeps_suite_green(self):
        ev = verify.evaluate_expectations(
            "", [{"id": "A", "texts": ["ok"], "xfail": True}])
        self.assertEqual((ev["verdict"], ev["results"][0]["status"]),
                         ("ok", "xfail"))

    def test_xpass_is_strict_red(self):
        ev = verify.evaluate_expectations(
            "ok", [{"id": "A", "texts": ["ok"], "xfail": True}])
        self.assertEqual((ev["verdict"], ev["results"][0]["status"]),
                         ("fail", "xpass"))
        self.assertEqual(ev["xpass_ids"], ["A"])

    def test_patterns_array_all_must_hit(self):
        item = {"id": "A", "patterns": [r"\d+", r"[a-z]+"]}
        self.assertEqual(
            verify.evaluate_expectations("123", [item])["verdict"], "fail")
        self.assertEqual(
            verify.evaluate_expectations("123 abc", [item])["verdict"], "ok")

    def test_capture_group_threshold_boundary(self):
        item = {"id": "R", "patterns": [r"Hz=(\d+)"], "capture_group": 1,
                "min": 2}
        self.assertEqual(
            verify.evaluate_expectations("Hz=2", [item])["verdict"], "ok")
        self.assertEqual(
            verify.evaluate_expectations("Hz=1", [item])["verdict"], "fail")

    def test_capture_group_max_boundary(self):
        item = {"id": "R", "patterns": [r"Hz=(\d+)"], "capture_group": 1,
                "max": 9}
        self.assertEqual(
            verify.evaluate_expectations("Hz=9", [item])["verdict"], "ok")
        self.assertEqual(
            verify.evaluate_expectations("Hz=10", [item])["verdict"], "fail")

    def test_cli_rows_and_tgl(self):
        items = verify.cli_expectations([], [], require_tgl=True)
        self.assertEqual([i["id"] for i in items], ["CLI-REQUIRE-TGL"])
        ev = verify.evaluate_expectations("TGL 3 TGL 4", items)
        self.assertEqual(ev["verdict"], "ok")

    def test_verdict_fails_if_any_fail_among_xfails(self):
        exp = [{"id": "A", "texts": ["a"], "xfail": True},
               {"id": "B", "texts": ["b"]}]
        ev = verify.evaluate_expectations("a c", exp)   # A=XFAIL, B=FAIL
        self.assertEqual(ev["verdict"], "fail")


class ForbiddenAssertionTests(unittest.TestCase):
    """F-112 负断言 (spec 2026-09-11-negative-assertion-schema §2/§6)"""

    # --- 核心语义钉 ---

    def test_forbidden_hit_overrides_pass(self):
        # 正向匹配 + forbidden 命中 → FAIL (假阳性拦截点)
        item = {"id": "A", "patterns": [r"recovered in \d+s"],
                "forbidden_texts": ["watchdog reset"]}
        ev = verify.evaluate_expectations(
            "recovered in 3s", [item])
        self.assertEqual(ev["verdict"], "ok")          # 基线: 无禁止行 = PASS
        ev2 = verify.evaluate_expectations(
            "watchdog reset\nrecovered in 3s", [item])
        self.assertEqual((ev2["verdict"], ev2["results"][0]["status"]),
                         ("fail", "fail"))
        self.assertIn("forbidden hit", ev2["results"][0]["detail"])

    def test_forbidden_pattern_semantics(self):
        item = {"id": "A", "texts": ["boot ok"],
                "forbidden_patterns": [r"retry#[4-9]"]}
        self.assertEqual(
            verify.evaluate_expectations("boot ok retry#2", [item])["verdict"], "ok")
        self.assertEqual(
            verify.evaluate_expectations("boot ok retry#5", [item])["verdict"], "fail")

    def test_forbidden_beats_xpass(self):
        # §2 订则: 负断言命中 FAIL 优先于 XPASS (欠条条目撞上禁止后果也不给红转绿的豁免通道)
        item = {"id": "A", "texts": ["ok"], "xfail": True, "xfail_reason": "wip",
                "forbidden_texts": ["boom"]}
        ev = verify.evaluate_expectations("ok boom", [item])
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertEqual(ev["xpass_ids"], [])          # 不得记作落地信号

    def test_forbidden_beats_xfail(self):
        # xfail 未匹配本应绿 (XFAIL), 但禁止后果出现 → FAIL
        item = {"id": "A", "texts": ["feat"], "xfail": True, "xfail_reason": "wip",
                "forbidden_texts": ["corrupt"]}
        ev = verify.evaluate_expectations("corrupt heap", [item])
        self.assertEqual(ev["results"][0]["status"], "fail")

    def test_forbidden_without_positive_still_fail(self):
        # 正向未匹配 + forbidden 命中: 两罪并罚仍 FAIL, detail 归负断言 (先求值序)
        item = {"id": "A", "texts": ["feat"], "forbidden_texts": ["err"]}
        ev = verify.evaluate_expectations("err happened", [item])
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertIn("forbidden hit", ev["results"][0]["detail"])

    # --- 向后兼容钉 (spec §6.3) ---

    def test_old_manifest_unchanged_results(self):
        # 无 forbidden 键的旧清单: 全部行为与 master 一致 (逐字段比对固化基线)
        # F-148: evaluate 返回值新增 records 聚合键 (无 record 条目时为空数组);
        # 无新键条目的四态判定逐字段不变。
        exp = [{"id": "A", "texts": ["ok"]},
               {"id": "B", "patterns": [r"TGL (\d+)"], "capture_group": 1,
                "min": 1, "max": 10},
               {"id": "C", "texts": ["todo"], "xfail": True,
                "xfail_reason": "r"}]
        out = "ok TGL 3 not-yet"
        ev = verify.evaluate_expectations(out, exp)
        self.assertEqual(ev, {"results": [
            {"id": "A", "status": "pass"},
            {"id": "B", "status": "pass"},
            {"id": "C", "status": "xfail"}],
            "verdict": "ok", "xpass_ids": [], "records": []})

    # --- loader 校验钉 ---

    def _manifest(self, items):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        _write_manifest(tmp, items)
        return tmp

    def test_loader_empty_forbidden_raises(self):
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(
                self._manifest([{"id": "A", "desc": "d", "texts": ["x"],
                                 "forbidden_texts": []}]))

    def test_loader_bad_forbidden_regex_raises(self):
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(
                self._manifest([{"id": "A", "desc": "d", "texts": ["x"],
                                 "forbidden_patterns": ["["]}]))

    def test_loader_suicide_config_raises(self):
        # E11 同源: 同串既要求出现又禁止出现 → loader 直拦
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(
                self._manifest([{"id": "A", "desc": "d", "texts": ["x"],
                                 "forbidden_texts": ["x"]}]))

    def test_loader_valid_forbidden_passes(self):
        tmp = self._manifest([{"id": "A", "desc": "d", "texts": ["x"],
                               "forbidden_texts": ["y"]}])
        self.assertEqual(verify.load_expectations(tmp)[0]["forbidden_texts"], ["y"])
