r"""F-244: release.py 的 G0 拒绝条件与 main 早退补测。

## 覆盖对象

`scripts/release.py` 此前 88% 覆盖（2026-11-02 实测）：`g0_checks` 的
非 git 仓库 / 工作树脏 / tag 已存在 / 同 HEAD 记录已存在 / 记录不可解析
五条拒绝，以及 `main` 的缺工程根与目录不存在早退未执行。

## 夹具

`_git` 用模块引用替换返回预置结果，不依赖真实仓库。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import release  # noqa: E402


def _git_stub(is_repo="true", dirty="", tag="", head="abc123"):
    def _git(args_, _ws):
        cmd = " ".join(args_)
        if cmd == "rev-parse --is-inside-work-tree":
            return 0, is_repo, ""
        if cmd == "status --porcelain":
            return 0, dirty, ""
        if cmd.startswith("tag -l"):
            return 0, tag, ""
        if cmd == "rev-parse HEAD":
            return 0, head, ""
        return 0, "", ""

    return _git


class G0ChecksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = self.tmp.name

    def _run(self, **kw):
        with mock.patch.object(release, "_git", side_effect=_git_stub(**kw)):
            return release.g0_checks(self.ws, "v9.9.9")

    def test_not_a_git_repo(self):
        errs = self._run(is_repo="false")
        self.assertEqual(errs, [f"不是 git 仓库: {self.ws}"])

    def test_dirty_tree(self):
        errs = self._run(dirty=" M x.py")
        self.assertTrue(any("工作树不干净" in e for e in errs))

    def test_existing_tag(self):
        errs = self._run(tag="v9.9.9")
        self.assertTrue(any("本地 tag 已存在" in e for e in errs))

    def test_same_head_record(self):
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        with open(os.path.join(self.ws, ".workbench", "releases", "v9.9.9.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"git_head": "abc123"}, fh)
        errs = self._run()
        self.assertTrue(any("同 HEAD 已有发布记录" in e for e in errs))

    def test_unparseable_record(self):
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        with open(os.path.join(self.ws, ".workbench", "releases", "v9.9.9.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("{broken")
        errs = self._run()
        self.assertTrue(any("既有发布记录不可解析" in e for e in errs))

    def test_different_head_allowed(self):
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        with open(os.path.join(self.ws, ".workbench", "releases", "v9.9.9.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"git_head": "other"}, fh)
        self.assertEqual(self._run(), [])


class MainEarlyExitTests(unittest.TestCase):
    def _run(self, argv):
        err = io.StringIO()
        old = sys.argv
        sys.argv = ["release.py", *argv]
        try:
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    release.main()
        finally:
            sys.argv = old
        return ctx.exception.code, err.getvalue()

    def test_no_project_root(self):
        with mock.patch.object(release, "find_project_root", return_value=None):
            code, err = self._run(["--tag", "v1"])
        self.assertEqual(code, 1)
        self.assertIn("未找到工程根", err)

    def test_project_dir_missing(self):
        missing = os.path.join(tempfile.gettempdir(), "no-such-release-proj")
        code, err = self._run(["--project", missing, "--tag", "v1"])
        self.assertEqual(code, 1)
        self.assertIn("目录不存在", err)


if __name__ == "__main__":
    unittest.main()
