r"""零覆盖收官批次 (F-102, WB-C7 / 审计 P1-8): serial 族 + cube_to_keil 的
纯 host 逻辑单测。

范围纪律: 只测**无硬件依赖的纯函数/可 mock 路径**——串口打开/枚举等
真机路径仍留白 (依赖 pyserial 真实端口, 属 P3 登记项)。
覆盖提升后同步移除 test_coverage_lint_reachability 的反向钉条目
(P2-12 纪律: 覆盖提升即移钉)。
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_hex  # noqa: E402
import serial_monitor  # noqa: E402
import serial_scan  # noqa: E402
import cube_usercode as cube_to_keil  # noqa: E402


class SerialHexTests(unittest.TestCase):
    """serial_hex: hex dump 格式化 (纯函数)"""

    def test_hex_dump_line_basic(self):
        line = serial_hex.hex_dump_line(b"AB", 0, 16, show_ascii=False)
        self.assertTrue(line.startswith("00000000  41 42"))
        self.assertNotIn("|", line)

    def test_hex_dump_line_ascii_column(self):
        line = serial_hex.hex_dump_line(b"A\x01B", 0, 16, show_ascii=True)
        self.assertIn("|A.B|", line)   # 不可打印 → '.'; 可打印 → 原字符

    def test_emit_chunk_json_mode(self):
        # serial_hex.output_json 写 sys.stdout.buffer (非 text 层) →
        # redirect_stdout 不拦截, 须直接替换 sys.stdout 为带 buffer 的假对象
        buf = io.BytesIO()
        fake = type("FakeStdout", (), {"buffer": buf})()
        with mock.patch.object(sys, "stdout", fake):
            serial_hex.emit_chunk(b"\x41\x42", 0, 16, True, use_json=True)
        doc = json.loads(buf.getvalue().decode("utf-8"))
        self.assertEqual(doc["hex"], "41 42")
        self.assertEqual(doc["ascii"], "AB")
        self.assertEqual(doc["length"], 2)


class SerialMonitorFilterTests(unittest.TestCase):
    """serial_monitor: include/exclude 过滤语义 (emit_line 纯逻辑)"""

    @staticmethod
    def _args(json=False, timestamp=False):
        return mock.Mock(json=json, timestamp=timestamp)

    @staticmethod
    def _cfg():
        return {"port": "COM3", "baudrate": 115200}

    def test_include_filter_blocks_non_match(self):
        import re
        em = serial_monitor.emit_line("hello", self._cfg(), self._args(),
                                      re.compile("world"), None)
        self.assertFalse(em)

    def test_exclude_filter_blocks_match(self):
        import re
        em = serial_monitor.emit_line("hello world", self._cfg(),
                                      self._args(), None,
                                      re.compile("world"))
        self.assertFalse(em)

    def test_pass_through_prints(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            em = serial_monitor.emit_line("hello", self._cfg(),
                                          self._args(), None, None)
        self.assertTrue(em)
        self.assertIn("hello", buf.getvalue())


class SerialScanChipMapTests(unittest.TestCase):
    """serial_scan: VID/PID 芯片映射 (纯数据逻辑)"""

    def test_load_chip_map_returns_dict_with_known_pairs(self):
        cm = serial_scan.load_chip_map()
        self.assertIsInstance(cm, dict)
        # ST-Link V2 虚拟串口 / CH340 是常见 pair, 至少应有条目
        self.assertTrue(any("ST" in v or "CH340" in v or "CP210" in v
                            for v in cm.values()),
                        f"芯片映射缺常见条目: {cm}")

    def test_scan_ports_filters_non_serial_errors(self):
        """枚举失败 (无 pyserial/无端口) 应返回可序列化结构而非抛异常"""
        with mock.patch.dict(sys.modules, {"serial": None}):
            try:
                ports, error = serial_scan.scan_ports()
            except Exception as e:
                self.fail(f"scan_ports 应体面处理 pyserial 缺失: {e}")
            # 二元组契约: (ports list|None, error str|None)
            self.assertIsNone(ports)
            self.assertIn("pyserial", error)


class CubeToKeilExtractTests(unittest.TestCase):
    """cube_usercode (原 cube_to_keil, F-131): USER CODE 块提取 (纯文本解析)"""

    def test_extract_user_code_blocks(self):
        import tempfile
        sample = (
            "/* USER CODE BEGIN 2 */\n"
            "  HAL_GPIO_WritePin(GPIOA, 1, 1);\n"
            "/* USER CODE END 2 */\n"
            "/* USER CODE BEGIN WHILE */\n"
            "  while (1) { }\n"
            "/* USER CODE END WHILE */\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False,
                                         encoding="ascii") as f:
            f.write(sample)
            path = Path(f.name)
        try:
            blocks = cube_to_keil.extract_user_code(path)
        finally:
            os.remove(path)
        self.assertIn("2", blocks)
        self.assertIn("WHILE", blocks)
        self.assertIn("HAL_GPIO_WritePin", blocks["2"])
        self.assertIn("while (1)", blocks["WHILE"])

    def test_dedent_strips_common_prefix(self):
        self.assertEqual(cube_to_keil._dedent("  a\n  b\n"), "a\nb\n")
        self.assertEqual(cube_to_keil._dedent("a\n  b\n"), "a\n  b\n")
        self.assertEqual(cube_to_keil._dedent("  \n  a\n"), "  \na\n")


if __name__ == "__main__":
    unittest.main()
