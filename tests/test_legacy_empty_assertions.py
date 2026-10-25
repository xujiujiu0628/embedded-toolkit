"""legacy 断言不得为空。

无 expectations.json 时, 旧路径的 expect/expect_patterns 若都为空 (且未加
--require-tgl), 任何输出都会 vacuous PASS。必须在构建/烧录之前拒绝。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class EmptyLegacyAssertionsTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"toolkit_min_version": "0.1", "builder": "gcc"}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_empty_legacy_contract_rejected_before_build(self):
        out, err = io.StringIO(), io.StringIO()
        build = mock.Mock()
        with mock.patch.object(sys, "argv",
                               ["verify.py", "--project", self.ws, "--json"]), \
                mock.patch.object(verify, "step_build", build), \
                redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                verify.main()

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("空断言", err.getvalue())
        build.assert_not_called()

    def test_verify_function_itself_rejects_empty_contract(self):
        result = verify.verify("anything", [])
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["all_expected_found"])


if __name__ == "__main__":
    unittest.main()
