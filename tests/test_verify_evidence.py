r"""F-128 (工单二 A-1) 证据分级回归钉 — verify --json 顶层 evidence 字段。

契约:
  1. 取值三档: real-hardware (rtt/semihosting 实跑) / simulator (sim 后端,
     C-1 预留) / static (capture 未跑成 — build/flash 失败早退同样 static);
  2. 字段随一切出口存在: main() 所有出口汇于 _output, 失败早退不缺键;
  3. 判定 verdict 与证据等级正交: 四态判定 (pass/xfail/xpass/fail) 下
     evidence 均存在且不随判定翻转 — FAIL 也是真机证据, PASS 也可能
     是静态证据 (agentic-embedded-lab claim+fidelity)。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


def _result(verify_status="pass", capture=None, status=None):
    """构造带 capture 步骤与指定四态判定的 result 骨架"""
    r = {
        "status": status or verify_status,
        "steps": {"verify": {"status": verify_status}},
    }
    if capture is not None:
        r["steps"]["capture"] = capture
    return r


class EvidenceLevelUnitTests(unittest.TestCase):
    """_evidence_level 纯函数: capture 后端 → 三档映射"""

    def test_rtt_is_real_hardware(self):
        cap = {"status": "ok", "method": "rtt"}
        self.assertEqual(verify._evidence_level(_result(capture=cap)),
                         "real-hardware")

    def test_semihosting_is_real_hardware(self):
        cap = {"status": "ok", "method": "semihosting"}
        self.assertEqual(verify._evidence_level(_result(capture=cap)),
                         "real-hardware")

    def test_sim_is_simulator(self):
        # C-1 预留: capture_sim.py 落地后 verify 分派 method="sim"
        cap = {"status": "ok", "method": "sim"}
        self.assertEqual(verify._evidence_level(_result(capture=cap)),
                         "simulator")

    def test_capture_failed_is_static(self):
        # capture 跑了但失败 → 没采到运行时证据, 不给"差一点就是真机"地带
        cap = {"status": "error", "method": "semihosting", "lines": 2}
        self.assertEqual(verify._evidence_level(_result(capture=cap)), "static")

    def test_no_capture_step_is_static(self):
        # build_failed 早退: steps 里根本没有 capture
        self.assertEqual(
            verify._evidence_level({"status": "build_failed",
                                    "steps": {"build": {"status": "error"}}}),
            "static")

    def test_unknown_method_is_static(self):
        # 未知 method 不猜测 — 诚实落 static, 宁低勿高
        cap = {"status": "ok", "method": "telepathy"}
        self.assertEqual(verify._evidence_level(_result(capture=cap)), "static")

    def test_evidence_values_are_the_documented_three(self):
        # 契约钉: 三档取值是输出契约的一部分, 改名即红 (README 同步改)
        self.assertEqual(verify.EVIDENCE_REAL, "real-hardware")
        self.assertEqual(verify.EVIDENCE_SIM, "simulator")
        self.assertEqual(verify.EVIDENCE_STATIC, "static")


class EvidenceVerdictOrthogonalityTests(unittest.TestCase):
    """验收: 四种判定状态下 evidence 字段均存在且取值正确"""

    def test_four_verdicts_all_real_hardware(self):
        # 真机 capture 下, pass/xfail/xpass/fail 判定全为 real-hardware —
        # 证据等级描述"证据从哪来", 不描述"判了什么"
        for verdict in ("pass", "xfail", "xpass", "fail"):
            r = _result(verify_status=verdict,
                        capture={"status": "ok", "method": "semihosting"})
            self.assertEqual(verify._evidence_level(r), "real-hardware",
                             f"verdict={verdict}")

    def test_four_verdicts_all_simulator_under_sim_backend(self):
        # 同一清单判真机也判仿真 — 仿真后端下四态证据恒 simulator
        for verdict in ("pass", "xfail", "xpass", "fail"):
            r = _result(verify_status=verdict,
                        capture={"status": "ok", "method": "sim"})
            self.assertEqual(verify._evidence_level(r), "simulator",
                             f"verdict={verdict}")


class OutputAttachesEvidenceTests(unittest.TestCase):
    """_output 是 main() 唯一出口汇点 — JSON 模式下 evidence 必须在顶层"""

    def test_success_json_has_evidence(self):
        r = _result(status="ok",
                    capture={"status": "ok", "method": "semihosting"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            verify._output(r, True)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["evidence"], "real-hardware")

    def test_build_failed_early_exit_json_has_evidence(self):
        # 早退出口 (build_failed, 无 capture 步骤) 不缺键 — 消费方无需特判
        r = {"status": "build_failed", "steps": {"build": {"status": "error"}}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            verify._output(r, True)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["evidence"], "static")

    def test_capture_timeout_json_is_static(self):
        # F-003 超时现场: OpenOCD 卡死 → 工具故障证据, 一样是 static
        r = {"status": "capture_failed",
             "steps": {"capture": {"status": "error",
                                   "method": "semihosting"}}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            verify._output(r, True)
        self.assertEqual(json.loads(buf.getvalue())["evidence"], "static")


class MainEndToEndEvidenceTests(unittest.TestCase):
    """驱动 main() 成功线 (mock 步骤), 断言 stdout JSON 顶层 evidence"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"toolkit_min_version": "0.1", "builder": "gcc",
                       "gcc": {"project": "Makefile", "target": "main",
                               "log_dir": ".workbench/build"}}, f)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "boot", "texts": ["[init] OK"]},
            ]}, f)

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
                                      "details": {}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash",
                                  mock.Mock(return_value={
                                      "status": "ok", "stderr": "Verified",
                                      "stdout": ""})), \
                mock.patch.object(verify, "run_semihosting_session",
                                  mock.Mock(return_value=("[init] OK\n", ""))), \
                mock.patch.object(verify, "reset_target",
                                  mock.Mock(return_value={"status": "ok"})), \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    verify.main()
                except SystemExit:
                    pass
        return out.getvalue()

    def test_success_run_evidence_real_hardware(self):
        result = json.loads(self._run_main())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["evidence"], "real-hardware")

    def test_no_flash_run_still_real_hardware(self):
        # --no-flash 跳烧录但 capture 仍实跑真机 (固件已在板上) → 证据不降级
        result = json.loads(self._run_main(["--no-flash", "--no-build"]))
        self.assertEqual(result["evidence"], "real-hardware")


if __name__ == "__main__":
    unittest.main()
