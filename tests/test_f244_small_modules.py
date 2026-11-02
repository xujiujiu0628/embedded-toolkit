r"""F-244: physical_gate / capture_sim / serial_monitor / duration_profile 零散补测。

## 覆盖对象

四个小模块在 2026-11-02 实测均低于 90%：physical_gate 的探测超时/缺行/
fail_reads 违例、capture_sim 的 qemu 解析链与启动失败、serial_monitor 的
坏编码回落与 CR 续行、duration_profile 的非数值耗时跳过。

## 夹具

子进程/时间用直接赋值替身（避免 test_stub_ratchet 的 B 式判据）；
运行目录用临时工程。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_sim  # noqa: E402
import duration_profile  # noqa: E402
import physical_gate  # noqa: E402
import serial_monitor  # noqa: E402


class PhysicalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"enable": True, "expected_toggles_per_sec": 4.0,
                    "measurement_window_ms": 100, "warmup_ms": 10,
                    "sample_interval_ms": 1, "min_edges": 8}

    def _run(self, stdout="", stderr="", popen_exc=None, communicate_exc=None,
             cfg_exc=None):
        class _Proc:
            def __init__(self):
                self._raised = False

            def communicate(self, timeout=None):
                if communicate_exc and not self._raised:
                    self._raised = True
                    raise communicate_exc
                return stdout, stderr

            def kill(self):
                pass

        def _popen(*_a, **_k):
            if popen_exc:
                raise popen_exc
            return _Proc()

        old_sub, old_time = physical_gate.subprocess, physical_gate.time
        physical_gate.subprocess = SimpleNamespace(
            Popen=_popen, PIPE=-1, TimeoutExpired=TimeoutError)
        physical_gate.time = SimpleNamespace(sleep=lambda _s: None)
        try:
            with mock.patch.object(physical_gate, "load_machine",
                                   return_value={"openocd_exe": "openocd"}), \
                    mock.patch.object(physical_gate, "resolve_openocd_cfg",
                                      side_effect=cfg_exc,
                                      return_value=None if cfg_exc else
                                      {"interface": "i.cfg", "target": "t.cfg"}):
                return physical_gate.step_physical_gate(
                    self.cfg, timeout=5, workspace=self.tmp.name)
        finally:
            physical_gate.subprocess, physical_gate.time = old_sub, old_time

    def test_disabled_skips(self):
        self.assertEqual(physical_gate.step_physical_gate({"enable": False}, 5),
                         {"status": "skipped"})

    def test_non_positive_expected_rejected(self):
        result = physical_gate.step_physical_gate(
            {"enable": True, "expected_toggles_per_sec": 0}, 5)
        self.assertEqual(result["status"], "probe_error")

    def test_invalid_cfg_reported(self):
        result = self._run(cfg_exc=physical_gate.OpenocdCfgError("bad cfg"))
        self.assertEqual(result["status"], "probe_error")
        self.assertIn("bad cfg", result["error"])

    def test_timeout_all_attempts(self):
        result = self._run(communicate_exc=TimeoutError())
        self.assertEqual(result["status"], "probe_error")
        self.assertIn("timed out", result["error"])

    def test_missing_result_line(self):
        result = self._run(stdout="no marker here")
        self.assertIn("no PHYS_GATE_RESULT", result["error"])

    def test_missing_fail_reads_rejected(self):
        result = self._run(stdout="PHYS_GATE_RESULT samples=10 edges=5 elapsed_ms=100\n")
        self.assertIn("fail_reads", result["error"])

    def test_ok_path(self):
        result = self._run(
            stdout="PHYS_GATE_RESULT samples=100 edges=40 elapsed_ms=10000 fail_reads=0\n")
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["measured_toggles_per_sec"], 4.0)

    def test_timing_fail(self):
        result = self._run(
            stdout="PHYS_GATE_RESULT samples=100 edges=100 elapsed_ms=10000 fail_reads=0\n")
        self.assertEqual(result["status"], "timing_fail")

    def test_insufficient_edges(self):
        result = self._run(
            stdout="PHYS_GATE_RESULT samples=100 edges=2 elapsed_ms=10000 fail_reads=0\n")
        self.assertEqual(result["status"], "insufficient_samples")


class CaptureSimTests(unittest.TestCase):
    def test_config_exe_wins(self):
        self.assertEqual(capture_sim.resolve_qemu({"exe": "q"}), ("q", "config:sim.exe"))

    def test_machine_exe(self):
        with mock.patch("wb_common.load_machine", return_value={"qemu_exe": "mq"}):
            self.assertEqual(capture_sim.resolve_qemu(), ("mq", "machine:qemu_exe"))

    def test_path_fallback(self):
        with mock.patch("wb_common.load_machine", return_value={}), \
                mock.patch.object(capture_sim, "which",
                                  side_effect=lambda n: "/qemu" if n == capture_sim.DEFAULT_QEMU else None):
            self.assertEqual(capture_sim.resolve_qemu(), ("/qemu", "path"))

    def test_default_fallback(self):
        with mock.patch("wb_common.load_machine", return_value={}), \
                mock.patch.object(capture_sim, "which", return_value=None):
            self.assertEqual(capture_sim.resolve_qemu(),
                             (capture_sim.DEFAULT_QEMU, "default"))

    def test_launch_failure_is_actionable(self):
        old = capture_sim.subprocess
        capture_sim.subprocess = SimpleNamespace(
            Popen=lambda *a, **k: (_ for _ in ()).throw(OSError("WinError 2")),
            PIPE=-1, STDOUT=-2, DEVNULL=-3)
        capture_sim.hidden_subprocess_kwargs = lambda: {}
        try:
            with self.assertRaises(RuntimeError) as ctx:
                capture_sim.run_sim_session(1, "m", "k.elf", qemu_exe="q")
        finally:
            capture_sim.subprocess = old
        self.assertIn("qemu 不可启动", str(ctx.exception))


class _Capture(io.StringIO):
    def __init__(self):
        super().__init__()
        self.buffer = io.BytesIO()


class SerialMonitorExtraTests(unittest.TestCase):
    def _main(self, chunks, cfg_encoding="utf-8", argv=()):
        class _Ser:
            def __init__(self):
                self.timeout = None
                self._chunks = list(chunks)
                self.in_waiting = 0

            def read(self, _n):
                return self._chunks.pop(0) if self._chunks else b""

            def close(self):
                pass

        out, err = _Capture(), _Capture()
        cfg = {"port": "COMX", "baudrate": 115200, "encoding": cfg_encoding}
        old = sys.argv
        sys.argv = ["serial_monitor.py", "--port", "COMX", "--timeout", "0.01", *argv]
        try:
            with mock.patch.object(serial_monitor, "resolve_serial_config",
                                   return_value=cfg), \
                    mock.patch.object(serial_monitor, "connect_serial",
                                      return_value=_Ser()), \
                    mock.patch.object(serial_monitor, "update_state_entry"), \
                    redirect_stdout(out), redirect_stderr(err):
                serial_monitor.main()
        finally:
            sys.argv = old
        return out.getvalue()

    def test_bad_encoding_falls_back_to_hex(self):
        out = self._main([b"\xff\xfe\n"], cfg_encoding="no-such-codec")
        self.assertIn("fffe", out)

    def test_cr_continuation_skips_leading_lf(self):
        out = self._main([b"abc\r", b"\ndef\r\n"])
        self.assertIn("abc", out)
        self.assertIn("def", out)
        self.assertEqual(out.splitlines(), ["abc", "def"])

    def test_bad_exclude_regex_exits_one(self):
        err = io.StringIO()
        old = sys.argv
        sys.argv = ["serial_monitor.py", "--port", "COMX", "--exclude", "["]
        try:
            with mock.patch.object(serial_monitor, "resolve_serial_config",
                                   return_value={"port": "x", "baudrate": 1,
                                                 "encoding": "utf-8"}), \
                    redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    serial_monitor.main()
        finally:
            sys.argv = old
        self.assertEqual(ctx.exception.code, 1)


class DurationProfileExtraTests(unittest.TestCase):
    def test_non_numeric_duration_skipped(self):
        by_step, _ = duration_profile._collect_step_durations(
            [{"step_durations": {"build": "abc", "flash": 1.0}}])
        self.assertEqual(by_step["build"], [])
        self.assertEqual(by_step["flash"], [1.0])

    def test_zero_duration_skipped(self):
        by_step, _ = duration_profile._collect_step_durations(
            [{"step_durations": {"build": 0}}])
        self.assertEqual(by_step["build"], [])


if __name__ == "__main__":
    unittest.main()
