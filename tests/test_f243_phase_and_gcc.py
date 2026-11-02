r"""F-243: phase_minus_one 人读输出 + gcc_build 预检/命令构造补测。

## 覆盖对象

- `phase_minus_one`：main 的非 JSON 人读分支（图标/推荐项输出，84%→）；
- `gcc_build`：`_run_make` 的 clean/rebuild/build 三种命令、`main` 的
  toolchain 解析失败与预检缺工具两条错误出口、`_makefile_vars` 的 `:=`/`?=`
  算符、`_parse_log_metrics` 的缺失文件回落（80%→）。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gcc_build  # noqa: E402
import phase_minus_one  # noqa: E402


def _call(module, argv, **patches):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = [module.__name__ + ".py", *argv]
    try:
        with mock.patch.multiple(module, **patches) if patches else _null():
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = module.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *_x):
        return False


class PhaseHumanOutputTests(unittest.TestCase):
    def test_human_output_shows_verdict_and_recommendations(self):
        result = {
            "target": "I2C1 driver",
            "verdict": "OK_WITH_WARNINGS",
            "checks": {
                "chip_support": {"status": "OK", "detail": "ok"},
                "pin_conflict": {"status": "CONFLICT", "detail": "PB6 used",
                                 "shared": ["PB6: I2C1 (same)"]},
            },
            "recommendations": ["review carefully"],
        }
        rc, out, _ = _call(phase_minus_one, ["-p", "I2C1", "--pins", "PB6"],
                           run_check=lambda *a, **k: result)
        self.assertIsNone(rc)
        self.assertIn("[PASS]", out)
        self.assertIn("[FAIL]", out)
        self.assertIn("PB6: I2C1 (same)", out)
        self.assertIn("Verdict: OK_WITH_WARNINGS", out)
        self.assertIn("review carefully", out)


class MakefileVarTests(unittest.TestCase):
    def test_assignment_operators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Makefile")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("TARGET := ch32v307-hello\nBUILD_DIR ?= build\n")
            self.assertEqual(gcc_build._makefile_vars(__import__("pathlib").Path(path)),
                             {"TARGET": "ch32v307-hello", "BUILD_DIR": "build"})

    def test_missing_file_returns_empty(self):
        from pathlib import Path
        self.assertEqual(gcc_build._makefile_vars(Path("no-such-Makefile")), {})


class LogMetricsTests(unittest.TestCase):
    def test_counts_errors_and_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "build.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("a.c:1:2: error: boom\nb.c:3:4: warning: meh\n")
            from pathlib import Path
            self.assertEqual(gcc_build._parse_log_metrics(Path(path)),
                             {"errors": 1, "warnings": 1})

    def test_missing_log_returns_minus_one(self):
        from pathlib import Path
        self.assertEqual(gcc_build._parse_log_metrics(Path("no-such.log")),
                         {"errors": -1, "warnings": -1})


class RunMakeTests(unittest.TestCase):
    def _run(self, action, kind="arm"):
        calls = []

        def _run(cmd, **_kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        old = gcc_build.subprocess
        gcc_build.subprocess = SimpleNamespace(run=_run, STDOUT=-2,
                                               TimeoutExpired=TimeoutError)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                gcc_build._run_make(
                    __import__("pathlib").Path(tmp), action, "t",
                    __import__("pathlib").Path(tmp) / "log.txt",
                    {"make_exe": "make"}, {"kind": kind, "bin_dir": "/bin",
                                            "prefix": "arm-none-eabi-"})
            finally:
                gcc_build.subprocess = old
        return calls

    def test_clean(self):
        calls = self._run("clean")
        self.assertEqual(calls[0][:2], ["make", "clean"])

    def test_rebuild_runs_clean_then_build(self):
        calls = self._run("rebuild")
        self.assertEqual(calls[0][:2], ["make", "clean"])
        self.assertIn("-j", calls[1][1])

    def test_build_arm_does_not_override_cc(self):
        calls = self._run("build")
        self.assertIn("TARGET=t", calls[0])
        self.assertFalse(any(str(a).startswith("CC=") for a in calls[0]))

    def test_build_wch_injects_tool_vars(self):
        calls = self._run("build", kind="wch")
        self.assertTrue(any(str(a).startswith("CC=") for a in calls[0]))
        self.assertTrue(any(str(a).startswith("OBJCOPY=") for a in calls[0]))


class GccMainPrecheckTests(unittest.TestCase):
    def _run(self, *, toolchain_exc=None, which=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        makefile = os.path.join(tmp.name, "Makefile")
        with open(makefile, "w", encoding="utf-8") as fh:
            fh.write("TARGET = app\n")

        def _toolchain(*_a, **_k):
            if toolchain_exc:
                raise ValueError(toolchain_exc)
            return {"kind": "arm", "prefix": "arm-none-eabi-", "bin_dir": "/gcc"}

        old_shutil = gcc_build.shutil
        gcc_build.shutil = SimpleNamespace(which=which or (lambda *_a, **_k: None))
        try:
            return _call(
                gcc_build, ["build", "--project", makefile, "--json"],
                workspace_root=lambda _w: __import__("pathlib").Path(tmp.name),
                load_machine=lambda: {"make_exe": "make", "gcc_path": "/gcc"},
                load_project_config=lambda *a, **k: {},
                resolve_toolchain=_toolchain,
                resolve_workspace_mode=lambda *a, **k: __import__("pathlib").Path(tmp.name),
            )
        finally:
            gcc_build.shutil = old_shutil

    def test_toolchain_error_reported(self):
        rc, out, _ = self._run(toolchain_exc="unknown toolchain")
        self.assertIsNone(rc)
        self.assertEqual(json.loads(out)["error"]["code"], "toolchain")

    def test_missing_tools_reported(self):
        rc, out, _ = self._run()
        self.assertIsNone(rc)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "precheck")
        self.assertIn("make_exe invalid", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
