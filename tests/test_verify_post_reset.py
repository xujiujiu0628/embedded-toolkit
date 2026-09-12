r"""F-129 (工单二 A-2) 判定后硬件自恢复回归钉。

缺陷背景 (借鉴 agentic-hil 失败自恢复): verify 判定后无论红绿都不复位目标,
超时/卡死场景留下挂着断点或半初始化外设的板子, 污染下一次 verify。

修复后契约:
  1. flash 实际发生过的运行, 判定结束后调 reset_target (红绿都调);
  2. 复位失败只记录 (post_reset: "ok"|"failed"|"skipped"), 绝不改判 verdict;
  3. --no-flash / capture.post_reset:false / flash 未跑成 → "skipped" 且不调;
  4. 早退出口 (build/flash/capture_failed) 无判定, 不复位;
  5. reset_target 判据沿 swd_probe 内容口径: "shutdown command invoked"
     在场且无 "init mode failed" —— 非零退出不否决 (克隆适配器容忍)。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_runtime  # noqa: E402
import verify  # noqa: E402


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class ResetTargetUnitTests(unittest.TestCase):
    """reset_target 纯函数: 内容判据 + 失败只留痕不抛"""

    def _run(self, **kwargs):
        # 只打 subprocess.run —— 整个 subprocess 模块换成 Mock 会把
        # reset_target 里的 except subprocess.TimeoutExpired 一起换掉
        with mock.patch.object(openocd_runtime.subprocess, "run") as m_run:
            m_run.return_value = kwargs.pop(
                "result", _completed(stdout="target halted\n"
                                     "shutdown command invoked\n"))
            if "side_effect" in kwargs:
                m_run.side_effect = kwargs.pop("side_effect")
            rs = openocd_runtime.reset_target("openocd.exe", **kwargs)
        return rs, m_run

    def test_ok_on_shutdown_line(self):
        rs, run = self._run()
        self.assertEqual(rs["status"], "ok")
        cmd = run.call_args[0][0]
        # 命令形态: -f cfg... + -c init / -c "reset run" / -c shutdown
        self.assertEqual(cmd[-5], "init")
        self.assertEqual(cmd[-3], "reset run")
        self.assertEqual(cmd[-1], "shutdown")
        self.assertIn("target/stm32f1x.cfg", cmd)

    def test_custom_cfg_overrides_default(self):
        with mock.patch.object(openocd_runtime.subprocess, "run") as m_run:
            m_run.return_value = _completed(stdout="shutdown command invoked")
            openocd_runtime.reset_target("ocd", ["board/a.cfg", "target/b.cfg"])
        cmd = m_run.call_args[0][0]
        self.assertIn("board/a.cfg", cmd)
        self.assertNotIn("interface/stlink.cfg", cmd)

    def test_init_mode_failed_is_error(self):
        rs, _ = self._run(
            result=_completed(stderr="Error: init mode failed\n"))
        self.assertEqual(rs["status"], "error")

    def test_silent_output_is_error(self):
        # 无 "shutdown command invoked" = 流程没走完, 不判 ok
        rs, _ = self._run(result=_completed(stdout="", stderr=""))
        self.assertEqual(rs["status"], "error")

    def test_timeout_is_error_not_raise(self):
        rs, _ = self._run(
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=20))
        self.assertEqual(rs["status"], "error")
        self.assertIn("超时", rs["message"])

    def test_oserror_is_error_not_raise(self):
        # 本机无 openocd (FileNotFoundError) → error 留痕, 不炸调用方
        rs, _ = self._run(side_effect=FileNotFoundError("openocd"))
        self.assertEqual(rs["status"], "error")

    def test_nonzero_exit_with_shutdown_line_is_ok(self):
        # swd_probe 同款哲学: 克隆适配器偶发非零退出, 内容才是真相
        rs, _ = self._run(
            result=_completed(stdout="shutdown command invoked",
                              returncode=1))
        self.assertEqual(rs["status"], "ok")


class PostResetMainFlowTests(unittest.TestCase):
    """驱动 main() 断言: 调用时机 / verdict 不变 / skip 三路径"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        self.config = {"toolkit_min_version": "0.1", "builder": "gcc",
                       "gcc": {"project": "Makefile", "target": "main",
                               "log_dir": ".workbench/build"}}
        self._write_config()
        # manifest 期望清单: capture 文本缺 "[init] OK" 即判 fail (判 fail 用)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "boot", "texts": ["[init] OK"]},
            ]}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _write_config(self):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(self.config, f)

    def _run(self, extra_args=(), reset_result=None, capture_text="noise"):
        """mock 五步骤 + 复位桩, 驱动 main() 返回 (code, result, reset_mock)"""
        if reset_result is None:
            reset_result = {"status": "ok"}
        argv = ["verify.py", "--project", self.ws, "--json"] + list(extra_args)
        out, err = io.StringIO(), io.StringIO()
        reset_mock = mock.Mock(return_value=dict(reset_result))
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": "s",
                                      "metrics": {"errors": 0, "warnings": 0},
                                      "details": {}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash",
                                  mock.Mock(return_value={
                                      "status": "ok", "stderr": "Verified",
                                      "stdout": ""})), \
                mock.patch.object(verify, "run_semihosting_session",
                                  mock.Mock(return_value=(capture_text, ""))), \
                mock.patch.object(verify, "reset_target", reset_mock), \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    verify.main()
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, json.loads(out.getvalue()), reset_mock

    def test_fail_verdict_still_resets(self):
        # 验收 ①: FAIL 判决后 reset 被调用 (红也复位), post_reset="ok"
        code, result, reset_mock = self._run()  # capture 无期望文本 → fail
        self.assertEqual(result["status"], "fail")
        self.assertEqual(code, 1)
        reset_mock.assert_called_once()
        self.assertEqual(result["post_reset"], "ok")

    def test_ok_verdict_also_resets(self):
        # 绿也复位: 板子状态同样不留给下一次运行
        code, result, reset_mock = self._run(capture_text="[init] OK\n")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(code, 0)
        reset_mock.assert_called_once()
        self.assertEqual(result["post_reset"], "ok")

    def test_reset_failure_keeps_verdict(self):
        # 验收 ②: 复位失败只记录, verdict/退出码纹丝不动
        code, result, _ = self._run(reset_result={"status": "error",
                                                  "message": "no device"})
        self.assertEqual(result["status"], "fail")
        self.assertEqual(code, 1)
        self.assertEqual(result["post_reset"], "failed")
        self.assertEqual(result["steps"]["verify"]["status"], "fail")

    def test_no_flash_skips_reset(self):
        # 验收 ③: --no-flash 路径不触发
        _code, result, reset_mock = self._run(
            extra_args=["--no-flash"], capture_text="[init] OK\n")
        reset_mock.assert_not_called()
        self.assertEqual(result["post_reset"], "skipped")

    def test_config_false_skips_reset(self):
        # 验收 ④: capture.post_reset: false 显式关闭
        self.config["capture"] = {"post_reset": False}
        self._write_config()
        _code, result, reset_mock = self._run(capture_text="[init] OK\n")
        reset_mock.assert_not_called()
        self.assertEqual(result["post_reset"], "skipped")

    def test_flash_failure_skips_reset(self):
        # flash 没跑成 (早退, 无判定) → 不复位, 复位桩零调用
        argv = ["verify.py", "--project", self.ws, "--json"]
        out, err = io.StringIO(), io.StringIO()
        reset_mock = mock.Mock(return_value={"status": "ok"})
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": "s",
                                      "metrics": {"errors": 0, "warnings": 0},
                                      "details": {}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash",
                                  mock.Mock(return_value={
                                      "status": "error", "stderr": "swd"})), \
                mock.patch.object(verify, "reset_target", reset_mock), \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit):
                    verify.main()
        reset_mock.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "flash_failed")
        self.assertNotIn("post_reset", result,
                         "早退出口无判定, 不得出现复位字段")


if __name__ == "__main__":
    unittest.main()
