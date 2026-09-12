r"""P2-6 边角缺陷打包回归钉 (工单 P2-6, F-133)。

每条一小钉:
  a. serial_monitor.emit_line 过滤异常 fail-closed (旧: except pass → 放行)
  b. physical_gate expected<=0 前置 probe_error (旧: deviation 恒 0 恒绿)
  c. svd_to_json.resolve_derived_from 死函数删 + merge_into_ref 保留现版本
  d. rm_lookup.format_result 显式 ref_data 参数 (库态无 NameError)
  e. duration_profile 工程根发现改共享 find_project_root (静态钉)
  f. openocd_telnet 地址 parse_hex_addr 显式解析 (十进制不再静默误读)
  g. openocd_run operation_mode 非数字 → JSON 错误契约 (旧: 裸 traceback)
  h. 三入口 ROOT_DIR=parents[2] 无效锚清除 (静态钉)
  i. capture_semihosting/serial_mux Popen 补 hidden_subprocess_kwargs (静态钉)
  j. save_json_file 写失败不留 .tmp 残骸
  k. serial_runtime.get_serial_config 注解修正 (静态钉)
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

import openocd_run      # noqa: E402
import openocd_telnet   # noqa: E402
import physical_gate    # noqa: E402
import rm_lookup        # noqa: E402
import runtime_common   # noqa: E402
import serial_monitor   # noqa: E402
import svd_to_json      # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _src(name):
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
        return f.read()


class _Args:
    def __init__(self, **kw):
        self.json = kw.get("json", False)
        self.timestamp = False
        for k, v in kw.items():
            setattr(self, k, v)


class FilterFailClosedTests(unittest.TestCase):
    class _Boom:
        def search(self, s):
            raise RuntimeError("simulated filter failure")

    def test_include_exception_skips_line_with_warning(self):
        err = io.StringIO()
        with redirect_stderr(err):
            em = serial_monitor.emit_line(
                "hello", {"port": "COM3", "baudrate": 115200},
                _Args(), self._Boom(), None)
        self.assertFalse(em, "include 过滤器异常时该行必须被跳过 (fail-closed)")
        self.assertIn("include", err.getvalue())

    def test_exclude_exception_skips_line_with_warning(self):
        err = io.StringIO()
        with redirect_stderr(err):
            em = serial_monitor.emit_line(
                "hello", {"port": "COM3", "baudrate": 115200},
                _Args(), None, self._Boom())
        self.assertFalse(em)
        self.assertIn("exclude", err.getvalue())


class PhysicalGateExpectedGuardTests(unittest.TestCase):
    def test_zero_expected_rejects_before_subprocess(self):
        for bad in (0, -2):
            with self.subTest(expected=bad):
                ws = tempfile.mkdtemp()
                with mock.patch.object(physical_gate.subprocess, "run",
                                       side_effect=AssertionError(
                                           "expected<=0 时不得启动子进程")):
                    r = physical_gate.step_physical_gate(
                        {"enable": True, "expected_toggles_per_sec": bad},
                        timeout=5, workspace=ws)
                self.assertEqual(r["status"], "probe_error")
                self.assertIn("expected", r["error"])


class SvdToJsonP2Tests(unittest.TestCase):
    def test_resolve_derived_from_gone(self):
        self.assertFalse(hasattr(svd_to_json, "resolve_derived_from"))

    def test_merge_keeps_existing_meta_version(self):
        ws = tempfile.mkdtemp()
        ref_path = os.path.join(ws, "ref.json")
        runtime_common.save_json_file(ref_path, {
            "_meta": {"version": "2.3.0", "updated": "2026-09-12"},
            "peripherals": {}})
        added, total = svd_to_json.merge_into_ref(
            {"NEWPER": {"registers": {}}}, ref_path)
        self.assertEqual(added, 1)
        meta = runtime_common.load_json_file(ref_path)["_meta"]
        self.assertEqual(meta["version"], "2.3.0", "版本不得被硬编码覆写")
        self.assertEqual(meta["updated"], "2026-09-12")


class RmLookupRefDataParamTests(unittest.TestCase):
    def test_format_result_takes_explicit_ref_data(self):
        result = {"query": "nope", "peripherals": [], "registers": [],
                  "bits": [], "recipes": []}
        try:
            with redirect_stdout(io.StringIO()):
                rm_lookup.format_result(result, {"peripherals": {}})
        except NameError as e:
            self.fail(f"库态调用 format_result 仍踩模块级 ref_data: {e}")

    def test_no_bare_meta_indexing(self):
        self.assertNotIn("len(ref_data['peripherals'])", _src("rm_lookup.py"))


class DurationProfileSharedRootTests(unittest.TestCase):
    def test_main_uses_shared_finder(self):
        src = _src("duration_profile.py")
        self.assertIn("find_project_root", src)
        self.assertNotIn("while ws and not os.path.isdir", src)


class TelnetAddressParseTests(unittest.TestCase):
    def test_parse_hex_addr_accepts_0x_form(self):
        self.assertEqual(openocd_telnet.parse_hex_addr("0x20000000"), 0x20000000)

    def test_parse_hex_addr_rejects_decimal_and_garbage(self):
        for bad in ("134217726", "", "0xZZ", "addr"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    openocd_telnet.parse_hex_addr(bad)


class OperationModeGuardTests(unittest.TestCase):
    def test_bad_operation_mode_exits_1_with_json(self):
        ws = tempfile.mkdtemp()
        cfg = os.path.join(ws, "ocd.json")
        runtime_common.save_json_file(cfg, {"operation_mode": "not-a-number"})
        buf = io.StringIO()
        code = None
        with mock.patch.object(sys, "argv", ["openocd_run.py", "raw",
                                             "--command", "foo",
                                             "--json", "--workspace", ws,
                                             "--config", cfg]), \
             redirect_stdout(buf), redirect_stderr(io.StringIO()):
            try:
                openocd_run.main()
            except SystemExit as e:
                code = e.code if e.code is not None else 0
        self.assertEqual(code, 1, "非法 operation_mode 必须以错误契约退出")
        out = json.loads(buf.getvalue()) if buf.getvalue().strip() else {}
        self.assertEqual(out.get("status"), "error")


class StaticGuardTests(unittest.TestCase):
    """h/i/k 静态钉。"""

    def test_capture_semihosting_uses_guard(self):
        self.assertIn("hidden_subprocess_kwargs", _src("capture_semihosting.py"))

    def test_serial_mux_uses_guard(self):
        self.assertIn("hidden_subprocess_kwargs", _src("serial_mux.py"))

    def test_root_dir_anchors_gone(self):
        for name in ("openocd_run.py", "openocd_gdb.py", "openocd_itm.py"):
            with self.subTest(f=name):
                self.assertNotIn("ROOT_DIR = Path(__file__).resolve().parents[2]",
                                 _src(name))

    def test_get_serial_config_annotation(self):
        src = _src("serial_runtime.py")
        self.assertIn("tuple[dict | None, dict]", src,
                      "注解应承认 (None, dict) 返回路径")


class TmpCleanupTests(unittest.TestCase):
    """j. save_json_file 写失败不留 .tmp 残骸。

    设计要点: 让真实 write_text 落盘、os.replace 失败——tmp 文件必须真实
    出现在目录里, 现实现无 finally 清理 → 残留 (真红); mock write_text
    会连 tmp 都不生成, 是假绿陷阱。"""

    def test_tmp_removed_on_failure(self):
        ws = tempfile.mkdtemp()
        target = os.path.join(ws, "a.json")
        with mock.patch("os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                runtime_common.save_json_file(target, {"x": 1})
        # 前置事实: tmp 确实写出来了 (否则本钉测不到任何东西)
        tmps = [f for f in os.listdir(ws) if f.endswith(".tmp")]
        self.assertEqual(tmps, [], f"写失败残留 tmp: {tmps}")


if __name__ == "__main__":
    unittest.main()
