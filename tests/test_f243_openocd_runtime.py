r"""F-243: openocd_runtime 的配置解析/流输出/SWD 探测补测。

## 覆盖对象

`scripts/openocd_runtime.py` 此前 80% 覆盖（2026-11-02 实测）：`load_local_config`
的调用栈推断、`resolve_param` 的 machine/path/default 三级回落、
`emit_stream_record` 的 JSON/文本分支、`swd_probe` 的成功/失败/超时/异常
四态未执行。

## 夹具

`subprocess` / `time` 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据），
用完还原；不启真 OpenOCD。
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_runtime  # noqa: E402


class LoadLocalConfigTests(unittest.TestCase):
    def test_without_script_file_uses_callstack(self):
        cfg = openocd_runtime.load_local_config()
        self.assertIsInstance(cfg, dict)


class EmitStreamRecordTests(unittest.TestCase):
    def test_json_record_with_channel_and_extra(self):
        out = io.StringIO()
        with redirect_stdout(out):
            openocd_runtime.emit_stream_record(
                source="openocd", channel_type="itm", text="hello\r\n",
                as_json=True, channel=3, extra={"k": "v"})
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["channel"], 3)
        self.assertEqual(payload["k"], "v")

    def test_text_without_newline_gets_one(self):
        out = io.StringIO()
        with redirect_stdout(out):
            openocd_runtime.emit_stream_record(
                source="s", channel_type="uart", text="abc", as_json=False)
        self.assertEqual(out.getvalue(), "abc\n")

    def test_text_with_newline_is_not_doubled(self):
        out = io.StringIO()
        with redirect_stdout(out):
            openocd_runtime.emit_stream_record(
                source="s", channel_type="uart", text="abc\n", as_json=False)
        self.assertEqual(out.getvalue(), "abc\n")


class ResolveParamTests(unittest.TestCase):
    def test_cli_wins(self):
        value, source = openocd_runtime.resolve_param("exe", "openocd-x")
        self.assertEqual((value, source), ("openocd-x", "cli"))

    def test_config_second(self):
        value, source = openocd_runtime.resolve_param(
            "exe", None, config={"exe": "cfg-x"}, config_keys=["exe"])
        self.assertEqual((value, source), ("cfg-x", "config:exe"))

    def test_state_third(self):
        value, source = openocd_runtime.resolve_param(
            "gdb_port", None, state_record={"gdb_port": 4444}, state_keys=["gdb_port"])
        self.assertEqual((value, source), (4444, "state:gdb_port"))

    def test_machine_fallback_for_exe(self):
        with mock.patch.object(openocd_runtime, "_machine_openocd_exe",
                               return_value="/machine/openocd"):
            value, source = openocd_runtime.resolve_param("exe", None)
        self.assertEqual((value, source), ("/machine/openocd", "machine:openocd_exe"))

    def test_path_fallback_for_exe(self):
        with mock.patch.object(openocd_runtime, "_machine_openocd_exe", return_value=""), \
                mock.patch.object(openocd_runtime, "which",
                                  side_effect=lambda name: "/usr/bin/openocd" if name == "openocd" else None):
            value, source = openocd_runtime.resolve_param("exe", None)
        self.assertEqual((value, source), ("/usr/bin/openocd", "path"))

    def test_default_when_nothing_found(self):
        with mock.patch.object(openocd_runtime, "_machine_openocd_exe", return_value=""), \
                mock.patch.object(openocd_runtime, "which", return_value=None):
            value, source = openocd_runtime.resolve_param("exe", None)
        self.assertEqual((value, source), ("openocd", "default"))

    def test_required_missing_raises(self):
        with self.assertRaises(ValueError):
            openocd_runtime.resolve_param("board", None, required=True)

    def test_normalize_as_path(self):
        value, _ = openocd_runtime.resolve_param(
            "file", "fw.hex", normalize_as_path=True)
        self.assertTrue(os.path.isabs(value))


class SwdProbeTests(unittest.TestCase):
    def _probe(self, results, attempts=1):
        calls = []

        def _run(_cmd, **_kw):
            calls.append(1)
            item = results.pop(0)
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(stdout="", stderr=item)

        old_sub, old_time = openocd_runtime.subprocess, openocd_runtime.time
        openocd_runtime.subprocess = SimpleNamespace(
            run=_run, TimeoutExpired=TimeoutError)
        openocd_runtime.time = SimpleNamespace(sleep=lambda _s: None)
        try:
            return openocd_runtime.swd_probe("openocd", attempts=attempts,
                                             cfg_list=["i.cfg", "t.cfg"]), calls
        finally:
            openocd_runtime.subprocess = old_sub
            openocd_runtime.time = old_time

    def test_success(self):
        (ok, tail), calls = self._probe(["Info : shutdown command invoked"])
        self.assertTrue(ok)
        self.assertIn("shutdown", tail)
        self.assertEqual(len(calls), 1)

    def test_init_mode_failed_is_not_success(self):
        (ok, tail), _ = self._probe(["Error: init mode failed"])
        self.assertFalse(ok)
        self.assertIn("init mode failed", tail)

    def test_timeout_then_retry(self):
        (ok, tail), calls = self._probe([TimeoutError("slow"), "shutdown command invoked"],
                                        attempts=2)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)

    def test_exception_reported(self):
        (ok, tail), _ = self._probe([OSError("boom")])
        self.assertFalse(ok)
        self.assertIn("boom", tail)


if __name__ == "__main__":
    unittest.main()
