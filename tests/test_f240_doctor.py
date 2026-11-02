r"""F-240: doctor 的报告渲染、退出码与分支矩阵补测。

## 覆盖对象

`scripts/doctor.py` 此前 72% 覆盖（2026-11-02 实测）：`_print_doctor` 的
drift/missing 注记、`strict_exit_code`、`doctor_report` 的 gcc 配置错误行与
SWD 三态（未配置 / 未请求探测 / 解析失败 / 探测结果）未执行。doctor 没有
自己的 main（入口在 verify.py --doctor），既有用例多走子进程，未计入覆盖。

## 夹具

`load_machine` / `_load_doctor_gcc_cfg` / `_check_tool` / `fixture_health` /
`resolve_openocd_target` / `swd_probe` 全部模块引用替换；TOOLKIT_ROOT 指到
临时目录，不读本机 machine.json。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import doctor  # noqa: E402
from runtime_common import OpenocdCfgError  # noqa: E402


def _report(**over):
    base = {
        "toolkit_version": "0.10",
        "python": "3.14.0",
        "machine": {"mode": "machine.json",
                    "keys": {"gcc_path": {"value_set": True, "placeholder": False,
                                          "path_exists": True}}},
        "tools": {
            "gcc": {"status": "ok", "version": "10.3"},
            "openocd": {"status": "warn", "detail": "占位"},
            "make": {"status": "fail", "error": "missing"},
        },
        "swd": {"status": "skipped", "detail": "未请求探测"},
        "fixtures": {"status": "ok"},
        "summary": {"ok": 1, "warn": 1, "fail": 1, "skipped": 1, "fixture": "ok"},
    }
    base.update(over)
    return base


class StrictExitCodeTests(unittest.TestCase):
    def test_clean_is_zero(self):
        self.assertEqual(doctor.strict_exit_code({"summary": {"ok": 3}}), 0)

    def test_warn_or_fail_is_one(self):
        self.assertEqual(doctor.strict_exit_code({"summary": {"warn": 1}}), 1)
        self.assertEqual(doctor.strict_exit_code({"summary": {"fail": 1}}), 1)

    def test_missing_summary_is_zero(self):
        self.assertEqual(doctor.strict_exit_code({}), 0)


class PrintDoctorTests(unittest.TestCase):
    def test_renders_tool_and_summary_lines(self):
        out = io.StringIO()
        with redirect_stdout(out):
            doctor._print_doctor(_report())
        text = out.getvalue()
        self.assertIn("== embedded-toolkit doctor ==", text)
        self.assertIn("gcc      : ok — 10.3", text)
        self.assertIn("openocd  : warn — 占位", text)
        self.assertIn("make     : fail", text)
        self.assertIn("missing", text)
        self.assertIn("fixtures: ok", text)
        self.assertIn("summary : ok=1 warn=1 fail=1 skipped=1", text)

    def test_drift_and_missing_notes(self):
        rep = _report(fixtures={
            "status": "warn",
            "drift": {"detected": True, "mismatches": ["a.json", "b.json"]},
            "config": {"status": "missing"},
            "expectations": {"status": "missing"},
        })
        out = io.StringIO()
        with redirect_stdout(out):
            doctor._print_doctor(rep)
        text = out.getvalue()
        self.assertIn("(drift: a.json, b.json)", text)
        self.assertIn("(missing: config, expectations)", text)

    def test_key_flags(self):
        rep = _report(machine={"mode": "m", "keys": {
            "gcc_path": {"value_set": True, "placeholder": True, "path_exists": False},
            "make_exe": {"value_set": False, "placeholder": False, "path_exists": None},
        }})
        out = io.StringIO()
        with redirect_stdout(out):
            doctor._print_doctor(rep)
        text = out.getvalue()
        self.assertIn("占位", text)
        self.assertIn("空", text)


class DoctorReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.oc = os.path.join(self.tmp.name, "openocd.exe")
        with open(self.oc, "w", encoding="utf-8") as fh:
            fh.write("")

    def _run(self, *, gcc_cfg=({}, ""), probe=True, target=None, swd=(True, "tail")):
        machine = {"gcc_path": "/gcc", "openocd_exe": self.oc, "make_exe": "/make"}
        target = target if target is not None else {"exe": self.oc, "cfg_list": []}
        with mock.patch.object(doctor, "TOOLKIT_ROOT", self.tmp.name), \
                mock.patch.object(doctor, "load_machine", return_value=machine), \
                mock.patch.object(doctor, "_load_doctor_gcc_cfg", return_value=gcc_cfg), \
                mock.patch.object(doctor, "_check_tool",
                                  return_value={"status": "ok", "version": "v"}), \
                mock.patch.object(doctor, "fixture_health",
                                  return_value={"status": "ok"}), \
                mock.patch.object(doctor, "resolve_openocd_target",
                                  side_effect=target if isinstance(target, Exception) else None,
                                  return_value=None if isinstance(target, Exception) else target), \
                mock.patch.object(doctor, "swd_probe", return_value=swd):
            return doctor.doctor_report(probe=probe, skip_drift_check=True)

    def test_clean_report(self):
        rep = self._run()
        self.assertEqual(rep["tool"], "doctor")
        self.assertEqual(rep["swd"]["status"], "ok")
        self.assertEqual(rep["summary"]["ok"], 5)

    def test_probe_disabled_skips_swd(self):
        rep = self._run(probe=False)
        self.assertEqual(rep["swd"]["status"], "skipped")
        self.assertIn("未请求探测", rep["swd"]["detail"])

    def test_gcc_cfg_error_becomes_fail_row(self):
        rep = self._run(gcc_cfg=({}, "bad config"))
        self.assertEqual(rep["tools"]["gcc"]["status"], "fail")
        self.assertIn("bad config", rep["tools"]["gcc"]["detail"])

    def test_openocd_cfg_error_fails_swd(self):
        rep = self._run(target=OpenocdCfgError("cfg missing"))
        self.assertEqual(rep["swd"]["status"], "fail")
        self.assertIn("cfg missing", rep["swd"]["detail"])

    def test_swd_probe_failure(self):
        rep = self._run(swd=(False, "no probe"))
        self.assertEqual(rep["swd"]["status"], "fail")
        self.assertEqual(rep["swd"]["detail"], "no probe")


if __name__ == "__main__":
    unittest.main()
