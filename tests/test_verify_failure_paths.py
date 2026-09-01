"""失败路径留痕回归 (F-002 / F-003 / F-004, 2026-08-30 代管 Day 2).

用户认可方向: "失败路径必须留痕" — 成功路径 90 分之外, 失败路径不许静默。
- F-002: 损坏 config.json → ConfigError 友好错误 (非裸 traceback)
- F-003: OpenOCD 卡死超时 → 回收部分输出 + capture_failed (非谎报"程序无输出")
- F-004: 反馈落账三条路径 (成功/门禁跳过/落账失败) 全部在 result.feedback 留痕
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (import 期读 machine.json, 本机存在)


class ConfigErrorTests(unittest.TestCase):
    """F-002: 工程配置损坏必须 ConfigError, 与 M1 的 ExpectationError 同款拦截"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_broken_json_raises_config_error(self):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            f.write("{broken")
        with self.assertRaises(verify.ConfigError):
            verify.load_config(self.ws)

    def test_non_utf8_raises_config_error(self):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "wb") as f:
            f.write(b'{"a": "\xff\xfe"}')
        with self.assertRaises(verify.ConfigError):
            verify.load_config(self.ws)

    def test_valid_config_still_loads(self):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        self.assertEqual(verify.load_config(self.ws)["builder"], "gcc")

    def test_missing_marker_still_filenotfound(self):
        # 无任何 marker 文件时错误语义不变 (工程根发现层负责, 非本函数)
        with self.assertRaises(FileNotFoundError):
            verify.load_config(self.ws)


class CaptureLineFilterTests(unittest.TestCase):
    """F-003 前置: 行过滤口径抽取为共享函数, 正常结束/超时收尸两路共用"""

    def test_filters_openocd_log_lines(self):
        raw = "Info :Listening on port 4444\r\nLED ON\r\nWarn : something\r\nTGL 3\r\n"
        self.assertEqual(verify._filter_capture_lines(raw), ["LED ON", "TGL 3"])

    def test_filters_status_keywords(self):
        raw = "target state: halted\nshutdown command invoked\nboot ok"
        self.assertEqual(verify._filter_capture_lines(raw), ["boot ok"])

    def test_keeps_hardfault_marker(self):
        # HARDFAULT 标记行绝不能被过滤 (verify Step 4b 靠它触发诊断)
        self.assertEqual(verify._filter_capture_lines("=== HARDFAULT ==="),
                         ["=== HARDFAULT ==="])


