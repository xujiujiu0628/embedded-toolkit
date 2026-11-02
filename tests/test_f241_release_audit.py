r"""F-241: release_audit 的 approve 回填与 main 路由补测。

## 覆盖对象

`scripts/release_audit.py` 此前 78% 覆盖（2026-11-02 实测）：`approve_record`
的四种前置拒绝/幂等/成功回填，以及 `main()` 的互斥参数、缺记录与 JSON 输出
未执行（既有用例走子进程，coverage 不追踪）。

## 夹具

临时 `.workbench/releases/<tag>.json`；`file_lock` / `audit_record` /
`save_json_file` / `now_iso` 模块引用替换，不碰真实锁与 git。
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

import release_audit  # noqa: E402


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *_x):
        return False


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["release_audit.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = release_audit.main()
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class ApproveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = self.tmp.name
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        self.rec = os.path.join(self.ws, ".workbench", "releases", "v1.json")

    def _write(self, payload):
        with open(self.rec, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _approve(self, audit=None, saved=None):
        with mock.patch.object(release_audit, "file_lock", return_value=_Lock()), \
                mock.patch.object(release_audit, "audit_record",
                                  return_value=audit or {"verdict": "clean", "checks": []}), \
                mock.patch.object(release_audit, "save_json_file",
                                  side_effect=lambda p, d: (saved.append(d) if saved is not None else None)), \
                mock.patch.object(release_audit, "now_iso", return_value="2026-11-02T00:00:00+08:00"):
            return release_audit.approve_record(self.ws, "v1")

    def test_unparseable_record_rejected(self):
        with open(self.rec, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        result = self._approve()
        self.assertFalse(result["ok"])
        self.assertIn("不可解析", result["error"])

    def test_audit_failure_rejected(self):
        self._write({"evidence": "hardware_validated"})
        audit = {"verdict": "failed", "checks": [
            {"id": "R2", "status": "fail", "detail": "hash mismatch"}]}
        result = self._approve(audit=audit)
        self.assertFalse(result["ok"])
        self.assertIn("R2", result["error"])

    def test_already_approved_is_idempotent(self):
        self._write({"evidence": release_audit.EVIDENCE_APPROVED,
                     "production_approved_at": "t"})
        result = self._approve()
        self.assertTrue(result["ok"])
        self.assertIn("幂等", result["note"])

    def test_non_hardware_evidence_rejected(self):
        self._write({"evidence": "simulation_validated"})
        result = self._approve()
        self.assertFalse(result["ok"])
        self.assertIn("hardware_validated", result["error"])

    def test_success_rewrites_record_with_trace(self):
        self._write({"evidence": "hardware_validated", "fidelity_boundaries": []})
        saved = []
        result = self._approve(saved=saved)
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"], release_audit.EVIDENCE_APPROVED)
        self.assertEqual(saved[0]["evidence"], release_audit.EVIDENCE_APPROVED)
        self.assertEqual(saved[0]["production_approved_at"], "2026-11-02T00:00:00+08:00")
        self.assertTrue(any("production_approved" in b
                            for b in saved[0]["fidelity_boundaries"]))


class MainRouteTests(unittest.TestCase):
    def test_missing_project_returns_two(self):
        with mock.patch.object(release_audit, "find_project_root", return_value=None):
            rc, _, err = _run([])
        self.assertEqual(rc, 2)
        self.assertIn("未找到工程根", err)

    def test_approve_conflicts_with_tag(self):
        with tempfile.TemporaryDirectory() as ws:
            rc, _, err = _run(["--project", ws, "--approve", "v1", "--tag", "v1"])
        self.assertEqual(rc, 2)
        self.assertIn("互斥", err)

    def test_neither_tag_nor_all_returns_two(self):
        with tempfile.TemporaryDirectory() as ws:
            rc, _, err = _run(["--project", ws])
        self.assertEqual(rc, 2)
        self.assertIn("需 --tag", err)

    def test_approve_failure_exit_one(self):
        with tempfile.TemporaryDirectory() as ws:
            with mock.patch.object(release_audit, "approve_record",
                                   return_value={"ok": False, "error": "nope"}):
                rc, _, err = _run(["--project", ws, "--approve", "v1"])
        self.assertEqual(rc, 1)
        self.assertIn("nope", err)

    def test_approve_success_json(self):
        with tempfile.TemporaryDirectory() as ws:
            with mock.patch.object(release_audit, "approve_record",
                                   return_value={"ok": True, "tag": "v1",
                                                 "evidence": "production_approved"}):
                rc, out, _ = _run(["--project", ws, "--approve", "v1", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["tag"], "v1")


if __name__ == "__main__":
    unittest.main()
