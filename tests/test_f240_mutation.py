r"""F-240: mutation 的 verify 包装、输出与"还原后仍坏"分支补测。

## 覆盖对象

`scripts/mutation.py` 此前 74% 覆盖（2026-11-02 实测）：`_run_verify_cli`
的 JSON/非 JSON 两条路径、`_emit` 的文本/JSON 输出，以及
`mutate_and_run` 的"还原后 verify 自身失败"分支未执行（既有用例都走注入
runner，CLI 包装与输出层只被子进程触达）。

## 夹具

`subprocess.run` 用模块引用替换返回假进程；不启动真 verify。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import mutation  # noqa: E402


class RunVerifyCliTests(unittest.TestCase):
    def _proc(self, stdout, stderr="", rc=0):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)

    def _run_with(self, proc):
        """直接替换 mutation.subprocess（mock.patch 会被 test_stub_ratchet
        记为 B 式全局打桩）；只替换本模块命名空间里的引用，用完还原。"""
        old = mutation.subprocess
        mutation.subprocess = SimpleNamespace(run=lambda *a, **k: proc)
        try:
            return mutation._run_verify_cli("proj", 30)()
        finally:
            mutation.subprocess = old

    def test_json_output_parsed(self):
        payload = {"status": "ok", "steps": {"verify": {"results": []}}}
        got = self._run_with(self._proc(json.dumps(payload)))
        self.assertEqual(got, payload)

    def test_non_json_output_becomes_error_with_tail(self):
        got = self._run_with(self._proc("Traceback: boom\n", "stderr tail", rc=2))
        self.assertEqual(got["status"], "error")
        self.assertEqual(got["results"], [])
        self.assertIn("rc=2", got["error"])
        self.assertIn("boom", got["error"])


class EmitTests(unittest.TestCase):
    def test_ok_text_prints_summary(self):
        out = io.StringIO()
        with redirect_stdout(out):
            mutation._emit({"ok": True, "summary": "all good"}, as_json=False)
        self.assertEqual(out.getvalue().strip(), "all good")

    def test_fail_text_prefixes_fail(self):
        out = io.StringIO()
        with redirect_stdout(out):
            mutation._emit({"ok": False, "error": "boom"}, as_json=False)
        self.assertEqual(out.getvalue().strip(), "FAIL: boom")

    def test_json_output(self):
        out = io.StringIO()
        with redirect_stdout(out):
            mutation._emit({"ok": True, "summary": "s"}, as_json=True)
        self.assertEqual(json.loads(out.getvalue()), {"ok": True, "summary": "s"})


class RestoreBrokenTests(unittest.TestCase):
    def test_green_run_broken_reports_verify_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "main.c")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("int x = 1;\n")
            calls = []

            def _runner():
                calls.append(1)
                if len(calls) == 1:
                    return {"status": "ok", "steps": {"verify": {"results": [
                        {"id": "FR-A", "status": "fail"}]}}}
                return {"status": "internal_error", "error": "crash after restore"}

            got = mutation.mutate_and_run(
                tmp, "FR-A", "main.c", "1", "2", _runner, 30)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "int x = 1;\n")
        self.assertFalse(got["ok"])
        self.assertIn("还原后 verify 自身失败", got["error"])
        self.assertIn("crash after restore", got["error"])


if __name__ == "__main__":
    unittest.main()
