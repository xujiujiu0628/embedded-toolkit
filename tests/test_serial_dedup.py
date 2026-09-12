r"""F-156 (P2-1) serial 族收编身份钉 + 字节契约钉。

契约:
  1. 身份钉: 五入口 output_json 必须是 serial_runtime 规范版同一对象
     (再导出非拷贝) — monitor/hex 用 output_jsonl (JSON Lines 紧凑态),
     send/log/scan 用 output_json (indent=2);
  2. 字节钉: 两种规范输出与被删的本地副本逐字节一致 (indent=2 / 紧凑单行,
     ensure_ascii=False, 尾随单个 \n) — buffer 直写;
  3. PARITY_MAP ×4 死码删除 (serial_runtime.open_serial_port 内的功能性
     本地映射保留);
  4. 公共骨架: resolve_serial_config / connect_serial 的失败分流与
     mux 警告文案参数化 — 各家 error_exit/文案差异保留。
"""
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_hex       # noqa: E402
import serial_log       # noqa: E402
import serial_monitor   # noqa: E402
import serial_runtime   # noqa: E402
import serial_scan      # noqa: E402
import serial_send      # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _src(name):
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
        return f.read()


class _FakeOut(io.StringIO):
    """带 no-op reconfigure 的假 stdout — 兼容两种规范输出"""

    def reconfigure(self, **kw):
        pass


class ByteContractTests(unittest.TestCase):
    """验收: 改 import 前后 stdout 逐字节一致 (文本层; utf-8 由
    reconfigure 守卫保证)"""

    def _capture(self, fn):
        fake = _FakeOut()
        with mock.patch.object(sys, "stdout", fake):
            fn({"状态": "ok", "port": "COM3"})
        return fake.getvalue()

    def test_output_json_bytes_exact(self):
        # indent=2 + ensure_ascii=False + 尾随 \n (原 send/log/scan 副本形态)
        out = self._capture(serial_runtime.output_json)
        self.assertEqual(out, '{\n  "状态": "ok",\n  "port": "COM3"\n}\n')

    def test_output_jsonl_bytes_exact(self):
        # 紧凑单行 + 尾随 \n (原 monitor/hex 副本形态)
        out = self._capture(serial_runtime.output_jsonl)
        self.assertEqual(out, '{"状态": "ok", "port": "COM3"}\n')


class IdentityPinTests(unittest.TestCase):
    def test_indent2_entries_share_serial_runtime_output_json(self):
        for mod in (serial_send, serial_log, serial_scan):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.output_json, serial_runtime.output_json)

    def test_jsonl_entries_share_serial_runtime_output_jsonl(self):
        for mod in (serial_monitor, serial_hex):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.output_json, serial_runtime.output_jsonl)

    def test_two_canonical_outputs_are_distinct(self):
        # JSON Lines 紧凑态与 indent=2 态字节不同 — 不可互替
        self.assertIsNot(serial_runtime.output_json,
                         serial_runtime.output_jsonl)


class ParityMapDeadCopyTests(unittest.TestCase):
    def test_dead_copies_removed(self):
        for name in ("serial_monitor.py", "serial_hex.py",
                     "serial_send.py", "serial_log.py"):
            with self.subTest(f=name):
                self.assertNotIn("PARITY_MAP", _src(name))
        # serial_runtime.open_serial_port 内的功能性映射保留
        self.assertIn("PARITY_MAP", _src("serial_runtime.py"))


class SerialScanDedupTests(unittest.TestCase):
    def test_scan_ports_delegates_to_runtime(self):
        # 本地 40 行扫描副本删除 — list_ports import 不再出现在 serial_scan
        self.assertNotIn("from serial.tools.list_ports", _src("serial_scan.py"))
        self.assertIs(serial_scan.scan_serial_ports,
                      serial_runtime.scan_serial_ports)


class SkeletonTests(unittest.TestCase):
    """公共骨架: 失败分流 + mux 警告文案参数化"""

    def _args(self, **kw):
        import argparse
        ns = argparse.Namespace(port=None, baudrate=None, bytesize=None,
                                parity=None, stopbits=None, encoding=None,
                                direct=False)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_resolve_config_multiple_candidates_route(self):
        calls = []
        cfg_sources = (None, {"need_selection": True, "error": "多候选"})
        with mock.patch.object(serial_runtime, "get_serial_config",
                               return_value=cfg_sources), \
                mock.patch.object(serial_runtime, "save_project_config"):
            serial_runtime.resolve_serial_config(
                self._args(), fail=lambda c, m: calls.append((c, m)))
        self.assertEqual(calls, [("multiple_candidates", "多候选，请用 --port 指定")])

    def test_resolve_config_saves_confirmed_values(self):
        saved = {}
        cfg = {"port": "COM3", "baudrate": 115200, "bytesize": 8,
               "parity": "none", "stopbits": 1, "encoding": "utf-8"}
        with mock.patch.object(serial_runtime, "get_serial_config",
                               return_value=(cfg, {})), \
                mock.patch.object(serial_runtime, "save_project_config",
                                  side_effect=lambda values: saved.update(values)):
            out = serial_runtime.resolve_serial_config(
                self._args(), fail=lambda c, m: None)
        self.assertEqual(out, cfg)
        self.assertEqual(saved["port"], "COM3")

    def test_connect_serial_warns_when_mux_used(self):
        ser = mock.Mock()
        setattr(ser, "_serial_skill_using_mux", True)
        err = io.StringIO()
        with mock.patch.object(serial_runtime, "open_serial_port",
                               return_value=ser) as m_open, \
                mock.patch.object(sys, "stderr", err):
            got = serial_runtime.connect_serial(
                {}, self._args(direct=False),
                mux_warn="[mux] WIRE-ME", fail=lambda c, m: None)
        self.assertIs(got, ser)
        self.assertIn("[mux] WIRE-ME", err.getvalue())
        self.assertTrue(m_open.call_args.kwargs.get("use_mux"))

    def test_connect_serial_direct_skips_mux_and_silence(self):
        ser = mock.Mock(spec=["close"])   # spec 防自动属性伪造 mux 标记
        err = io.StringIO()
        with mock.patch.object(serial_runtime, "open_serial_port",
                               return_value=ser) as m_open, \
                mock.patch.object(sys, "stderr", err):
            serial_runtime.connect_serial(
                {}, self._args(direct=True),
                mux_warn="[mux] WIRE-ME", fail=lambda c, m: None)
        self.assertFalse(m_open.call_args.kwargs.get("use_mux"))
        self.assertNotIn("WIRE-ME", err.getvalue())

    def test_connect_serial_failure_routes_to_fail(self):
        calls = []
        with mock.patch.object(serial_runtime, "open_serial_port",
                               side_effect=OSError("port gone")):
            serial_runtime.connect_serial(
                {}, self._args(),
                mux_warn="w", fail=lambda c, m: calls.append((c, m)))
        self.assertEqual(calls, [("connect_failed", "port gone")])


if __name__ == "__main__":
    unittest.main()
