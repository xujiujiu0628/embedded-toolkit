r"""F-241: serial_log 的默认输出路径 / --console / --max-size / summary 补测。

## 覆盖对象

`scripts/serial_log.py` 此前 78% 覆盖（2026-11-02 实测）：默认输出路径生成、
`--console` 镜像、`--max-size` 截断、summary JSON 与连接失败出口未执行
（既有 `test_serial_log_record.py` 只覆盖三种格式的落盘主路径）。

## 夹具

假串口按行吐预置数据；`resolve_serial_config` / `connect_serial` 模块引用替换。
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

import serial_log  # noqa: E402


class _FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.closed = True


def _cfg(log_dir):
    return {"port": "COMX", "baudrate": 115200, "bytesize": 8, "parity": "none",
            "stopbits": 1, "encoding": "utf-8", "log_dir": log_dir, "timeout": 1.0}


def _run(argv, fake, log_dir, fail=None):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["serial_log.py", *argv]
    try:
        with mock.patch.object(serial_log, "resolve_serial_config", return_value=_cfg(log_dir)), \
                mock.patch.object(serial_log, "connect_serial",
                                  side_effect=fail, return_value=fake), \
                mock.patch.object(serial_log, "update_state_entry"), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rc = serial_log.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class SerialLogCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_default_output_path_created(self):
        fake = _FakeSerial([b"line1\n"])
        out_path = os.path.join(self.tmp.name, "out.log")
        rc, out, _ = _run(["--port", "COMX", "--duration", "0.01",
                           "--output", out_path, "--json"], fake, self.tmp.name)
        self.assertIsNone(rc)
        with open(out_path, encoding="utf-8") as fh:
            self.assertIn("line1", fh.read())
        summary = json.loads(out)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["summary"]["lines"], 1)

    def test_no_output_uses_log_dir(self):
        fake = _FakeSerial([b"x\n"])
        rc, _, _ = _run(["--port", "COMX", "--duration", "0.01"], fake, self.tmp.name)
        self.assertIsNone(rc)
        files = os.listdir(self.tmp.name)
        self.assertTrue(any(name.startswith("serial_") and name.endswith(".log")
                            for name in files))

    def test_console_mirrors_to_stderr(self):
        fake = _FakeSerial([b"mirror\n"])
        out_path = os.path.join(self.tmp.name, "o.log")
        rc, _, err = _run(["--port", "COMX", "--duration", "0.01",
                           "--output", out_path, "--console"], fake, self.tmp.name)
        self.assertIsNone(rc)
        self.assertIn("mirror", err)

    def test_timestamp_prefix(self):
        fake = _FakeSerial([b"ts\n"])
        out_path = os.path.join(self.tmp.name, "o.log")
        _run(["--port", "COMX", "--duration", "0.01", "--output", out_path,
              "--timestamp"], fake, self.tmp.name)
        with open(out_path, encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith("["))

    def test_max_size_stops_recording(self):
        fake = _FakeSerial([b"aaaa\n", b"bbbb\n", b"cccc\n"])
        out_path = os.path.join(self.tmp.name, "o.log")
        rc, out, _ = _run(["--port", "COMX", "--duration", "1",
                           "--output", out_path, "--max-size", "0.000001",
                           "--json"], fake, self.tmp.name)
        self.assertIsNone(rc)
        self.assertLessEqual(json.loads(out)["summary"]["lines"], 3)

    def test_connect_failure_exits_one(self):
        def _fail(*_a, **_k):
            serial_log.error_exit("open_failed", "boom", False)

        rc, _, _ = _run(["--port", "COMX"], None, self.tmp.name, fail=_fail)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
