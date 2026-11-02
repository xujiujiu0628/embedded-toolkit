r"""F-237: CLI 入口的进程内调用补测（覆盖率可计量）。

## 为什么另起一层

`tests/test_f237_*.py` 里的 CLI 用例走子进程，验证的是**真实退出码**；
但 `coverage run` 默认不追踪子进程，那些行在报告里仍是未覆盖。本文件在
进程内调 `main()`（patched argv + 重定向 stdout/stderr + 捕获 SystemExit），
让 CLI 分支真正进入覆盖率账本。两层并存：子进程钉 rc，进程内钉覆盖。

## 纪律

- 每个用例跑完恢复 `sys.argv` / cwd / 模块全局（`cube_usercode` 有
  `_bind_roots` 缓存，必须复位，否则用例间互相污染）；
- 断言看真实输出片段，不只看"没抛异常"。
"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import cube_usercode  # noqa: E402
import feedback_db  # noqa: E402
import phase_minus_one  # noqa: E402
import svd_to_json  # noqa: E402

MINI_SVD = """<?xml version="1.0" encoding="utf-8"?>
<device><peripherals>
  <peripheral>
    <name>GPIOA</name><description>GPIO</description><baseAddress>0x40010800</baseAddress>
    <registers>
      <register><name>CRL</name><addressOffset>0x00</addressOffset></register>
    </registers>
  </peripheral>
</peripherals></device>
"""


def _call(main_func, *argv):
    """进程内调 main(): 返回 (rc, stdout, stderr)；SystemExit 转 rc。

    直接赋值 sys.argv 并在 finally 恢复，不用 ``mock.patch.object(sys, ...)``
    —— 后者会被 test_stub_ratchet 记为新增全局打桩（B 式）；本层只需要
    一个可恢复的 argv 替换，不涉及全局库对象置桩。
    """
    old_argv = sys.argv
    sys.argv = ["prog", *argv]
    out, err = StringIO(), StringIO()
    rc = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = main_func()
            except SystemExit as exc:
                rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return rc, out.getvalue(), err.getvalue()


class SvdCliInProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svd = os.path.join(self.tmp.name, "mini.svd")
        with open(self.svd, "w", encoding="utf-8") as fh:
            fh.write(MINI_SVD)

    def test_missing_svd_exits_one(self):
        rc, _, err = _call(svd_to_json.main, "--svd", os.path.join(self.tmp.name, "no.svd"), "--list")
        self.assertEqual(rc, 1)
        self.assertIn("SVD file not found", err)

    def test_list_prints_peripheral(self):
        rc, out, _ = _call(svd_to_json.main, "--svd", self.svd, "--list")
        self.assertIsNone(rc)
        self.assertIn("GPIOA", out)

    def test_periph_json(self):
        rc, out, _ = _call(svd_to_json.main, "--svd", self.svd, "--periph", "GPIOA", "--json")
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["GPIOA"]["base"], "0x40010800")

    def test_periph_missing_exits_one(self):
        rc, _, err = _call(svd_to_json.main, "--svd", self.svd, "--periph", "NOPE")
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_all_to_out_dir(self):
        out_dir = os.path.join(self.tmp.name, "out")
        rc, out, _ = _call(svd_to_json.main, "--svd", self.svd, "--all", "--out", out_dir)
        self.assertIsNone(rc)
        self.assertIn("Extracted 1 peripherals", out)
        self.assertEqual(os.listdir(out_dir), ["gpioa.json"])

    def test_no_action_prints_help(self):
        rc, out, _ = _call(svd_to_json.main, "--svd", self.svd)
        self.assertIsNone(rc)
        self.assertIn("--periph", out)


class PhaseMinusOneCliInProcessTests(unittest.TestCase):
    def test_list(self):
        rc, out, _ = _call(phase_minus_one.main, "--list")
        self.assertIsNone(rc)
        self.assertIn("FULL:", out)

    def test_no_arguments_prints_help(self):
        rc, out, _ = _call(phase_minus_one.main)
        self.assertIsNone(rc)
        self.assertIn("Example:", out)

    def test_known_peripheral_json(self):
        rc, out, _ = _call(phase_minus_one.main, "-p", "USART1", "--json")
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["checks"]["kb_coverage"]["status"], "FULL")

    def test_unavailable_peripheral_blocks(self):
        rc, out, _ = _call(phase_minus_one.main, "-p", "DAC", "--json")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["verdict"], "BLOCKED")


class FeedbackDbCliInProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, ".workbench"))
        with open(os.path.join(self.tmp.name, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        self._old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._old_cwd)

    def test_log_then_stats(self):
        payload = json.dumps({"pipeline": "build_fix", "error_code": "E09", "outcome": "fixed"})
        rc, out, _ = _call(feedback_db.main, "--log", payload)
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["status"], "ok")
        rc, out, _ = _call(feedback_db.main, "--stats", "build_fix")
        self.assertEqual(json.loads(out)["total_events"], 1)

    def test_calibrate(self):
        _call(feedback_db.main, "--log", json.dumps(
            {"pipeline": "hardfault", "fault_type": "HardFault", "outcome": "fixed"}))
        rc, out, _ = _call(feedback_db.main, "--calibrate")
        self.assertIn("hardfault", json.loads(out))

    def test_invalid_json_exits_one(self):
        rc, out, _ = _call(feedback_db.main, "--log", "{bad")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "error")

    def test_no_arguments_prints_help(self):
        rc, out, _ = _call(feedback_db.main)
        self.assertIsNone(rc)
        self.assertIn("--stats", out)


class CubeUsercodeCliInProcessTests(unittest.TestCase):
    """main() 会 os.chdir 到工程根并缓存模块全局，用例间必须复位。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.proj, ".workbench"))
        with open(os.path.join(self.proj, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        os.makedirs(os.path.join(self.proj, "Core", "Src"))
        with open(os.path.join(self.proj, "Core", "Src", "main.c"), "w", encoding="utf-8") as fh:
            fh.write("/* USER CODE BEGIN 2 */\nint x = 1;\n/* USER CODE END 2 */\n")
        self._old_cwd = os.getcwd()
        self._reset_globals()
        self.addCleanup(self._restore)

    def _reset_globals(self):
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

    def _restore(self):
        os.chdir(self._old_cwd)
        self._reset_globals()

    def test_backup_then_diff(self):
        os.chdir(self.proj)
        rc, out, _ = _call(cube_usercode.main, "backup")
        self.assertEqual(rc, 0)
        self.assertIn("BACKUP", out.upper())
        self._reset_globals()
        rc, out, _ = _call(cube_usercode.main, "diff")
        self.assertEqual(rc, 0)

    def test_restore_without_backup_exits_one(self):
        os.chdir(self.proj)
        rc, out, _ = _call(cube_usercode.main, "restore")
        self.assertEqual(rc, 1)
        self.assertIn("没有找到备份目录", out)

    def test_missing_project_root_exits_one(self):
        os.chdir(self.tmp.name)
        rc, _, err = _call(cube_usercode.main, "diff")
        self.assertEqual(rc, 1)
        self.assertIn("未找到工程根", err)


if __name__ == "__main__":
    unittest.main()
