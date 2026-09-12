r"""F-150 (总工单 v2 T6/C-1) sim 后端回归钉。

契约:
  1. capture_sim.py: qemu 命令形态 (F-149 spike 实证), exe 解析链
     (config sim.exe > machine.json qemu_exe > PATH > 缺省), 超时 →
     SimTimeout 携 proc (收尸权在调用方, F-003 口径);
  2. verify 分派: backend=sim → flash skipped (带 reason)、capture
     method="sim"、evidence="simulation_validated"、**不持设备锁、不跑
     HIL 守卫** (无硬件, CI 可跑)、判定逻辑零改动 (同一份 expectations);
  3. 真机路径零回归: 既有 capture_semihosting 契约不变 (套件全量覆盖);
  4. examples/sim-demo 契约静态可 lint、四态齐备。
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

import capture_sim  # noqa: E402
import expectations_lint  # noqa: E402
import hw_lease  # noqa: E402
import verify  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class ResolveQemuTests(unittest.TestCase):
    def test_config_wins(self):
        exe, src = capture_sim.resolve_qemu({"exe": r"D:\tools\qemu.exe"})
        self.assertEqual((exe, src), (r"D:\tools\qemu.exe", "config:sim.exe"))

    def test_machine_json_next(self):
        with mock.patch("wb_common.load_machine",
                        return_value={"qemu_exe": r"E:\qemu\qemu-system-arm.exe"}):
            exe, src = capture_sim.resolve_qemu({})
        self.assertEqual((exe, src),
                         (r"E:\qemu\qemu-system-arm.exe", "machine:qemu_exe"))

    def test_path_then_default(self):
        with mock.patch("wb_common.load_machine", return_value={}), \
                mock.patch.object(capture_sim, "which",
                                  return_value="/usr/bin/qemu-system-arm"):
            exe, src = capture_sim.resolve_qemu({})
        self.assertEqual(src, "path")
        with mock.patch("wb_common.load_machine", return_value={}), \
                mock.patch.object(capture_sim, "which", return_value=None):
            exe, src = capture_sim.resolve_qemu({})
        self.assertEqual((exe, src),
                         ("qemu-system-arm", "default"))


class RunSimSessionTests(unittest.TestCase):
    def test_command_shape(self):
        with mock.patch.object(capture_sim, "subprocess") as m_sub:
            m_sub.PIPE = subprocess.PIPE
            m_sub.DEVNULL = subprocess.DEVNULL
            proc = mock.Mock()
            proc.communicate.return_value = ("out\n", "err\n")
            m_sub.Popen.return_value = proc
            out, err = capture_sim.run_sim_session(
                15, "stm32vldiscovery", "build/x.elf",
                qemu_exe="qemu-fake", sim_cfg={"extra_args": ["-d", "unimp"]})
        self.assertEqual((out, err), ("out\n", "err\n"))
        cmd = m_sub.Popen.call_args[0][0]
        self.assertEqual(cmd[0], "qemu-fake")
        self.assertIn("-M", cmd)
        self.assertEqual(cmd[cmd.index("-M") + 1], "stm32vldiscovery")
        self.assertEqual(cmd[cmd.index("-kernel") + 1], "build/x.elf")
        self.assertIn("enable=on,target=native",
                      cmd[cmd.index("-semihosting-config") + 1])
        self.assertIn("-no-reboot", cmd)
        self.assertEqual(cmd[-2:], ["-d", "unimp"])
        # stdin 必须 DEVNULL (防 qemu 监视器吞交互终端)
        self.assertIs(m_sub.Popen.call_args.kwargs.get("stdin"),
                      subprocess.DEVNULL)

    def test_timeout_raises_sim_timeout_with_proc(self):
        with mock.patch.object(capture_sim, "subprocess") as m_sub:
            m_sub.PIPE = subprocess.PIPE
            m_sub.DEVNULL = subprocess.DEVNULL
            proc = mock.Mock()
            m_sub.Popen.return_value = proc
            m_sub.TimeoutExpired = subprocess.TimeoutExpired
            proc.communicate.side_effect = subprocess.TimeoutExpired(
                cmd=[], timeout=45)
            with self.assertRaises(capture_sim.SimTimeout) as cm:
                capture_sim.run_sim_session(15, "m", "k.elf", qemu_exe="q")
        self.assertIs(cm.exception.proc, proc,
                      "超时必须携带 proc, 收尸权在调用方 (F-003 口径)")


class VerifySimDispatchTests(unittest.TestCase):
    """backend=sim: flash skipped / method=sim / evidence 对 / 零设备锁"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"toolkit_min_version": "0.1", "builder": "gcc",
                       "gcc": {"project": "Makefile", "target": "sim-demo",
                               "log_dir": ".workbench/build"},
                       "capture": {"backend": "sim", "duration_sec": 10,
                                   "sim": {"machine": "stm32vldiscovery"}}}, f)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "boot", "texts": ["[init] OK"]},
            ]}, f)
        self.lock_dir = os.path.join(self.ws, "device-locks")
        self._lp = mock.patch.object(hw_lease, "DEVICE_LOCK_DIR", self.lock_dir)
        self._lp.start()
        self.addCleanup(self._lp.stop)
        # 构建 details 里的 elf_file 是相对路径 — sim 分派会校验在场
        os.makedirs(os.path.join(self.ws, "build"), exist_ok=True)
        with open(os.path.join(self.ws, "build", "x.elf"), "wb") as f:
            f.write(b"\x00")

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run_main(self, extra_args=()):
        argv = ["verify.py", "--project", self.ws, "--json"] + list(extra_args)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": "s",
                                      "metrics": {"errors": 0, "warnings": 0},
                                      "details": {"elf_file": "build/x.elf",
                                                  "hex_file": "build/x.hex"}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "run_sim_session",
                                  mock.Mock(return_value=("[init] OK\n", ""))), \
                mock.patch.object(hw_lease, "acquire") as m_acq, \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    verify.main()
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, json.loads(out.getvalue()), m_acq

    def test_sim_run_end_to_end_green(self):
        code, result, m_acq = self._run_main()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        # flash skipped 带 sim 理由
        flash = result["steps"]["flash"]
        self.assertEqual(flash["status"], "skipped")
        self.assertIn("sim", flash["reason"])
        # capture: qemu 直接加载 elf
        cap = result["steps"]["capture"]
        self.assertEqual(cap["method"], "sim")
        self.assertEqual(cap["machine"], "stm32vldiscovery")
        self.assertEqual(cap["kernel"], "build/x.elf")
        # F-146: sim 证据恒 simulation_validated
        self.assertEqual(result["evidence"], "simulation_validated")
        # post_reset: 无烧录 → skipped (F-129 契约)
        self.assertEqual(result["post_reset"], "skipped")
        # F-145: 无硬件 → 设备锁零调用
        m_acq.assert_not_called()
        # 判定逻辑零改动: 同一份 expectations 正常判绿
        self.assertEqual(result["steps"]["verify"]["status"], "ok")

    def test_sim_kernel_missing_is_capture_failed(self):
        # build details 无 elf 且 config 无 sim.kernel → capture_failed 早退
        code, result, m_acq = self._run_main(["--no-build"])
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "capture_failed")
        self.assertIn("elf", result["error"])
        m_acq.assert_not_called()


class SimDemoFixtureTests(unittest.TestCase):
    """examples/sim-demo 契约静态检查 (CI sim job 的地面保障)"""

    def test_demo_expectations_lint_clean(self):
        rel = os.path.join("examples", "sim-demo", ".workbench",
                           "expectations.json")
        rs = expectations_lint.lint_file(os.path.join(_ROOT, rel))
        self.assertEqual(rs["errors"], [], rs)

    def test_demo_contract_has_four_states_ready(self):
        with open(os.path.join(_ROOT, "examples", "sim-demo", ".workbench",
                               "expectations.json"), encoding="utf-8") as f:
            exps = json.load(f)["expectations"]
        ids = {e["id"] for e in exps}
        self.assertIn("FR-FUTURE-1", ids)   # xfail 欠条 (四态覆盖)
        self.assertTrue(any("record" in e for e in exps))  # F-148 record


if __name__ == "__main__":
    unittest.main()
