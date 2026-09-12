r"""F-147 (总工单 v2 N-1) verify --junit-xml 回归钉。

契约:
  1. 四态映射: pass → testcase; fail → <failure type="fail">; xpass →
     <failure type="xpass"> (XPASS 判红); xfail 未翻转 → <skipped> (欠条
     不是通过, 报告不计失败);
  2. preflight 拒绝 (build/flash/capture 失败, 没跑到判定): 期望逐条
     <skipped> + 一条 preflight <error> 点名 status;
  3. 只写实测时间: testsuite time = elapsed_sec (正数才写), testcase 不
     编造时长;
  4. 父目录自动创建; 写失败不抛 — 记 junit_xml_error 并拉低退出码;
  5. 本地 XML 解析断言格式合法 (不依赖 CI 人工步骤)。
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
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import junit_xml  # noqa: E402
import verify  # noqa: E402


def _rows():
    return [
        {"id": "FR-SYS-01", "status": "pass"},
        {"id": "FR-ADC-01", "status": "fail", "detail": "mv=5000 超上限"},
        {"id": "FR-FUTURE-1", "status": "xfail", "detail": "功能未实现"},
        {"id": "FR-LANDED-1", "status": "xpass"},
    ]


class BuildCasesTests(unittest.TestCase):
    """四态映射 (验收 ①)"""

    def test_four_states_map_correctly(self):
        cases = junit_xml.build_cases({"steps": {"verify": {"results": _rows()}}},
                                      ["FR-SYS-01"])
        by_id = {c["name"]: c for c in cases}
        self.assertEqual(by_id["FR-SYS-01"]["kind"], "case")
        self.assertEqual(by_id["FR-ADC-01"]["kind"], "failure")
        self.assertEqual(by_id["FR-ADC-01"]["failure_type"], "fail")
        self.assertEqual(by_id["FR-FUTURE-1"]["kind"], "skipped")
        self.assertIn("xfail", by_id["FR-FUTURE-1"]["message"])
        self.assertIn("功能未实现", by_id["FR-FUTURE-1"]["message"])
        self.assertEqual(by_id["FR-LANDED-1"]["kind"], "failure")
        self.assertEqual(by_id["FR-LANDED-1"]["failure_type"], "xpass")
        self.assertIn("翻转", by_id["FR-LANDED-1"]["message"])

    def test_preflight_yields_skipped_per_expectation_plus_error(self):
        # 验收 ②: build_failed 早退 — 期望全 skipped + 一条 preflight error
        result = {"status": "build_failed", "error": "Build failed after 1 attempt(s)",
                  "steps": {"verify": {}}}
        cases = junit_xml.build_cases(result, ["FR-A", "FR-B"])
        skipped = [c for c in cases if c["kind"] == "skipped"]
        errors = [c for c in cases if c["kind"] == "preflight_error"]
        self.assertEqual([c["name"] for c in skipped], ["FR-A", "FR-B"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["name"], "preflight")
        self.assertIn("build_failed", errors[0]["message"])

    def test_preflight_without_expectations_still_has_error_case(self):
        cases = junit_xml.build_cases({"status": "capture_failed"}, None)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["kind"], "preflight_error")


class RenderXmlTests(unittest.TestCase):
    """XML 合法性 (验收 ⑤) + 属性计数"""

    def test_render_is_parseable_with_correct_counts(self):
        result = {"steps": {"verify": {"results": _rows()}},
                  "elapsed_sec": 12.3}
        cases = junit_xml.build_cases(result, None)
        xml = junit_xml.render_xml(cases, 12.3)
        root = ET.fromstring(xml)   # 非法 XML 在此即红
        self.assertEqual(root.tag, "testsuite")
        self.assertEqual(root.get("tests"), "4")
        self.assertEqual(root.get("failures"), "2")    # fail + xpass 判红
        self.assertEqual(root.get("errors"), "0")
        self.assertEqual(root.get("skipped"), "1")     # xfail 欠条
        self.assertEqual(root.get("time"), "12.3")

    def test_time_only_when_measured(self):
        # 验收 ③: 只写实测时间 — elapsed 缺席/非正数不编造
        for elapsed in (None, 0, -1.0):
            xml = junit_xml.render_xml(
                junit_xml.build_cases({"status": "ok"}, None), elapsed)
            self.assertIsNone(ET.fromstring(xml).get("time"), f"elapsed={elapsed}")

    def test_special_chars_in_ids_do_not_break_xml(self):
        # id 含 XML 特殊字符 → ET 转义, 解析不炸
        rows = [{"id": 'FR<X>&"1"', "status": "fail"}]
        cases = junit_xml.build_cases({"steps": {"verify": {"results": rows}}}, None)
        root = ET.fromstring(junit_xml.render_xml(cases, None))
        self.assertEqual(root.find("testcase").get("name"), 'FR<X>&"1"')


class WriteReportTests(unittest.TestCase):
    """落盘契约: 父目录自动创建 + 写失败不抛 (验收 ④)"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_write_creates_parent_dirs_and_valid_file(self):
        out = os.path.join(self.ws, "nested", "dir", "report.xml")
        result = {"status": "ok", "elapsed_sec": 3.0,
                  "steps": {"verify": {"results": _rows()}}}
        rs = junit_xml.write_junit_report(result, out)
        self.assertTrue(rs["ok"], rs)
        root = ET.parse(out).getroot()   # 落盘文件必须可解析
        self.assertEqual(root.get("tests"), "4")

    def test_write_failure_returns_error_envelope(self):
        # 父路径是个文件 → makedirs 必败 → 错误信封而非异常
        blocker = os.path.join(self.ws, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("not a dir")
        out = os.path.join(blocker, "report.xml")
        rs = junit_xml.write_junit_report({"status": "ok"}, out)
        self.assertFalse(rs["ok"])
        self.assertIn("JUnit 报告写失败", rs["error"])


class VerifyMainJunitTests(unittest.TestCase):
    """verify 最小接线: --junit-xml 端到端 + 写失败拉低退出码"""

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
        self.addCleanup(setattr, verify, "_JUNIT_OUT", None)

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
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, out.getvalue()

    def test_success_run_writes_parseable_report(self):
        out_path = os.path.join(self.ws, "junit", "verify-report.xml")
        code, stdout = self._run_main(["--junit-xml", out_path])
        self.assertEqual(code, 0)
        root = ET.parse(out_path).getroot()
        self.assertEqual(root.get("tests"), "1")
        names = [tc.get("name") for tc in root.findall("testcase")]
        self.assertEqual(names, ["FR-SYS-01"])
        result = json.loads(stdout)
        self.assertNotIn("junit_xml_error", result)

    def test_junit_write_failure_lowers_exit_code(self):
        # ok 判定 + 报告写失败 → exit 1 + JSON 记 junit_xml_error
        blocker = os.path.join(self.ws, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("not a dir")
        out_path = os.path.join(blocker, "report.xml")
        code, stdout = self._run_main(["--junit-xml", out_path])
        result = json.loads(stdout)
        self.assertEqual(result["status"], "ok")
        self.assertIn("junit_xml_error", result)
        self.assertEqual(code, 1, "报告没落盘, 成功判定也必须拉低退出码")


if __name__ == "__main__":
    unittest.main()
