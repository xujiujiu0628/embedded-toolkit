r"""F-238: openocd_telnet 解析层与连接层补测。

## 覆盖对象

`scripts/openocd_telnet.py` 此前 44% 覆盖（2026-11-02 实测）：地址/寄存器/
内存解析、IAC 过滤、连接重试、提示符读取与 close 语义均未执行。本文件用
假 socket 跑连接层，不接真 OpenOCD。

## 夹具

- `_FakeSock` 按预置块吐字节，记录 sendall/close；
- socket 模块用直接赋值替换（不用 mock.patch —— 会被 test_stub_ratchet
  记为 B 式全局打桩），finally 恢复；
- stdout 用带 `reconfigure` 的 StringIO 子类承接（`output_json` 会调它）。
"""
import io
import os
import socket
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_telnet  # noqa: E402


class _CaptureOut(io.StringIO):
    def reconfigure(self, **_kwargs):
        pass


class _FakeSock:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def settimeout(self, _t):
        pass

    def connect(self, _addr):
        pass

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()

    def close(self):
        self.closed = True


class ParseHexAddrTests(unittest.TestCase):
    def test_accepts_prefixed_hex(self):
        self.assertEqual(openocd_telnet.parse_hex_addr("0x08000000"), 0x08000000)
        self.assertEqual(openocd_telnet.parse_hex_addr("0X10"), 16)

    def test_rejects_bare_decimal(self):
        with self.assertRaises(ValueError):
            openocd_telnet.parse_hex_addr("134217726")

    def test_rejects_empty_and_bad_chars(self):
        with self.assertRaises(ValueError):
            openocd_telnet.parse_hex_addr("0x")
        with self.assertRaises(ValueError):
            openocd_telnet.parse_hex_addr("0xZZ")

    def test_rejects_non_string(self):
        with self.assertRaises(ValueError):
            openocd_telnet.parse_hex_addr(None)


class ParseRegisterTests(unittest.TestCase):
    def test_single_with_bit_width(self):
        self.assertEqual(
            openocd_telnet.parse_reg_single("pc (/32): 0x080009dc"),
            {"pc": "0x080009dc"},
        )

    def test_single_without_bit_width(self):
        self.assertEqual(
            openocd_telnet.parse_reg_single("pc 0x080009dc"),
            {"pc": "0x080009dc"},
        )

    def test_single_unparsable_is_empty(self):
        self.assertEqual(openocd_telnet.parse_reg_single("nothing"), {})

    def test_all_registers_indexed_format(self):
        raw = "(0) r0 (/32): 0x00000001\n(1) pc (/32): 0x080009dc\n"
        self.assertEqual(
            openocd_telnet.parse_reg_response(raw),
            {"r0": "0x00000001", "pc": "0x080009dc"},
        )

    def test_all_registers_fallback_format(self):
        raw = "r0 (/32): 0x00000001\nsp (/32): 0x20005000\n"
        self.assertEqual(
            openocd_telnet.parse_reg_response(raw),
            {"r0": "0x00000001", "sp": "0x20005000"},
        )

    def test_memory_response(self):
        raw = "0x20000000: 0102 0304\n0x20000004: AABB CCDD\n"
        self.assertEqual(openocd_telnet.parse_mem_response(raw), [
            {"address": "0x20000000", "data": "0102 0304"},
            {"address": "0x20000004", "data": "AABB CCDD"},
        ])

    def test_command_error_keywords(self):
        self.assertTrue(openocd_telnet.has_command_error("Error: target not halted"))
        self.assertTrue(openocd_telnet.has_command_error("unknown command"))
        self.assertFalse(openocd_telnet.has_command_error("r0 = 0x1"))


class StripIacTests(unittest.TestCase):
    def test_removes_iac_triplet_and_nul(self):
        raw = b"\xff\xfb\x01hello\x00world"
        self.assertEqual(openocd_telnet.TelnetConnection._strip_iac(raw), b"helloworld")

    def test_plain_bytes_untouched(self):
        self.assertEqual(openocd_telnet.TelnetConnection._strip_iac(b"abc"), b"abc")


