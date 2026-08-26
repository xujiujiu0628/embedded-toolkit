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
