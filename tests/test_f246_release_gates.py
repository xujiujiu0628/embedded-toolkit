r"""F-246: release 的 gate1 解析 / gcc 版本 / run_gates 门禁分支补测。

## 覆盖对象

`release` 91% 的尾部：`gate1` 的超时与输出不可解析、`_gcc_version` 的异常
回落、`run_gates` 的 G0 失败 / G0.5 目标解析失败 / wch 探测 / G1 未绿 /
results 缺失 / FAIL 条目 / xfail 未翻转 / 证据等级门与成功路径。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import release  # noqa: E402


class Gate1Tests(unittest.TestCase):
    def _run(self, proc=None, exc=None):
        def _run(*_a, **_k):
            if exc:
                raise exc
            return proc

        old_sub = release.subprocess
        release.subprocess = SimpleNamespace(
            run=_run, TimeoutExpired=TimeoutError)
        try:
            with mock.patch.object(release, "_idf_build_budget", return_value=None), \
                    mock.patch.object(release, "_project_config", return_value={}):
                return release.gate1("ws", 10)
        finally:
            release.subprocess = old_sub

    def test_non_json_output(self):
        result = self._run(SimpleNamespace(stdout="{bad", stderr="tail"))
        self.assertEqual(result["status"], "error")
        self.assertIn("不可解析", result["error"])

    def test_timeout(self):
        result = self._run(exc=TimeoutError())
        self.assertEqual(result["status"], "error")
        self.assertIn("重跑超时", result["error"])


class GccVersionTests(unittest.TestCase):
    def test_exception_returns_unknown(self):
        old_sub = release.subprocess
        release.subprocess = SimpleNamespace(
            run=lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        try:
            self.assertEqual(release._gcc_version(), "unknown")
        finally:
            release.subprocess = old_sub


class RunGatesTests(unittest.TestCase):
    def _run(self, *, g0=None, esp=False, target=None, swd=(True, "ok"),
             gate1_res=None, allow_xfail=False, allow_non_hw=False):
        def _target(*_a, **_k):
            if isinstance(target, Exception):
                raise target
            return target or {"source": "arm", "exe": "o", "cfg_list": []}

        with mock.patch.object(release, "g0_checks", return_value=g0 or []), \
                mock.patch.object(release, "esp_backend_mode", return_value=esp), \
                mock.patch.object(release, "load_machine", return_value={}), \
                mock.patch.object(release, "resolve_openocd_target", side_effect=_target), \
                mock.patch.object(release, "swd_probe", return_value=swd), \
                mock.patch.object(release, "gate1", return_value=gate1_res or {}):
            return release.run_gates("ws", "v1", allow_xfail, 10, "openocd",
                                     allow_non_hw)

    def _ok_gate1(self, **over):
        base = {"status": "ok", "evidence": "hardware_validated",
                "steps": {"verify": {"results": [{"id": "A", "status": "pass"}]}}}
        base.update(over)
        return base

    def test_g0_failure(self):
        ok, msg, ctx = self._run(g0=["dirty"])
        self.assertFalse(ok)
        self.assertIn("G0 失败", msg)
        self.assertEqual(ctx, {})

    def test_g05_target_error(self):
        ok, msg, _ = self._run(target=release.OpenocdCfgError("bad cfg"))
        self.assertFalse(ok)
        self.assertIn("目标解析失败", msg)

    def test_g05_wch_probe_success(self):
        ok, msg, _ = self._run(target={"source": "wch", "exe": "w", "cfg_list": ["wch.cfg"]},
                               gate1_res=self._ok_gate1())
        self.assertTrue(ok)

    def test_g05_probe_failure(self):
        ok, msg, _ = self._run(swd=(False, "no probe"))
        self.assertFalse(ok)
        self.assertIn("SWD 预检失败", msg)

    def test_esp_skips_g05(self):
        ok, _, ctx = self._run(esp=True, gate1_res=self._ok_gate1())
        self.assertTrue(ok)
        self.assertEqual(ctx["g0_5"]["status"], "skipped")

    def test_g1_not_ok(self):
        ok, msg, _ = self._run(gate1_res={"status": "error", "error": "boom"})
        self.assertFalse(ok)
        self.assertIn("G1 verify 未绿", msg)

    def test_results_missing(self):
        ok, msg, _ = self._run(gate1_res={"status": "ok", "steps": {}})
        self.assertFalse(ok)
        self.assertIn("缺 results", msg)

    def test_fail_entry(self):
        ok, msg, _ = self._run(gate1_res=self._ok_gate1(
            steps={"verify": {"results": [{"id": "F", "status": "fail"}]}}))
        self.assertFalse(ok)
        self.assertIn("FAIL 条目", msg)

    def test_xfail_without_waiver(self):
        ok, msg, _ = self._run(gate1_res=self._ok_gate1(
            steps={"verify": {"results": [{"id": "X", "status": "xfail"}]}}))
        self.assertFalse(ok)
        self.assertIn("未翻转 xfail", msg)

    def test_non_hardware_evidence_gate(self):
        ok, msg, _ = self._run(gate1_res=self._ok_gate1(evidence="static"))
        self.assertFalse(ok)
        self.assertIn("证据等级", msg)

    def test_all_green_with_waivers(self):
        ok, msg, ctx = self._run(
            gate1_res=self._ok_gate1(
                evidence="static",
                steps={"verify": {"results": [{"id": "X", "status": "xfail"}]}}),
            allow_xfail=True, allow_non_hw=True)
        self.assertTrue(ok)
        self.assertEqual(ctx["waived"], ["X"])
        self.assertTrue(ctx["evidence_waiver"])


if __name__ == "__main__":
    unittest.main()