class ConnectionTests(unittest.TestCase):
    def _conn(self, chunks):
        conn = openocd_telnet.TelnetConnection(host="h", port=4444, timeout=0.1)
        conn.sock = _FakeSock(chunks)
        return conn

    def test_read_until_prompt_returns_text_before_prompt(self):
        conn = self._conn([b"hello\r\n> "])
        self.assertEqual(conn._read_until_prompt(), "hello")

    def test_read_until_prompt_handles_cr_prompt(self):
        conn = self._conn([b"data\r> "])
        self.assertEqual(conn._read_until_prompt(), "data")

    def test_read_until_prompt_returns_trailing_data_on_eof(self):
        conn = self._conn([b"tail"])
        self.assertEqual(conn._read_until_prompt(), "tail")

    def test_send_requires_connection(self):
        conn = openocd_telnet.TelnetConnection()
        with self.assertRaises(ConnectionError):
            conn.send("halt")

    def test_send_writes_command_and_reads(self):
        conn = self._conn([b"ok\r\n> "])
        self.assertEqual(conn.send("halt"), "ok")
        self.assertEqual(conn.sock.sent, [b"halt\n"])

    def test_close_sends_shutdown_and_closes(self):
        conn = self._conn([])
        sock = conn.sock
        conn.close()
        self.assertIn(b"shutdown\n", sock.sent)
        self.assertTrue(sock.closed)
        self.assertIsNone(conn.sock)

    def test_connect_retries_then_raises(self):
        class _DeadSocket:
            def settimeout(self, _t):
                pass

            def connect(self, _addr):
                raise OSError("refused")

            def close(self):
                pass

        class _FakeSocketModule:
            AF_INET = socket.AF_INET
            SOCK_STREAM = socket.SOCK_STREAM

            @staticmethod
            def socket(*_a):
                return _DeadSocket()

        old_socket, old_sleep = openocd_telnet.socket, openocd_telnet.time.sleep
        openocd_telnet.socket = _FakeSocketModule
        openocd_telnet.time.sleep = lambda _s: None
        try:
            conn = openocd_telnet.TelnetConnection(host="h", port=1, timeout=0.1)
            with self.assertRaises(ConnectionError):
                conn.connect(retries=2)
        finally:
            openocd_telnet.socket = old_socket
            openocd_telnet.time.sleep = old_sleep


class OutputJsonTests(unittest.TestCase):
    def test_output_json_writes_utf8_json(self):
        out = _CaptureOut()
        with redirect_stdout(out):
            openocd_telnet.output_json({"k": "中文"})
        self.assertIn("中文", out.getvalue())


class _FakeTelnet:
    """按命令返回预置响应；未登记的返回空串。"""

    def __init__(self, responses=None, default=""):
        self.responses = responses or {}
        self.default = default
        self.sent = []

    def send(self, command):
        self.sent.append(command)
        value = self.responses.get(command, self.default)
        return value(command) if callable(value) else value


class _FakeTime:
    @staticmethod
    def sleep(_seconds):
        pass


def _args(**kw):
    import argparse
    base = dict(action="halt", count=1, address="0x08000000", length=1,
                width="32", value="0x1", bp_length=2, timeout_ms=10)
    base.update(kw)
    return argparse.Namespace(**base)