class CaptureTimeoutTests(unittest.TestCase):
    """F-003: 超时必须回收部分输出并 capture_failed, 不再谎报 ok/lines=0"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        old = verify.WORKSPACE
        verify.WORKSPACE = self.tmp  # _save_failure_context 落盘位置
        self.addCleanup(setattr, verify, "WORKSPACE", old)

    def test_timeout_reports_capture_failed_with_partial_output(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("LED ON\r\nInfo : x\r\n", "TGL 3\r\n")
        result = {"steps": {}, "status": None}
        with self.assertRaises(SystemExit) as cm:
            verify._finish_capture_timeout(proc, result, 10, 0, as_json=True)
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(result["status"], "capture_failed")
        cap = result["steps"]["capture"]
        self.assertEqual(cap["status"], "error")
        self.assertEqual(cap["lines"], 2)  # LED ON + TGL 3, Info 行被过滤
        self.assertIn("LED ON", cap["partial_output"])
        self.assertIn("TGL 3", cap["partial_output"])
        self.assertNotIn("Info", cap["partial_output"])
        # 失败现场 (last_failure.json) 也必须带部分输出
        with open(os.path.join(self.tmp, ".workbench", "build",
                               "last_failure.json"), encoding="utf-8") as f:
            ctx = json.load(f)
        self.assertIn("LED ON", ctx["captured_output"])

    def test_timeout_with_unrecyclable_output_still_fails_honestly(self):
        proc = mock.Mock()
        proc.communicate.side_effect = OSError("process dead")
        result = {"steps": {}, "status": None}
        with self.assertRaises(SystemExit):
            verify._finish_capture_timeout(proc, result, 10, 0, as_json=True)
        self.assertEqual(result["status"], "capture_failed")
        self.assertEqual(result["steps"]["capture"]["lines"], 0)


class FeedbackLoggingTests(unittest.TestCase):
    """F-004: 落账成功/门禁跳过/落账失败三条路径全部留痕于 result.feedback"""

    def _result(self):
        return {"status": "ok",
                "steps": {"build": {"status": "ok", "errors": 0, "warnings": 1}}}

    def test_gate_run_marks_skipped_with_reason(self):
        state = verify._log_feedback_event(self._result(), gate_run=True)
        self.assertFalse(state["logged"])
        self.assertTrue(state["skipped"])
        self.assertIn("gate_run", state["reason"])

    @mock.patch.object(verify.subprocess, "run")
    def test_success_logs_event_id_and_semantics(self, m_run):
        m_run.return_value = mock.Mock(
            returncode=0, stdout='{"status":"ok","event_id":"bf_1"}', stderr="")
        state = verify._log_feedback_event(self._result(), gate_run=False)
        self.assertTrue(state["logged"])
        self.assertEqual(state["event_id"], "bf_1")
        event = json.loads(m_run.call_args.args[0][3])
        self.assertEqual(event["pipeline"], "build_fix")
        self.assertEqual(event["outcome"], "fixed")     # ok 且无 hardfault
        self.assertEqual(event["verify_result"], "pass")
        self.assertEqual(event["build_result"], "0e1w")  # _build_result_str 语义不变

    @mock.patch.object(verify.subprocess, "run")
    def test_hardfault_outcome_still_broken(self, m_run):
        m_run.return_value = mock.Mock(returncode=0,
                                       stdout='{"event_id":"hf_1"}', stderr="")
        r = self._result()
        r["status"] = "hardfault"
        r["steps"]["hardfault"] = {"fault_type": "BusFault"}
        state = verify._log_feedback_event(r, gate_run=False)
        self.assertTrue(state["logged"])
        event = json.loads(m_run.call_args.args[0][3])
        self.assertEqual(event["pipeline"], "hardfault")
        self.assertEqual(event["outcome"], "still_broken")
        self.assertEqual(event["fault_type"], "BusFault")

    @mock.patch.object(verify.subprocess, "run")
    def test_failure_exit_code_recorded_not_swallowed(self, m_run):
        # F-001 场景回归: feedback_db exit 1 不再无痕, error 全文入档
        m_run.return_value = mock.Mock(returncode=1, stdout="",
                                       stderr="Error: 未找到工程根")
        state = verify._log_feedback_event(self._result(), gate_run=False)
        self.assertFalse(state["logged"])
        self.assertIn("未找到工程根", state["error"])

    @mock.patch.object(verify.subprocess, "run")
    def test_subprocess_timeout_recorded(self, m_run):
        m_run.side_effect = subprocess.TimeoutExpired(cmd="feedback_db", timeout=10)
        state = verify._log_feedback_event(self._result(), gate_run=False)
        self.assertFalse(state["logged"])
        self.assertIn("TimeoutExpired", state["error"])

    @mock.patch.object(verify.subprocess, "run")
    def test_unexpected_exception_recorded(self, m_run):
        m_run.side_effect = OSError("spawn failed")
        state = verify._log_feedback_event(self._result(), gate_run=False)
        self.assertFalse(state["logged"])
        self.assertIn("OSError", state["error"])


class StepFlashNoArtifactTests(unittest.TestCase):
    """F-007: --no-build 无产物时明确报错, 不再回落 blink 退役残留 obj/blink.hex"""

    def setUp(self):
        old = verify.WORKSPACE
        verify.WORKSPACE = tempfile.mkdtemp()
        self.addCleanup(setattr, verify, "WORKSPACE", old)
        self.addCleanup(shutil.rmtree, verify.WORKSPACE, ignore_errors=True)

    def test_empty_hex_rejected_with_clear_message(self):
        r = verify.step_flash("")
        self.assertEqual(r["status"], "error")
        self.assertIn("hex", r["message"])
        self.assertNotIn("blink", r["message"])

    def test_nonexistent_hex_still_rejected(self):
        r = verify.step_flash("no/such/file.hex")
        self.assertEqual(r["status"], "error")
        self.assertIn("no/such/file.hex", r["message"])


class RttSpawnFlagsPlatformTests(unittest.TestCase):
    """F-031 (F-027 的运行时姊妹钉): _step_capture_rtt 的 spawn 旗标必须随平台适配。

    F-027 的静态钉管"裸用常量须有守卫同行" (属性级); 本测试管派发行为 (kwargs 级):
    Linux 模拟下 creationflags 必为 0 —— 裸常量在该平台连属性都不存在 (P0 崩溃类),
    win32 模拟下必传真实常量。假 Popen 进程即死, 顺带钉住 3 重试骨架与 error 如实上报。
    """

    class _DeadProc:
        def __init__(self):
            self.stderr = io.StringIO("")

        def poll(self):
            return 1

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 1

    def _capture_calls(self, platform_str):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(kwargs)
            return self._DeadProc()

        with mock.patch.object(verify.sys, "platform", platform_str), \
                mock.patch.object(verify.subprocess, "Popen", fake_popen), \
                mock.patch.object(verify.time, "sleep", lambda s: None):
            out = verify._step_capture_rtt(1, {})
        self.assertEqual(out["status"], "error")  # 进程即死必须如实 error, 不假绿
        self.assertEqual(len(calls), 3, "ST-Link 竞态 3 重试纪律同钉")
        return calls

    def test_linux_sim_uses_zero_creationflags(self):
        for kw in self._capture_calls("linux"):
            self.assertEqual(
                kw["creationflags"], 0,
                "Linux 模拟下 creationflags 必须为 0 (F-027 崩溃类回归钉)")

    @unittest.skipUnless(hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"),
                         "本机无 Windows 常量")
    def test_win32_sim_passes_real_constant(self):
        for kw in self._capture_calls("win32"):
            self.assertEqual(kw["creationflags"],
                             subprocess.CREATE_NEW_PROCESS_GROUP)


if __name__ == "__main__":
    unittest.main()
