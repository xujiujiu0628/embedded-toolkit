import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (import 期读 machine.json, 本机存在)


def _write_manifest(ws, expectations):
    wb = os.path.join(ws, ".workbench")
    os.makedirs(wb, exist_ok=True)
    with open(os.path.join(wb, "expectations.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "expectations": expectations}, f,
                  ensure_ascii=False)


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