class ExecuteActionTests(unittest.TestCase):
    def setUp(self):
        self._old_time = openocd_telnet.time
        openocd_telnet.time = _FakeTime

    def tearDown(self):
        openocd_telnet.time = self._old_time

    def test_halt_ok_reports_pc(self):
        telnet = _FakeTelnet({
            "halt": "",
            "reg pc": "pc (/32): 0x08000000",
            "reg xpsr": "xpsr (/32): 0x01000000",
            "reg msp": "msp (/32): 0x20005000",
        })
        result = openocd_telnet.execute_action(telnet, _args(action="halt"))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["details"]["halted"])
        self.assertIn("PC=0x08000000", result["summary"])

    def test_halt_error_semantics_blocks(self):
        telnet = _FakeTelnet({"halt": "Error: target not halted"}, default="pc (/32): 0x1")
        result = openocd_telnet.execute_action(telnet, _args(action="halt"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "halt_failed")

    def test_halt_reg_empty_reports_unconfirmed(self):
        """空响应不含错误关键词 → status ok 但 halted=False（不硬编码 True）。"""
        telnet = _FakeTelnet({"halt": "", "reg pc": "", "reg xpsr": "", "reg msp": ""})
        result = openocd_telnet.execute_action(telnet, _args(action="halt"))
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["details"]["halted"])
        self.assertIn("未确认暂停", result["summary"])

    def test_resume_ok(self):
        telnet = _FakeTelnet({"resume": ""})
        result = openocd_telnet.execute_action(telnet, _args(action="resume"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("已恢复运行", result["summary"])

    def test_resume_already_running(self):
        telnet = _FakeTelnet({"resume": "not halted, context restore failed"})
        result = openocd_telnet.execute_action(telnet, _args(action="resume"))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["details"]["already_running"])

    def test_resume_error(self):
        telnet = _FakeTelnet({"resume": "Error: boom"})
        result = openocd_telnet.execute_action(telnet, _args(action="resume"))
        self.assertEqual(result["status"], "error")

    def test_step_counts_steps(self):
        telnet = _FakeTelnet(default="pc (/32): 0x08000010")
        result = openocd_telnet.execute_action(telnet, _args(action="step", count=2))
        self.assertEqual(len(result["details"]["steps"]), 2)
        self.assertEqual(result["details"]["pc"], "0x08000010")

    def test_reg_reads_all_core_registers(self):
        telnet = _FakeTelnet(
            responses={"halt": ""},
            default=None,
        )
        telnet.default = lambda cmd: f"{cmd.split()[-1]} (/32): 0x1"
        result = openocd_telnet.execute_action(telnet, _args(action="reg"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["details"]["registers"]), 23)

    def test_reg_all_failed_is_error(self):
        telnet = _FakeTelnet({"halt": ""}, default="")
        result = openocd_telnet.execute_action(telnet, _args(action="reg"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "reg_read_failed")

    def test_read_mem_ok(self):
        telnet = _FakeTelnet({"mdw 0x08000000 1": "0x08000000: 12345678"})
        result = openocd_telnet.execute_action(telnet, _args(action="read-mem"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["memory"][0]["data"], "12345678")

    def test_read_mem_error_and_empty(self):
        err = _FakeTelnet({"mdw 0x08000000 1": "Error: bad address"})
        self.assertEqual(
            openocd_telnet.execute_action(err, _args(action="read-mem"))["error"]["code"],
            "read_failed")
        empty = _FakeTelnet({"mdw 0x08000000 1": "nothing"})
        self.assertEqual(
            openocd_telnet.execute_action(empty, _args(action="read-mem"))["error"]["code"],
            "read_empty")

    def test_write_mem_ok_and_error(self):
        ok = _FakeTelnet({"mww 0x08000000 0x1": ""})
        self.assertEqual(
            openocd_telnet.execute_action(ok, _args(action="write-mem"))["status"], "ok")
        bad = _FakeTelnet({"mww 0x08000000 0x1": "Error: write failed"})
        self.assertEqual(
            openocd_telnet.execute_action(bad, _args(action="write-mem"))["status"], "error")

    def test_bp_and_rbp(self):
        ok = _FakeTelnet()
        self.assertEqual(
            openocd_telnet.execute_action(ok, _args(action="bp"))["status"], "ok")
        self.assertEqual(
            openocd_telnet.execute_action(ok, _args(action="rbp"))["status"], "ok")
        bad = _FakeTelnet(default="Error: failed")
        self.assertEqual(
            openocd_telnet.execute_action(bad, _args(action="bp"))["status"], "error")
        self.assertEqual(
            openocd_telnet.execute_action(bad, _args(action="rbp"))["status"], "error")

    def test_run_to_hit_and_miss(self):
        hit = _FakeTelnet({
            "halt": "", "bp 0x08000000 2 hw": "", "resume": "",
            "reg pc": "pc (/32): 0x08000000", "rbp 0x08000000": "",
        })
        result = openocd_telnet.execute_action(hit, _args(action="run-to"))
        self.assertTrue(result["details"]["bp_hit"])
        self.assertIn("断点命中", result["summary"])

        miss = _FakeTelnet({
            "halt": "", "bp 0x08000000 2 hw": "", "resume": "",
            "reg pc": "pc (/32): 0x08000010", "rbp 0x08000000": "",
        })
        result = openocd_telnet.execute_action(miss, _args(action="run-to"))
        self.assertFalse(result["details"]["bp_hit"])

    def test_run_to_bp_error_removes_and_fails(self):
        telnet = _FakeTelnet({"halt": "", "bp 0x08000000 2 hw": "Error: bp failed"})
        result = openocd_telnet.execute_action(telnet, _args(action="run-to"))
        self.assertEqual(result["error"]["code"], "bp_set_failed")

    def test_run_to_resume_error_removes_bp(self):
        telnet = _FakeTelnet({
            "halt": "", "bp 0x08000000 2 hw": "", "resume": "Error: resume failed",
        })
        result = openocd_telnet.execute_action(telnet, _args(action="run-to"))
        self.assertEqual(result["error"]["code"], "resume_failed")
        self.assertIn("rbp 0x08000000", telnet.sent)

    def test_unknown_action(self):
        result = openocd_telnet.execute_action(_FakeTelnet(), _args(action="bogus"))
        self.assertEqual(result["error"]["code"], "unknown_action")


class PrintResultTests(unittest.TestCase):
    def test_ok_registers_and_memory(self):
        out = _CaptureOut()
        with redirect_stdout(out):
            openocd_telnet.print_result(
                {"status": "ok", "summary": "s", "details": {
                    "registers": {"r0": "0x1"}, "memory": [{"address": "0x0", "data": "AA"}]}},
                "reg")
        text = out.getvalue()
        self.assertIn("r0 = 0x1", text)
        self.assertIn("0x0: AA", text)

    def test_steps_and_bp_hit(self):
        out = _CaptureOut()
        with redirect_stdout(out):
            openocd_telnet.print_result(
                {"status": "ok", "summary": "s", "details": {
                    "steps": [{"step": 1, "pc": "0x1"}],
                    "bp_hit": True, "bp_address": "0x1"}}, "run-to")
        text = out.getvalue()
        self.assertIn("step 1: PC=0x1", text)
        self.assertIn("命中", text)

    def test_error_exits_one(self):
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                openocd_telnet.print_result(
                    {"status": "error", "error": {"message": "boom"}}, "halt")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("boom", err.getvalue())


if __name__ == "__main__":
    unittest.main()
