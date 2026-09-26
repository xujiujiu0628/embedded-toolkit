"""esp_runtime (F-174) — ESP32-S3 三后端的 host 单测, 零真机零 IO。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime


class RunIdfTests(unittest.TestCase):
    def _fake_run(self, rc=0, out="hello", err=""):
        seen = {}
        def fake(cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw
            return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
        return fake, seen

    def test_builds_powershell_with_export_and_gate(self):
        fake, seen = self._fake_run()
        with mock.patch.object(esp_runtime, "resolve_idf_path",
                               return_value=r"D:\idf\esp-idf"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py build"], timeout=900,
                                    workspace=r"W:", _run=fake)
        self.assertEqual(r["status"], "ok")
        script = seen["cmd"][-1]                      # -Command 后的脚本文本
        self.assertIn(". 'D:/idf/esp-idf/export.ps1'", script)  # 正斜杠 (PS 不处理反斜杠转义)
        self.assertIn("idf.py build", script)
        self.assertIn("$LASTEXITCODE", script)         # 逐命令退出码门闩
        self.assertEqual(seen["cmd"][:3], ["powershell", "-NoProfile", "-ExecutionPolicy"])
        self.assertEqual(seen["kw"]["cwd"], "W:")

    def test_nonzero_rc_is_error_not_fail_open(self):
        # F-090 同源纪律: 输出里全是漂亮话, rc!=0 必须 error
        fake, _ = self._fake_run(rc=2, out="Hash of data verified")
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py flash"], 60, "W:", _run=fake)
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["returncode"], 2)

    def test_timeout_returns_message(self):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=1)
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["x"], 1, "W:", _run=boom)
        self.assertEqual(r["status"], "error")
        self.assertIn("超时", r["message"])


    def test_export_path_single_quote_escaped(self):
        # Task 2 审查裁决: PS 单引号串内 ' 须翻倍转义, 防路径注入/断串
        fake, seen = self._fake_run()
        with mock.patch.object(esp_runtime, "resolve_idf_path",
                               return_value=r"D:\id'f\esp-idf"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            esp_runtime.run_idf(["idf.py build"], timeout=900,
                                workspace=r"W:", _run=fake)
        script = seen["cmd"][-1]
        self.assertIn("D:/id''f/esp-idf/export.ps1", script)


    def test_idf_env_strips_msys_markers(self):
        # F-174 真机裁决: Git Bash 起跑的 CC 会把 MSYSTEM/MINGW* 带进子环境,
        # IDF export 检测到即拒绝激活 ("MSys/Mingw is not supported")
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_tools_dir": "T"}),              mock.patch.dict(os.environ, {"MSYSTEM": "MINGW64",
                                          "MINGW_PREFIX": "/mingw64",
                                          "MSYS": "x", "KEEP_ME": "k"}):
            env = esp_runtime._idf_env()
        for k in ("MSYSTEM", "MINGW_PREFIX", "MSYS"):
            self.assertNotIn(k, env)
        self.assertEqual(env["IDF_TOOLS_PATH"], "T")
        self.assertEqual(env.get("KEEP_ME"), "k")   # 非 MSYS 系键不误伤


class ResolveIdfPathTests(unittest.TestCase):
    def test_missing_key_raises(self):
        with mock.patch.object(esp_runtime, "load_machine", return_value={}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_nonexistent_dir_raises(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": r"Q:\nope"}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_ok_path_returns_it(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": os.getcwd()}):
            self.assertEqual(esp_runtime.resolve_idf_path(), os.getcwd())


class PanicMarkerTests(unittest.TestCase):
    def test_markers(self):
        self.assertTrue(esp_runtime.detect_esp_panic("Guru Meditation Error: Core 0"))
        self.assertTrue(esp_runtime.detect_esp_panic("Backtrace: 0x4037abcd:0x3fc..."))
        self.assertTrue(esp_runtime.detect_esp_panic("abort() was called at PC ..."))
        self.assertFalse(esp_runtime.detect_esp_panic("ESP-PILOT-OK tick=1"))


class StepBuildIdfTests(unittest.TestCase):
    """mock run_idf + tmpdir 产物, 钉: 命令装配/日志落盘/metrics/state.json 契约。"""

    def _ws(self, td, with_artifacts=True):
        os.makedirs(os.path.join(td, "build"), exist_ok=True)
        os.makedirs(os.path.join(td, ".workbench"), exist_ok=True)
        if with_artifacts:
            open(os.path.join(td, "build", "esp32s3_hello.bin"), "w").close()
            open(os.path.join(td, "build", "esp32s3_hello.elf"), "w").close()
        return td

    def test_success_contract(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({"idf": {}}, workspace=ws,
                                           _run_idf=lambda c, **kw: {
                        "status": "ok", "returncode": 0,
                        "output": "Executing idf.py build\nDone\n"})
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["metrics"], {"errors": 0, "warnings": 0})
            self.assertEqual(r["details"]["hex_file"], "build/esp32s3_hello.bin")
            self.assertEqual(r["details"]["elf_file"], "build/esp32s3_hello.elf")
            self.assertTrue(os.path.isfile(os.path.join(
                ws, r["details"]["log_file"])))          # 日志落盘
            with open(os.path.join(ws, ".workbench", "state.json"),
                      encoding="utf-8") as f:
                lb = json.load(f)["last_build"]
            self.assertEqual(lb["provider"], "idf")
            self.assertEqual(lb["hex_file"], "build/esp32s3_hello.bin")  # verify --no-build 回读键

    def test_error_line_counted_and_status_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "error", "returncode": 2,
                "output": "main.c:5:1: error: 'foo' undeclared\nninja: build stopped\n"})
            self.assertEqual(r["status"], "error")
            self.assertEqual(r["metrics"]["errors"], 1)

    def test_rc_zero_but_error_line_still_error(self):
        # rc=0 但日志含 error: → 不许按成功入账 (F-090 判据的补充证据方向)
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "cc1: error: bad\n"})
            self.assertEqual(r["status"], "error")

    def test_no_bin_artifact_errors(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td, with_artifacts=False)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "Done\n"})
            self.assertEqual(r["status"], "error")
            self.assertIn("bin", r["summary"].lower())

    def test_rebuild_prepends_fullclean(self):
        seen = []
        def spy(cmds, **kw):
            seen.append(list(cmds))
            return {"status": "ok", "returncode": 0, "output": "Done\n"}
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            esp_runtime.step_build_idf({}, rebuild=True, workspace=ws, _run_idf=spy)
        self.assertEqual(seen[0], ["idf.py fullclean", "idf.py build"])


class StepFlashEsptoolTests(unittest.TestCase):
    def test_port_required(self):
        r = esp_runtime.step_flash_esptool({}, workspace="W:")
        self.assertEqual(r["status"], "error")
        self.assertIn("port", r["message"])

    def test_command_assembly_and_rc(self):
        seen = []
        def spy(cmds, **kw):
            seen.append((cmds, kw.get("timeout")))
            return {"status": "ok", "returncode": 0,
                    "output": "Hash of data verified.\nHard resetting via RTS pin..."}
        r = esp_runtime.step_flash_esptool({"port": "COM3", "timeout": 120},
                                           workspace=r"W:", _run_idf=spy)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(seen[0][0], ["idf.py -p COM3 flash"])  # 地址表由 idf flash_args 管理
        self.assertEqual(seen[0][1], 120)

    def test_rc_fail_carries_stderr_tail(self):
        r = esp_runtime.step_flash_esptool(
            {"port": "COM9"}, workspace="W:",
            _run_idf=lambda c, **kw: {"status": "error", "returncode": 2,
                                      "output": "x" * 600 + "could not open port"})
        self.assertEqual(r["status"], "error")
        self.assertIn("COM9", r["message"])
        self.assertIn("could not open port", r["stderr"])


class StepCaptureUartTests(unittest.TestCase):
    """假串口: readline 依序吐预制行, 到空后按墙钟截止。"""

    def _fake_serial(self, lines):
        import serial as _s
        class FakeSer:
            def __init__(self, *a, **kw): self.i = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                if self.i < len(lines):
                    self.i += 1
                    return lines[self.i - 1].encode()
                raise _s.SerialException("done-for-test")
        return FakeSer

    def test_missing_port_errors(self):
        r = esp_runtime.step_capture_uart(5, {}, workspace="W:")
        self.assertEqual(r["status"], "error")
        self.assertIn("capture.port", r["error"])

    def test_reset_then_capture_then_contract(self):
        seen = []
        def spy(cmds, **kw):
            seen.append(cmds)
            return {"status": "ok", "returncode": 0, "output": "Chip type: ESP32-S3"}
        lines = ["ESP-PILOT-BOOT ok", "ESP-PILOT-OK tick=0 heap=123", ""]
        with mock.patch("serial.Serial", self._fake_serial(lines)), \
             mock.patch.object(esp_runtime.time, "sleep"):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "baudrate": 115200, "settle_sec": 0},
                workspace="W:", _run_idf=spy)
        # 第 4 次 readline 抛 SerialException("done-for-test") → 端口故障即 error,
        # 错误原文可读 (COM3 被占/拔线就是这个出口)
        self.assertEqual(r["status"], "error")
        self.assertIn("done-for-test", r["error"])
        self.assertIn("esptool", seen[0][0])      # 复位先行 (chip_id 廉价只读)
        self.assertIn("--after hard_reset", seen[0][0])  # IDF v4 只认下划线 (真机裁决)

    def test_happy_path_text_and_panic_flag(self):
        class OkSer:
            def __init__(self, *a, **kw): self.n = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                self.n += 1
                if self.n == 1: return b"ESP-PILOT-OK tick=0\n"
                return b""      # 静默, 等 deadline
        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])   # deadline 走秒
        with mock.patch("serial.Serial", lambda *a, **kw: OkSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time", lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["method"], "uart")
        self.assertEqual(r["_text"], "ESP-PILOT-OK tick=0")
        self.assertFalse(r["esp_panic"])

    def test_panic_marked_not_fatal(self):
        class PanicSer:
            def __init__(self, *a, **kw): self.n = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                self.n += 1
                if self.n == 1: return b"Guru Meditation Error: Core 0 panic'ed\n"
                return b""
        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])
        with mock.patch("serial.Serial", lambda *a, **kw: PanicSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time", lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")      # panic 不拦截采集 (交 AI judge 定性)
        self.assertTrue(r["esp_panic"])

    def test_reset_failure_short_circuits(self):
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3"}, workspace="W:",
            _run_idf=lambda c, **kw: {"status": "error", "message": "超时 (5s)"})
        self.assertEqual(r["status"], "error")
        self.assertIn("复位失败", r["error"])

    def test_handshake_released_before_first_read_f177(self):
        """F-177: pyserial 开串口默认断言 DTR/RTS——CH340/CP210x 自动下载
        电路把这对组合等价于拉低 EN, 芯片被按在复位里, 采集静默收 0 行
        (初代 esp32 真机首跑钓出; S3 原生 USB CDC 无此电气通路, 故 F-174
        未触达)。执行序钉: 释放必须发生在第一次 readline 之前。"""
        events = ["open"]

        class BridgeSer:
            def __init__(self, *a, **kw):
                self._dtr = True
                self._rts = True

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            @property
            def dtr(self):
                return self._dtr

            @dtr.setter
            def dtr(self, v):
                events.append(f"dtr={v}")
                self._dtr = v

            @property
            def rts(self):
                return self._rts

            @rts.setter
            def rts(self, v):
                events.append(f"rts={v}")
                self._rts = v

            def readline(self):
                events.append("read")
                return b""

        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])
        with mock.patch("serial.Serial", lambda *a, **kw: BridgeSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time",
                               lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM8", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")
        first_read = events.index("read")
        self.assertEqual(events[:first_read],
                         ["open", "dtr=False", "rts=False"])

    def test_handshake_release_unsupported_tolerated(self):
        """部分 CDC 设备不支持设控制线 (property 无 setter →
        AttributeError)——吞掉继续采集, 不得把 S3 路径搞红。"""
        class CdcSer:
            def __init__(self, *a, **kw):
                self.n = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            dtr = property(None, None)
            rts = property(None, None)

            def readline(self):
                self.n += 1
                return b"tick 0\n" if self.n == 1 else b""

        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])
        with mock.patch("serial.Serial", lambda *a, **kw: CdcSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time",
                               lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["_text"], "tick 0")

    def test_serialexception_keeps_partial_lines(self):
        """F-192/N-5 (WB-20260926-03 T4): SerialException 路径携带已收行
        入账 — 形态对齐 F-003 超时路径的部分输出信封 (lines 计数 +
        partial_output), status 仍 fail-closed; esp_panic 标记随部分输出
        保留 (定性交 AI judge, 不因采集故障翻绿)。

        打桩形态注: esp_runtime 的 serial 是函数内 import (无模块级引用
        可替换), 且 test_stub_ratchet 棘轮禁新增 mock.patch("serial.Serial")
        全局桩 — 故走 patch.dict(sys.modules) 注入假 serial 模块
        (保存/恢复式, F-184 模块引用替换哲学在 import 缝上的形态)。"""
        class FakeSerialError(Exception):
            pass

        class BoomAfter3:
            def __init__(self, *a, **kw):
                self.n = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def readline(self):
                self.n += 1
                if self.n == 1:
                    return b"ESP-BOOT ok\n"
                if self.n == 2:
                    return b"Guru Meditation Error: Core 0 panic'ed\n"
                if self.n == 3:
                    return b"tick=2\n"
                raise FakeSerialError("device returned no data")

        fake_serial = SimpleNamespace(Serial=BoomAfter3,
                                      SerialException=FakeSerialError)
        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])
        with mock.patch.dict(sys.modules, {"serial": fake_serial}), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time",
                               lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        # fail-closed 不翻绿: status error (verify 侧 capture_failed 语义不变)
        self.assertEqual(r["status"], "error")
        self.assertIn("COM3", r["error"])
        self.assertIn("device returned no data", r["error"])
        # 已收 3 行入账 (修前丢弃 → 红)
        self.assertEqual(r["lines"], 3)
        self.assertIn("ESP-BOOT ok", r["partial_output"])
        self.assertIn("tick=2", r["partial_output"])
        # panic 标记随部分输出保留
        self.assertTrue(r["esp_panic"])
        # 信封形态对齐 F-003: 错误面走 partial_output, 不带 _text 私有键
        self.assertNotIn("_text", r)


if __name__ == "__main__":
    unittest.main()
