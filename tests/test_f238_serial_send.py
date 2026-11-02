r"""F-238: serial_send 主流程补测（发送/重复/等响应/错误出口）。

## 覆盖对象

`scripts/serial_send.py` 此前 30% 覆盖（2026-11-02 实测）：`main()` 的发送
循环、重复轮次、等响应、写失败与 Hex 解析失败出口从未执行。`build_payload`
的纯函数分支已由 `test_serial_send_payload.py` 覆盖，本文件只补主流程。

## 夹具

`connect_serial` / `resolve_serial_config` / `update_state_entry` 模块引用
替换；假串口记录写入字节并按需返回响应，不碰真机。
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

import serial_send  # noqa: E402


class _FakeSerial:
    def __init__(self, response=b""):
        self.response = response
        self.written = []
        self.flushed = 0
        self.closed = False
        self.timeout = None

    def write(self, payload):
        self.written.append(bytes(payload))

    def flush(self):
        self.flushed += 1

    def read(self, _n):
        return self.response

    def close(self):
        self.closed = True


def _cfg():
    return {"port": "COMX", "baudrate": 115200, "encoding": "utf-8"}


def _run_main(argv, fake, fail=None):
    state = []
    out = io.StringIO()
    err = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["serial_send.py", *argv]
    try:
        with mock.patch.object(serial_send, "resolve_serial_config", return_value=_cfg()), \
                mock.patch.object(serial_send, "connect_serial",
                                  side_effect=fail, return_value=fake), \
                mock.patch.object(serial_send, "update_state_entry",
                                  side_effect=lambda cat, rec: state.append((cat, rec))), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                rc = serial_send.main()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue(), state


class SendMainTests(unittest.TestCase):
    def test_single_text_send(self):
        fake = _FakeSerial()
        rc, out, state = _run_main(["hello", "--port", "COMX"], fake)
        self.assertIsNone(rc)
        self.assertEqual(fake.written, [b"hello"])
        self.assertEqual(fake.flushed, 1)
        self.assertTrue(fake.closed)
        self.assertIn("TX[1]: hello", out)
        self.assertEqual(state[0][0], "last_serial_send")
        self.assertEqual(state[0][1]["bytes_sent"], 5)

    def test_json_output(self):
        fake = _FakeSerial()
        rc, out, _ = _run_main(["hi", "--port", "COMX", "--json"], fake)
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["details"]["tx"], "hi")

    def test_hex_mode_sends_decoded_bytes(self):
        fake = _FakeSerial()
        rc, out, _ = _run_main(["0x41 0x42", "--port", "COMX", "--hex"], fake)
        self.assertIsNone(rc)
        self.assertEqual(fake.written, [b"AB"])
        self.assertIn("TX[1]: 41 42", out)

    def test_bad_hex_exits_one(self):
        rc, _, _ = _run_main(["zz", "--port", "COMX", "--hex"], _FakeSerial())
        self.assertEqual(rc, 1)

    def test_repeat_reports_rounds(self):
        fake = _FakeSerial()
        rc, out, state = _run_main(
            ["x", "--port", "COMX", "--repeat", "3", "--interval", "0", "--json"], fake)
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["details"]["total"], 3)
        self.assertEqual(len(payload["details"]["rounds"]), 3)
        self.assertEqual(state[0][1]["bytes_sent"], 3)

    def test_wait_response_reads_rx(self):
        fake = _FakeSerial(response=b"OK")
        rc, out, _ = _run_main(
            ["ping", "--port", "COMX", "--wait-response", "--json"], fake)
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["details"]["rx"], "OK")
        self.assertEqual(payload["details"]["rx_bytes"], 2)

    def test_wait_response_empty(self):
        fake = _FakeSerial(response=b"")
        rc, out, _ = _run_main(
            ["ping", "--port", "COMX", "--wait-response", "--json"], fake)
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["details"]["rx"], "")

    def test_write_error_exits_one(self):
        class _Broken(_FakeSerial):
            def write(self, _payload):
                raise OSError("write boom")

        rc, _, _ = _run_main(["x", "--port", "COMX"], _Broken())
        self.assertEqual(rc, 1)

    def test_connect_failure_exits_one(self):
        def _fail(*_args, **_kwargs):
            serial_send.error_exit("open_failed", "boom", False)

        rc, _, _ = _run_main(["x", "--port", "COMX"], None, fail=_fail)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
