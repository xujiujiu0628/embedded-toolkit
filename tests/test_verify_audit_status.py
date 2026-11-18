"""台账写失败留痕：verify 出口写 `audit` 块，release 据此拦发布。

## 语义

台账仍然**不改判定**（`verify.py` 的 status/verdict 一个字节不动）——但一次
"硬件动作已发生、账却没落"的运行不能当作可复核的发布证据。留痕分两处：

- `verify._attach_audit_status`：只有失败才写 `result["audit"]`
  （缺席 = 全部落盘，不需要恒真字段占位）；
- `release.run_gates` 的 G2 台账门：`audit.ok is False` 直接拦，不设豁免。

evidence 字段**不降级**：板子确实跑过，把它改写成 static 是假话，拦截
应该发生在门禁层而不是伪装证据等级。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class AppendAuditEntryTests(unittest.TestCase):
    def setUp(self):
        verify._AUDIT_FAILURES.clear()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        verify._AUDIT_FAILURES.clear()
        self.tmp.cleanup()

    def test_success_returns_true_and_writes_line(self):
        ok = verify.append_audit_entry(self.tmp.name, "manual", "flash", "ok", "cmd")
        self.assertTrue(ok)
        self.assertEqual(verify._AUDIT_FAILURES, [])
        path = os.path.join(self.tmp.name, ".workbench", "state", "audit.jsonl")
        with open(path, encoding="utf-8") as f:
            self.assertIn('"step": "flash"', f.read())

    def test_write_failure_returns_false_and_records(self):
        blocker = os.path.join(self.tmp.name, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        ok = verify.append_audit_entry(os.path.join(blocker, "sub"),
                                       "manual", "capture", "ok", "cmd")
        self.assertFalse(ok)
        self.assertEqual(len(verify._AUDIT_FAILURES), 1)
        self.assertIn("capture", verify._AUDIT_FAILURES[0])

    def test_attach_writes_block_only_on_failure(self):
        result = {}
        verify._attach_audit_status(result)
        self.assertNotIn("audit", result)

        verify._AUDIT_FAILURES.append("flash: disk full")
        verify._attach_audit_status(result)
        self.assertFalse(result["audit"]["ok"])
        self.assertIn("flash: disk full", result["audit"]["errors"])

    def test_attach_does_not_clobber_existing_block(self):
        result = {"audit": {"ok": False, "errors": ["preset"]}}
        verify._AUDIT_FAILURES.append("flash: other")
        verify._attach_audit_status(result)
        self.assertEqual(result["audit"]["errors"], ["preset"])


if __name__ == "__main__":
    unittest.main()
