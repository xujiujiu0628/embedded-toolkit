"""--doctor 环境预检测试 (F-041)。全离线: SWD 探测经 mock, 不跑真 openocd;
"占位路径永不执行"由 subprocess 守卫钉死; swd_probe 下沉契约由同对象钉死。"""
import json
import os
import subprocess
import sys
import unittest
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
        """F-041 下沉契约: release G0.5 与 verify--doctor 共用
        openocd_runtime.swd_probe 同一对象 (防再分叉出两套口径)。"""
        self.assertIs(openocd_runtime.swd_probe, release.swd_probe)
        self.assertIs(openocd_runtime.swd_probe, verify.swd_probe)


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
        self.assertEqual(set(rep["machine"]["keys"]),
                         {"uv4_exe", "openocd_exe", "gcc_path", "make_exe"})
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
        for name in ("gcc", "openocd", "make"):
            self.assertEqual(rep["tools"][name]["status"], "skipped")
        self.assertEqual(rep["swd"]["status"], "skipped")

    def test_empty_machine_values_reported(self):
        with mock.patch.object(doctor, "load_machine",
                               return_value={"openocd_exe": "", "make_exe": None}):
            rep = verify.doctor_report(probe=False)
        self.assertFalse(rep["machine"]["keys"]["uv4_exe"]["value_set"])
        self.assertIsNone(rep["machine"]["keys"]["uv4_exe"]["path_exists"])
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


if __name__ == "__main__":
    unittest.main()
