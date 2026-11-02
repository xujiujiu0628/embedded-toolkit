r"""F-238: serial_hex 主循环与输出面补测。

## 覆盖对象

`scripts/serial_hex.py` 此前 28% 覆盖（2026-11-02 实测）：`main()` 整段
（读循环 / 空闲冲刷 / 退出冲刷 / 信号 / 错误出口）从未执行。

## 夹具

`connect_serial` / `resolve_serial_config` / `update_state_entry` 用模块引用
替换（仓内合法形态），假串口按块吐预置字节；不碰真机、不依赖 pyserial 端口。
`sys.stderr` 用带 `.buffer` 的 StringIO 子类承接（main 末尾直接写
`sys.stderr.buffer`，普通 StringIO 会 AttributeError）。
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_hex  # noqa: E402


class _CaptureErr(io.StringIO):
    """同时提供 text 与 .buffer 的 stderr 替身。"""

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
    return {
        "port": "COMX", "baudrate": 115200, "bytesize": 8,
        "parity": "none", "stopbits": 1, "encoding": "utf-8",
        "log_dir": "", "timeout": 0.1,
    }


def _run_main(argv, fake, fail=None):
    """进程内跑 main(): 返回 (rc, stdout, stderr, state_calls)。"""
    state_calls = []
    out, err = io.StringIO(), _CaptureErr()
    old_argv = sys.argv
    sys.argv = ["serial_hex.py", *argv]
    try:
        with mock.patch.object(serial_hex, "resolve_serial_config", return_value=_cfg()), \
                mock.patch.object(serial_hex, "connect_serial",
                                  side_effect=fail, return_value=fake), \
                mock.patch.object(serial_hex, "update_state_entry",
                                  side_effect=lambda cat, rec: state_calls.append((cat, rec))), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rc = serial_hex.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue(), err.getvalue() + err.buffer.getvalue().decode("utf-8"), state_calls


class HexDumpLineTests(unittest.TestCase):
    def test_formats_offset_hex_and_ascii(self):
        line = serial_hex.hex_dump_line(b"\x01\x02AB", 0, 16, True)
        self.assertTrue(line.startswith("00000000  01 02 41 42"))
        self.assertTrue(line.endswith("|..AB|"))

    def test_no_ascii_column(self):
        line = serial_hex.hex_dump_line(b"\x01", 0x10, 16, False)
        self.assertNotIn("|", line)
        self.assertIn("00000010", line)


class EmitChunkTests(unittest.TestCase):
    def test_json_chunk_has_hex_and_ascii(self):
        out = io.StringIO()
        with redirect_stdout(out):
            serial_hex.emit_chunk(b"A\x00B", 0, 16, True, True)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["length"], 3)
        self.assertEqual(payload["hex"], "41 00 42")
        self.assertEqual(payload["ascii"], "A.B")

    def test_text_chunk_uses_dump_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            serial_hex.emit_chunk(b"AB", 0, 16, True, False)
        self.assertIn("41 42", out.getvalue())


class MainLoopTests(unittest.TestCase):
    def test_full_line_then_remainder(self):
        fake = _FakeSerial([b"\x00" * 20])
        rc, out, err, state = _run_main(["--port", "COMX", "--timeout", "0.01"], fake)
        self.assertIsNone(rc)
        self.assertIn("00000000", out)
        self.assertIn("00000010", out)
        self.assertIn("共 20 字节", err)
        self.assertTrue(fake.closed)
        self.assertEqual(state[0][0], "last_observe")
        self.assertEqual(state[0][1]["bytes_received"], 20)

    def test_no_ascii_flag(self):
        fake = _FakeSerial([b"AB"])
        rc, out, _, _ = _run_main(
            ["--port", "COMX", "--timeout", "0.01", "--no-ascii"], fake)
        self.assertIsNone(rc)
        self.assertNotIn("|", out)

    def test_json_output_is_json_lines(self):
        fake = _FakeSerial([b"ABC"])
        rc, out, _, _ = _run_main(
            ["--port", "COMX", "--timeout", "0.01", "--json"], fake)
        self.assertIsNone(rc)
        payload = json.loads(out.strip().splitlines()[0])
        self.assertEqual(payload["length"], 3)

    def test_idle_flush_emits_partial_buffer(self):
        fake = _FakeSerial([b"AB"])
        rc, out, _, _ = _run_main(
            ["--port", "COMX", "--timeout", "0.35"], fake)
        self.assertIsNone(rc)
        self.assertIn("41 42", out)

    def test_connect_failure_exits_one(self):
        def _fail(*_args, **_kwargs):
            serial_hex.error_exit("open_failed", "boom", False)

        rc, _, err, _ = _run_main(["--port", "COMX"], None, fail=_fail)
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)

    def test_read_error_exits_one(self):
        class _Broken(_FakeSerial):
            def read(self, _n):
                raise OSError("boom")

        rc, _, err, _ = _run_main(["--port", "COMX", "--timeout", "0.01"], _Broken([]))
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)


if __name__ == "__main__":
    unittest.main()
