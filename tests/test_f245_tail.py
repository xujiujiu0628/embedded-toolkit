r"""F-245: 尾部模块（wb_runtime / failure_context / evidence_export / audit）补测。

## 覆盖对象

- `wb_runtime`：`save_local_config` 的损坏拒绝与新建、`normalize_path_with_base`；
- `failure_context`：timing_fail / physical_gate_failed / XPASS / missing 四种
  agent_hint；
- `evidence_export`：`render_release_summary` 的非列表字段坏型注记；
- `phase_minus_one`：`check_kb_coverage` 的 PARTIAL 分支、`load_issues` 缺失；
- `release_audit`：`main` 的 --tag/--all 文本与 JSON 出口。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import evidence_export  # noqa: E402
import failure_context  # noqa: E402
import phase_minus_one  # noqa: E402
import release_audit  # noqa: E402
import wb_runtime  # noqa: E402


class WbRuntimeTests(unittest.TestCase):
    def test_save_local_config_refuses_corrupt(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "wb.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            err = io.StringIO()
            with mock.patch.object(wb_runtime, "default_config_path",
                                   return_value=__import__("pathlib").Path(path)), \
                    redirect_stderr(err):
                result = wb_runtime.save_local_config({"a": 1})
        self.assertIsNone(result)
        self.assertIn("拒绝写回", err.getvalue())

    def test_save_local_config_creates_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "wb.json")
            with mock.patch.object(wb_runtime, "default_config_path",
                                   return_value=__import__("pathlib").Path(path)):
                result = wb_runtime.save_local_config({"a": 1})
            self.assertEqual(result, __import__("pathlib").Path(path))
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {"a": 1})

    def test_normalize_path_with_base(self):
        self.assertEqual(wb_runtime.normalize_path_with_base("", None), "")
        base = tempfile.gettempdir()
        got = wb_runtime.normalize_path_with_base("rel.txt", base)
        self.assertTrue(os.path.isabs(got))
        self.assertIn("rel.txt", got)


class FailureContextTests(unittest.TestCase):
    def _ctx(self, status, steps=None):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            os.makedirs(os.path.join(ws, ".workbench"))
            result = {"status": status, "steps": steps or {}}
            failure_context._save_failure_context(result, 1, "cap", workspace=ws)
            path = os.path.join(ws, ".workbench", "build", "last_failure.json")
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)

    def test_timing_fail_hint(self):
        ctx = self._ctx("timing_fail")
        self.assertIn("clock tree", ctx["agent_hint"])

    def test_physical_gate_failed_hint(self):
        ctx = self._ctx("physical_gate_failed")
        self.assertIn("fails closed", ctx["agent_hint"])

    def test_xpass_hint(self):
        ctx = self._ctx("fail", {"verify": {"xpass_ids": ["A"]}})
        self.assertIn("XPASS", ctx["agent_hint"])

    def test_missing_hint(self):
        ctx = self._ctx("fail", {"verify": {"missing": ["B"]}})
        self.assertIn("expected patterns missing", ctx["agent_hint"])


class EvidenceExportTests(unittest.TestCase):
    def test_bad_type_fields_noted(self):
        md = evidence_export.render_release_summary({
            "tag": "v1", "xfail_waived": "oops",
            "fidelity_boundaries": "oops", "limitations": 5,
            "results": "oops",
        })
        self.assertIn("xfail_waived", md)
        self.assertIn("fidelity_boundaries", md)
        self.assertIn("limitations", md)


class PhaseMinusOneTailTests(unittest.TestCase):
    def test_partial_coverage_status(self):
        ref = {"peripherals": {}, "_relationships": {"I2C1": {"bus": "APB1", "pins": ["PB6"]}}}
        result = phase_minus_one.check_kb_coverage("I2C1", ref)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn("pins", result["detail"])

    def test_load_issues_missing_file(self):
        with mock.patch.object(phase_minus_one, "ISSUES_PATH",
                               os.path.join(tempfile.gettempdir(), "no-issues.json")):
            self.assertEqual(phase_minus_one.load_issues(), {})


class ReleaseAuditMainTests(unittest.TestCase):
    def _run(self, argv, audit_result):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["release_audit.py", *argv]
        try:
            with mock.patch.object(release_audit, "audit_project",
                                   return_value=audit_result), \
                    redirect_stdout(out), redirect_stderr(err):
                rc = release_audit.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()

    def test_text_clean(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            rc, out, _ = self._run(
                ["--project", ws, "--tag", "v1"],
                {"project": ws, "verdict": "clean", "records": [
                    {"verdict": "clean", "tag": "v1", "checks": []}]})
        self.assertEqual(rc, 0)
        self.assertIn("[clean] v1", out)

    def test_json_failed_exit_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ws:
            rc, out, _ = self._run(
                ["--project", ws, "--all", "--json"],
                {"project": ws, "verdict": "failed", "records": []})
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["verdict"], "failed")


if __name__ == "__main__":
    unittest.main()
