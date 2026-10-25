"""--doctor 环境预检测试 (F-041)。全离线: SWD 探测经 mock, 不跑真 openocd;
"占位路径永不执行"由 subprocess 守卫钉死; swd_probe 下沉契约由同对象钉死。"""
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (F-054 后 import 期零 IO)
import doctor  # noqa: E402  (F-058: doctor 家族拆分件)
import openocd_runtime  # noqa: E402
import release  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(verify.__file__))
REPO_ROOT = os.path.dirname(SCRIPTS)


class SwdProbeMoveTests(unittest.TestCase):
    def test_release_gate_and_doctor_share_one_probe(self):
        """F-041 下沉契约: release G0.5 与 doctor 共用
        openocd_runtime.swd_probe 同一对象 (防再分叉出两套口径)。

        F-192/N-4 (WB-20260926-03 T5) 随动: verify 主链零调用 swd_probe,
        死名已从 verify 删除 — verify 面旧断言 assertIs(…, verify.swd_probe)
        改钉 "死名不得回场" (同源防分叉语义由 release 面断言继续持有)。"""
        self.assertIs(openocd_runtime.swd_probe, release.swd_probe)
        self.assertFalse(hasattr(verify, "swd_probe"),
                         "F-192/N-4: verify 不得再持有 swd_probe 死名 "
                         "(G0.5 探测面归 release/doctor 直连 openocd_runtime)")


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class SwdProbeBehaviorTests(unittest.TestCase):
    def _run(self, attempts):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            raise FileNotFoundError("no openocd here")

        with mock.patch.object(openocd_runtime.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(openocd_runtime.time, "sleep"):
            ok, detail = openocd_runtime.swd_probe("openocd-fake", attempts=attempts)
        return ok, detail, calls

    def test_gate_default_three_attempts(self):
        ok, _, calls = self._run(3)
        self.assertFalse(ok)
        self.assertEqual(len(calls), 3)

    def test_doctor_single_attempt(self):
        ok, _, calls = self._run(1)
        self.assertFalse(ok)
        self.assertEqual(len(calls), 1)

    def test_judgment_is_content_based(self):
        """含 shutdown 但带 init mode failed → 仍判失败 (对齐 hardfault 哲学)。"""
        both = _FakeProc(stdout="shutdown command invoked",
                         stderr="Error: init mode failed", returncode=1)
        with mock.patch.object(openocd_runtime.subprocess, "run", return_value=both), \
                mock.patch.object(openocd_runtime.time, "sleep"):
            self.assertFalse(openocd_runtime.swd_probe("x", attempts=1)[0])
        good = _FakeProc(stdout="shutdown command invoked",
                         stderr="Info : SWD DPIDR 0x1ba01477", returncode=0)
        with mock.patch.object(openocd_runtime.subprocess, "run", return_value=good), \
                mock.patch.object(openocd_runtime.time, "sleep"):
            ok, detail = openocd_runtime.swd_probe("x", attempts=1)
        self.assertTrue(ok)
        self.assertIn("shutdown command invoked", detail)


class DoctorReportTests(unittest.TestCase):
    def test_structure_and_summary_consistency(self):
        rep = verify.doctor_report(probe=False)
        for key in ("tool", "toolkit_version", "python", "machine", "tools", "swd", "summary"):
            self.assertIn(key, rep)
        self.assertEqual(rep["tool"], "doctor")
        # F-131 (工单 P2-2): uv4_exe 随 Keil 退役从 _DOCTOR_KEYS 移除;
        # 旧 machine.json 里残留的该键应被容忍 (不出现在报告里) 而非报错
        self.assertEqual(set(rep["machine"]["keys"]),
                         {"openocd_exe", "gcc_path", "make_exe"})
        self.assertTrue(rep["machine"]["mode"].startswith(("machine.json", "fallback", "missing")))
        for name in ("gcc", "openocd", "make"):
            self.assertIn(rep["tools"][name]["status"], ("ok", "warn", "skipped"))
        statuses = [rep["tools"][n]["status"] for n in ("gcc", "openocd", "make")]
        statuses.append(rep["swd"]["status"])
        # F-048: fixture 也进 summary 计数 (与 tools/swd 平级)
        if "fixtures" in rep:
            statuses.append(rep["fixtures"]["status"])
        for k in ("ok", "warn", "fail", "skipped"):
            self.assertEqual(rep["summary"][k], statuses.count(k), k)

    def test_placeholder_paths_never_executed(self):
        """安全钉: machine.example.json 的 "<...>" 占位值绝不能被当作命令执行。"""
        # F-131: 含 uv4_exe 的旧 machine.json 输入须被容忍 (不出现在报告、不报错)
        placeholder = {k: f"<本机 {k} 绝对路径>"
                       for k in ("uv4_exe", "openocd_exe", "gcc_path", "make_exe")}

        def guard(*a, **kw):
            raise AssertionError("占位/未配置路径不得触发任何子进程")

        with mock.patch.object(doctor, "load_machine", return_value=placeholder), \
                mock.patch.object(verify.subprocess, "run", side_effect=guard), \
                mock.patch.object(openocd_runtime.subprocess, "run", side_effect=guard):
            # F-048: skip_drift_check=True 跳过 git main 对比, 不让 fixture 体检破守卫
            rep = verify.doctor_report(probe=True, skip_drift_check=True)
        self.assertTrue(all(v["placeholder"] for v in rep["machine"]["keys"].values()))
        self.assertNotIn("uv4_exe", rep["machine"]["keys"])  # F-131: 退役键不再报
        for name in ("gcc", "openocd", "make"):
            self.assertEqual(rep["tools"][name]["status"], "skipped")
        self.assertEqual(rep["swd"]["status"], "skipped")

    def test_empty_machine_values_reported(self):
        with mock.patch.object(doctor, "load_machine",
                               return_value={"openocd_exe": "", "make_exe": None,
                                             "uv4_exe": "<旧 Keil 键>"}):
            rep = verify.doctor_report(probe=False)
        # F-131: uv4_exe 退役——报告键集只含三活键, 旧键多余也无害
        self.assertEqual(set(rep["machine"]["keys"]),
                         {"openocd_exe", "gcc_path", "make_exe"})
        self.assertFalse(rep["machine"]["keys"]["openocd_exe"]["value_set"])
        self.assertEqual(rep["tools"]["gcc"]["status"], "skipped")
        self.assertEqual(rep["tools"]["openocd"]["status"], "skipped")
        self.assertEqual(rep["tools"]["make"]["status"], "skipped")
        self.assertEqual(rep["swd"]["status"], "skipped")


class DoctorCliTests(unittest.TestCase):
    def test_cli_exit_zero_and_human_output(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "verify.py"), "--doctor"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, (r.stderr or "")[-500:])
        self.assertIn("embedded-toolkit doctor", r.stdout)
        self.assertIn("summary", r.stdout)

    def test_cli_json_parseable(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "verify.py"),
                            "--doctor", "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, (r.stderr or "")[-500:])
        doc = json.loads(r.stdout)
        self.assertEqual(doc["tool"], "doctor")
        self.assertIn("summary", doc)


