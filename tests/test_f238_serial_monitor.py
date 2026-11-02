r"""F-238: serial_monitor 行处理与主循环补测。

## 覆盖对象

`scripts/serial_monitor.py` 此前 28% 覆盖（2026-11-02 实测）：`emit_line`
的过滤/异常/JSON 分支与 `main()` 整段（读循环、行切分、退出冲刷、错误出口）
从未执行。

## 夹具

假串口按块吐预置字节；`connect_serial` / `resolve_serial_config` /
`update_state_entry` 模块引用替换。`sys.stderr` 用带 `.buffer` 的替身承接
（main 末尾直接写 `sys.stderr.buffer`）。
"""
import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_monitor  # noqa: E402


class _CaptureErr(io.StringIO):
    def __init__(self):
        super().__init__()
        self.buffer = io.BytesIO()


class _FakeSerial:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False
        self.timeout = None
        self.in_waiting = 0

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


def _cfg():
    return {"port": "COMX", "baudrate": 115200, "encoding": "utf-8"}


class _Args:
    json = False
    timestamp = False


def _emit(text, include=None, exclude=None, json_mode=False, timestamp=False):
    args = _Args()
    args.json = json_mode
    args.timestamp = timestamp
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        kept = serial_monitor.emit_line(text, _cfg(), args, include, exclude)
    return kept, out.getvalue(), err.getvalue()


class EmitLineTests(unittest.TestCase):
    def test_plain_line_printed(self):
        kept, out, _ = _emit("hello")
        self.assertTrue(kept)
        self.assertEqual(out.strip(), "hello")

    def test_timestamp_prefix(self):
        kept, out, _ = _emit("hello", timestamp=True)
        self.assertTrue(kept)
        self.assertTrue(out.startswith("["))

    def test_include_filter_drops_non_matching(self):
        kept, out, _ = _emit("hello", include=re.compile("keep"))
        self.assertFalse(kept)
        self.assertEqual(out, "")

    def test_include_filter_keeps_matching(self):
        kept, _, _ = _emit("keep me", include=re.compile("keep"))
        self.assertTrue(kept)

    def test_exclude_filter_drops_matching(self):
        kept, out, _ = _emit("noise", exclude=re.compile("noise"))
        self.assertFalse(kept)
        self.assertEqual(out, "")

    def test_broken_include_filter_fails_closed(self):
        broken = mock.Mock()
        broken.search.side_effect = RuntimeError("boom")
        kept, _, err = _emit("hello", include=broken)
        self.assertFalse(kept)
        self.assertIn("fail-closed", err)

    def test_broken_exclude_filter_fails_closed(self):
        broken = mock.Mock()
        broken.search.side_effect = RuntimeError("boom")
        kept, _, err = _emit("hello", exclude=broken)
        self.assertFalse(kept)
        self.assertIn("fail-closed", err)

    def test_json_line(self):
        kept, out, _ = _emit("hello", json_mode=True)
        self.assertTrue(kept)
        payload = json.loads(out)
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["port"], "COMX")


def _run_main(argv, fake, fail=None):
    state = []
    out, err = io.StringIO(), _CaptureErr()
    old_argv = sys.argv
    sys.argv = ["serial_monitor.py", *argv]
    try:
        with mock.patch.object(serial_monitor, "resolve_serial_config", return_value=_cfg()), \
                mock.patch.object(serial_monitor, "connect_serial",
                                  side_effect=fail, return_value=fake), \
                mock.patch.object(serial_monitor, "update_state_entry",
                                  side_effect=lambda cat, rec: state.append((cat, rec))), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rc = serial_monitor.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue(), err.getvalue() + err.buffer.getvalue().decode("utf-8"), state


class MonitorMainTests(unittest.TestCase):
    def test_two_complete_lines(self):
        fake = _FakeSerial([b"line1\nline2\n"])
        rc, out, err, state = _run_main(["--port", "COMX", "--timeout", "0.01"], fake)
        self.assertIsNone(rc)
        self.assertIn("line1", out)
        self.assertIn("line2", out)
        self.assertIn("共 2 行", err)
        self.assertTrue(fake.closed)
        self.assertEqual(state[0][0], "last_observe")
        self.assertEqual(state[0][1]["lines"], 2)

    def test_partial_line_flushed_on_exit(self):
        fake = _FakeSerial([b"partial"])
        rc, out, _, _ = _run_main(["--port", "COMX", "--timeout", "0.01"], fake)
        self.assertIsNone(rc)
        self.assertIn("partial", out)

    def test_filter_limits_output(self):
        fake = _FakeSerial([b"keep\nskip\n"])
        rc, out, err, state = _run_main(
            ["--port", "COMX", "--timeout", "0.01", "--filter", "keep"], fake)
        self.assertIsNone(rc)
        self.assertIn("keep", out)
        self.assertNotIn("skip", out)
        self.assertIn("共 1 行", err)
        self.assertEqual(state[0][1]["lines"], 1)

    def test_bad_filter_regex_exits_one(self):
        rc, _, err, _ = _run_main(
            ["--port", "COMX", "--filter", "["], _FakeSerial([]))
        self.assertEqual(rc, 1)
        self.assertIn("无效正则", err)

    def test_json_output(self):
        fake = _FakeSerial([b"hello\n"])
        rc, out, _, _ = _run_main(
            ["--port", "COMX", "--timeout", "0.01", "--json"], fake)
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["text"], "hello")

    def test_crlf_normalized(self):
        fake = _FakeSerial([b"a\r\nb\r\n"])
        rc, out, _, _ = _run_main(["--port", "COMX", "--timeout", "0.01"], fake)
        self.assertIsNone(rc)
        self.assertIn("a", out)
        self.assertIn("b", out)

    def test_read_error_exits_one(self):
        class _Broken(_FakeSerial):
            def read(self, _n):
                raise OSError("boom")

        rc, _, err, _ = _run_main(["--port", "COMX", "--timeout", "0.01"], _Broken([]))
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)

    def test_connect_failure_exits_one(self):
        def _fail(*_args, **_kwargs):
            serial_monitor.error_exit("monitor", "open_failed", "boom", False)

        rc, _, _, _ = _run_main(["--port", "COMX"], None, fail=_fail)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
