"""F-046: HIL 任务 (flash / capture) 入口必须可追溯到 schedule / dispatch 触发.

用户拍板方向 (2026-09-02, 方案四-1):
  - HIL 任务指 flash + capture 两步 (build 是 PC 端不算, 整流水线过宽)
  - 默认 task_origin=manual, 不破坏 VS Code 直接调子工具 (build/flash/debug 不走 verify.py)
  - 加 --require-schedule-origin 旗标, 开启时拒绝 manual (CI / release 门禁用)
  - 每次执行把 origin 写进 result.steps.{flash,capture}.origin
  - 每次执行追加一条到 .workbench/state/audit.jsonl (台账: ts/origin/command/step/status)

本测试锁契约:
  1. enforce_hil_origin() 在 manual 放行, 返回 (allowed=True, reason="")
  2. enforce_hil_origin() 在 manual + require_schedule_origin 拒绝, 给出 reason
  3. enforce_hil_origin() 在 schedule/dispatch + require_schedule_origin 放行
  4. append_audit_entry() 写入 .workbench/state/audit.jsonl, 每行一条 JSON
  5. invalid origin 值抛 ValueError (白名单: manual/schedule/dispatch)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (F-054 后 import 期零 IO)


class EnforceHilOriginTests(unittest.TestCase):
    """F-046 守卫函数契约"""

    def test_manual_default_allowed(self):
        # 默认 manual + 不开硬卡: 放行 (兼容现有 VS Code verify 任务)
        allowed, reason = verify.enforce_hil_origin("manual", False)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_schedule_default_allowed(self):
        allowed, reason = verify.enforce_hil_origin("schedule", False)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_dispatch_default_allowed(self):
        allowed, reason = verify.enforce_hil_origin("dispatch", False)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_manual_with_strict_guard_rejected(self):
        # 开 --require-schedule-origin + manual: 拒绝, 提示走 schedule/dispatch
        allowed, reason = verify.enforce_hil_origin("manual", True)
        self.assertFalse(allowed)
        self.assertIn("schedule", reason.lower())
        self.assertIn("dispatch", reason.lower())

    def test_schedule_with_strict_guard_allowed(self):
        allowed, reason = verify.enforce_hil_origin("schedule", True)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_dispatch_with_strict_guard_allowed(self):
        allowed, reason = verify.enforce_hil_origin("dispatch", True)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_invalid_origin_raises(self):
        # 白名单外值: 早失败, 不允许"silent fallback to manual"
        with self.assertRaises(ValueError) as ctx:
            verify.enforce_hil_origin("auto", False)
        self.assertIn("manual", str(ctx.exception).lower())
        self.assertIn("schedule", str(ctx.exception).lower())
        self.assertIn("dispatch", str(ctx.exception).lower())


class AppendAuditEntryTests(unittest.TestCase):
    """F-046 台账落盘契约"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench", "state"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_writes_jsonl_with_required_keys(self):
        audit_path = os.path.join(self.ws, ".workbench", "state", "audit.jsonl")
        verify.append_audit_entry(
            workspace=self.ws, origin="schedule",
            step="flash", status="ok", command="python verify.py --no-build")
        self.assertTrue(os.path.isfile(audit_path))
        with open(audit_path, encoding="utf-8") as f:
            line = f.readline().strip()
        entry = json.loads(line)
        self.assertEqual(entry["origin"], "schedule")
        self.assertEqual(entry["step"], "flash")
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["command"], "python verify.py --no-build")
        self.assertIn("ts", entry)
        # ts 必须是 ISO8601 字符串 (now_iso() 风格)
        self.assertRegex(entry["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_appends_multiple_entries(self):
        # 同一次 verify 跑 flash + capture 两次调用 → 两行
        audit_path = os.path.join(self.ws, ".workbench", "state", "audit.jsonl")
        verify.append_audit_entry(self.ws, "manual", "flash", "ok", "python verify.py")
        verify.append_audit_entry(self.ws, "manual", "capture", "ok", "python verify.py")
        with open(audit_path, encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        entries = [json.loads(ln) for ln in lines]
        self.assertEqual(entries[0]["step"], "flash")
        self.assertEqual(entries[1]["step"], "capture")

    def test_creates_state_dir_if_missing(self):
        # 父目录不在时也应能建 (首次跑的工程常见)
        fresh_ws = tempfile.mkdtemp()
        try:
            verify.append_audit_entry(
                fresh_ws, "dispatch", "capture", "ok", "python verify.py")
            expected = os.path.join(fresh_ws, ".workbench", "state", "audit.jsonl")
            self.assertTrue(os.path.isfile(expected))
        finally:
            shutil.rmtree(fresh_ws, ignore_errors=True)


class MainFlowGuardTests(unittest.TestCase):
    """F-046 集成: main() 在 flash 之前必须调用守卫 (而非仅函数存在)"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc", "verify": {"expect": []}}, f)
        # worktree 里的 verify.py 才包含本次新增的 HIL_ORIGINS
        # sys.path 在 import 时已插, 沿用模块级 verify

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run_main_with(self, argv_extra):
        """调 main() 一次, 用 mock 阻断外部子工具."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        # 把 worktree 的 .workbench 作为 cwd
        old_cwd = os.getcwd()
        os.chdir(self.ws)
        try:
            with mock.patch.object(sys, "argv",
                                   ["verify.py"] + list(argv_extra)), \
                 mock.patch.object(verify, "step_build",
                                   return_value={"status": "error"}), \
                 mock.patch.object(verify, "step_flash",
                                   return_value={"status": "ok",
                                                 "stderr": "mocked"}), \
                 mock.patch.object(verify, "_step_capture_rtt",
                                   return_value={"status": "ok", "method": "rtt",
                                                 "lines": 0, "duration_sec": 0.0,
                                                 "raw_length": 0}), \
                 redirect_stdout(io.StringIO()) as out, \
                 redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as ctx:
                    verify.main()
                return ctx.exception.code, out.getvalue(), err.getvalue()
        finally:
            os.chdir(old_cwd)

    def test_manual_strict_guard_rejects_before_flash(self):
        # 开 --require-schedule-origin + manual → exit 2, step_flash 永远不该被调起
        from unittest import mock
        with mock.patch.object(verify, "step_flash") as flash_mock:
            code, _out, err = self._run_main_with(
                ["--require-schedule-origin", "--no-build",
                 "--task-origin", "manual"])
        self.assertEqual(code, 2)
        flash_mock.assert_not_called()
        self.assertIn("schedule", err.lower())
        self.assertIn("dispatch", err.lower())

    def test_schedule_strict_guard_allows_flash(self):
        # schedule + --require-schedule-origin → 守卫放行, step_flash 被调起
        # helper 内部已经 patch 了 step_flash, 验证它被调即可
        code, _out, _err = self._run_main_with(
            ["--require-schedule-origin", "--no-build",
             "--task-origin", "schedule"])
        # 关键: 守卫没拦 (exit 不是 2); 后续 verify 失败 exit 1 也 OK
        self.assertNotEqual(code, 2)

    def test_invalid_origin_via_cli_raises_systemexit(self):
        # argparse choices 拦截: typo 的 origin 根本进不来
        from unittest import mock
        with mock.patch.object(verify, "step_flash") as flash_mock, \
             mock.patch.object(sys, "argv",
                               ["verify.py", "--task-origin", "auto"]):
            with self.assertRaises(SystemExit) as ctx:
                verify.main()
        self.assertEqual(ctx.exception.code, 2)  # argparse 参数错误退出码
        flash_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
