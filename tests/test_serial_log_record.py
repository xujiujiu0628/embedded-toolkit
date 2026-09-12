r"""serial_log 主记录循环的行为测试 (F-102 补充)。

覆盖: 三种格式 (text/csv/jsonl) 的落盘正确性 + duration 停止条件 +
timestamp 前缀。串口打开由 mock open_serial_port 供给假端口
(readline 返回预置字节流), 不碰真机。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_log  # noqa: E402


class _FakeSerial:
    """readline() 按行吐预置数据, 读完返回 b'' (模拟超时空转)"""

    def __init__(self, lines):
        self._buf = b"".join(lines)
        self._pos = 0

    def close(self):
        pass

    def readline(self):
        if self._pos >= len(self._buf):
            # 读完: 模拟持续超时空读, 由 duration 终止循环
            time.sleep(0.05)
            return b""
        nl = self._buf.find(b"\n", self._pos)
        if nl == -1:
            line, self._pos = self._buf[self._pos:], len(self._buf)
        else:
            line, self._pos = self._buf[self._pos:nl + 1], nl + 1
        return line


class SerialLogRecordTests(unittest.TestCase):

    def _run_log(self, lines, fmt, timestamp=False, duration=0.4):
        ext = {"json": "jsonl"}.get(fmt, fmt)
        out_path = os.path.join(self.tmp, f"out.{ext}")
        fake = _FakeSerial(lines)
        argv = ["serial_log.py", "--port", "COMX", "--output", out_path,
                "--format", fmt, "--duration", str(duration),
                "--direct", "--json"] + (["--timestamp"] if timestamp else [])
        with mock.patch.object(serial_log.sys, "argv", argv), \
             mock.patch.object(serial_log, "get_serial_config",
                               return_value=({"port": "COMX",
                                              "baudrate": 115200,
                                              "bytesize": 8, "parity": "none",
                                              "stopbits": 1,
                                              "encoding": "utf-8",
                                              "log_dir": self.tmp,
                                              "timeout": 1.0},
                                             {"port": "cli"})), \
             mock.patch.object(serial_log, "save_project_config",
                               lambda **kw: None), \
             mock.patch.object(serial_log, "open_serial_port",
                               return_value=fake):
            code = serial_log.main()
        # main() 成功路径无显式 return → None (非 0)
        self.assertIsNone(code)
        return out_path

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_text_format_with_timestamp(self):
        out = self._run_log([b"boot ok\n", b"tick 1\n"], "text",
                            timestamp=True)
        lines = open(out, encoding="utf-8").read().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^\[\d{4}-\d{2}-\d{2}T[\d:.]+\] boot ok$")

    def test_csv_format_escapes_quotes(self):
        out = self._run_log([b'he said "hi"\n'], "csv")
        line = open(out, encoding="utf-8").read().strip().splitlines()[-1]
        self.assertIn('""hi""', line, "csv 引号必须转义")

    def test_jsonl_format_valid_json(self):
        out = self._run_log([b"hello\n"], "json")
        doc = json.loads(open(out, encoding="utf-8").read().strip())
        self.assertEqual(doc["text"], "hello")

    def test_invalid_utf8_falls_back_to_hex(self):
        out = self._run_log([b"\xff\xfe bad\n"], "text")
        content = open(out, encoding="utf-8").read().strip()
        self.assertNotIn("bad", content.split("] ")[-1][:4])  # 保留 hex 形态


if __name__ == "__main__":
    unittest.main()
