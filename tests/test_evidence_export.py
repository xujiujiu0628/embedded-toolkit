r"""F-151 (总工单 v2 T7/N-4) evidence_export 回归钉。

验收三类: 渲染 / 脱敏 / 降级落盘。
契约: GITHUB_STEP_SUMMARY 优先 (追加), 不在/写失败回落 --out; if: always()
安全 (输入非法只 exit 码报错, 不抛 traceback); 摘要零本机绝对路径、零
machine.json 内容 (统一 redact)。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import evidence_export  # noqa: E402

_WIN_PATH = r"D:\local\toolkit\examples\sim-demo"
_WIN_OTHER = r"D:\local\other"
_POSIX_PATH = "/home/runner/work/embedded-toolkit/x.elf"


def _verify_result():
    return {
        "status": "ok",
        "evidence": "simulation_validated",
        "elapsed_sec": 1.2,
        "post_reset": "skipped",
        "workspace": _WIN_PATH,
        "steps": {"verify": {"results": [
            {"id": "FR-SYS-01", "status": "pass"},
            {"id": "FR-ADC-01", "status": "fail", "detail": "mv=319 < min 3000"},
            {"id": "FR-FUTURE-1", "status": "xfail"},
            {"id": "FR-LANDED-1", "status": "xpass"},
        ]}},
        "records": [{"id": "FR-ADC-01", "mv": "3192"}],
        "captured_output": "boot on " + _POSIX_PATH,
        "junit_xml_error": None,
    }


class RenderTests(unittest.TestCase):
    def test_verify_summary_has_four_states_and_marks(self):
        md = evidence_export.render_verify_summary(_verify_result())
        self.assertIn("simulation_validated", md)
        self.assertIn("✅ PASS", md)
        self.assertIn("❌ FAIL", md)
        self.assertIn("⏭ XFAIL (欠条)", md)
        self.assertIn("❌ XPASS (判红)", md)
        self.assertIn("mv=319 < min 3000", md)
        self.assertIn("`mv=3192`", md, "record 提取值要进摘要")
        self.assertIn("不进发布门禁", md, "sim 证据提示 (F-146 呼应)")

    def test_verify_summary_marks_junit_error(self):
        r = _verify_result()
        r["junit_xml_error"] = "JUnit 报告写失败: disk full"
        md = evidence_export.render_verify_summary(r)
        self.assertIn("JUnit 报告写失败", md)

    def test_release_summary(self):
        md = evidence_export.render_release_summary({
            "tag": "v1.1.0", "git_head": "0123456789abcdef", "branch": "master",
            "evidence": "production_approved",
            "production_approved_at": "2026-09-12T12:00:00+08:00",
            "xfail_waived": ["FR-B"],
            "fidelity_boundaries": ["真机 capture 输出匹配判定"],
            "limitations": ["单板单次采样"],
            "results": [{"id": "FR-A", "status": "pass"}],
            "signature": "",
        })
        self.assertIn("v1.1.0", md)
        self.assertIn("0123456789ab", md)
        self.assertIn("批准投产", md)
        self.assertIn("2026-09-12T12:00:00+08:00", md)
        self.assertIn("Fidelity 边界", md)
        self.assertIn("签名机制登记未实现", md)


class RedactTests(unittest.TestCase):
    def test_windows_and_posix_paths_redacted(self):
        text = evidence_export.redact(
            f"workspace={_WIN_PATH} kernel={_POSIX_PATH} 产物 build/x.elf")
        self.assertNotIn("D:\\local", text)
        self.assertNotIn("/home/runner", text)
        self.assertIn("build/x.elf", " ".join(text.split()))
        self.assertIn("<path>", text)

    def test_extra_root_longest_first(self):
        text = evidence_export.redact(
            f"{_WIN_PATH} and {_WIN_OTHER}",
            extra_roots=(_WIN_PATH, r"D:\local"))
        self.assertNotIn(_WIN_PATH, text)
        self.assertNotIn(_WIN_OTHER, text)

    def test_machine_json_content_never_enter(self):
        # 红线钉: 渲染函数不读 machine.json — 结果里不该出现工具链键值
        r = _verify_result()
        md = evidence_export.render_verify_summary(r)
        for key in ("gcc_path", "make_exe", "openocd_exe", "qemu_exe"):
            self.assertNotIn(key, md)


class WriteSummaryTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        # 每个用例显式控制 GITHUB_STEP_SUMMARY
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        self.addCleanup(self._env.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_fallback_to_out_when_no_github_env(self):
        out = os.path.join(self.ws, "summary.md")
        rs = evidence_export.write_summary("md-body\n", out_path=out)
        self.assertTrue(rs["ok"])
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), "md-body\n")

    def test_github_env_target_gets_appended(self):
        gh = os.path.join(self.ws, "gh_summary.md")
        with open(gh, "w", encoding="utf-8") as f:
            f.write("old\n")
        os.environ["GITHUB_STEP_SUMMARY"] = gh
        rs = evidence_export.write_summary("new\n", out_path=None)
        self.assertTrue(rs["ok"])
        with open(gh, encoding="utf-8") as f:
            self.assertEqual(f.read(), "old\nnew\n")   # 追加语义
        # GH 写成功时不得在 CWD 产生多余回落文件 (施工实录: 曾双写)
        self.assertFalse(os.path.exists("job-summary.md"),
                         "GH 在场且写成功 → 不落 CWD 回落文件")

    def test_unwritable_github_env_falls_back_to_out(self):
        # GH 路径父目录是文件 → 写失败 → 回落 --out (if: always() 语义)
        blocker = os.path.join(self.ws, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("not a dir")
        os.environ["GITHUB_STEP_SUMMARY"] = os.path.join(blocker, "s.md")
        out = os.path.join(self.ws, "summary.md")
        rs = evidence_export.write_summary("md\n", out_path=out)
        self.assertTrue(rs["ok"], rs)
        self.assertTrue(any(o.endswith("summary.md") for o in rs["written"]))
        self.assertTrue(rs["error"], "GH 写失败要留痕")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        self.addCleanup(self._env.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["evidence_export.py"] + argv), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                code = evidence_export.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_redacted_output(self):
        src = os.path.join(self.ws, "result.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(_verify_result(), f)
        out = os.path.join(self.ws, "summary.md")
        code, stdout, _err = self._main(
            ["--verify-file", src, "--out", out])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as f:
            body = f.read()
        self.assertNotIn("D:\\local", body, "本机绝对路径必须被脱敏")
        self.assertIn("simulation_validated", body)

    def test_invalid_json_is_exit_2_no_traceback(self):
        bad = os.path.join(self.ws, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, _out, err = self._main(["--verify-file", bad,
                                      "--out", os.path.join(self.ws, "s.md")])
        self.assertEqual(code, 2)
        self.assertIn("输入不可用", err)

    def test_missing_input_file_is_exit_2(self):
        code, _out, _err = self._main(
            ["--verify-file", os.path.join(self.ws, "nope.json"),
             "--out", os.path.join(self.ws, "s.md")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