class DoctorStrictModeTests(unittest.TestCase):
    """--strict 让真机 CI 能把环境预检失败变成 job 失败。

    默认 doctor 仍是诊断报告 (rc=0); strict 只在存在 warn/fail 时返回 1,
    skipped 是可选组件缺席, 不算失败。
    """

    @staticmethod
    def _report(ok=0, warn=0, fail=0, skipped=0):
        return {"tool": "doctor", "toolkit_version": "0",
                "python": "3", "machine": {"mode": "missing", "keys": {}},
                "tools": {}, "swd": {"status": "skipped", "detail": ""},
                "fixtures": {},
                "summary": {"ok": ok, "warn": warn, "fail": fail,
                            "skipped": skipped, "fixture": "ok"}}

    def _main_code(self, report, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["verify.py", "--doctor", "--json", *args]), \
                mock.patch.object(verify, "doctor_report",
                                  return_value=report), \
                redirect_stdout(out):
            try:
                verify.main()
            except SystemExit as e:
                return e.code, out.getvalue()
        return 0, out.getvalue()

    def test_default_is_diagnostic_rc0_even_with_fail(self):
        code, _ = self._main_code(self._report(fail=1))
        self.assertEqual(code, 0)

    def test_strict_fails_on_fail(self):
        code, _ = self._main_code(self._report(fail=1), "--strict")
        self.assertEqual(code, 1)

    def test_strict_fails_on_warn(self):
        code, _ = self._main_code(self._report(warn=1), "--strict")
        self.assertEqual(code, 1)

    def test_strict_allows_skipped(self):
        code, _ = self._main_code(self._report(skipped=3), "--strict")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
