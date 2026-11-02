r"""F-244: cube_usercode 的编码回落与备份失败回收补测。

## 覆盖对象

`scripts/cube_usercode.py` 此前 84% 覆盖（2026-11-02 实测）：`extract_user_code`
的 ascii→utf-8 回落、`_dedent` 全空输入、`cmd_backup` 的复制失败与交换失败
两条回收路径、`main` 缺工程根与默认动作未执行。

## 夹具

`shutil` / `os` 用直接赋值替身（避免 test_stub_ratchet 的 B 式判据），
用完还原；工程目录用临时目录。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import cube_usercode  # noqa: E402


class ExtractEncodingTests(unittest.TestCase):
    def test_non_ascii_file_falls_back_to_utf8_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.c"
            path.write_bytes("/* USER CODE BEGIN 2 */\n中文\n/* USER CODE END 2 */\n".encode("utf-8"))
            blocks = cube_usercode.extract_user_code(path)
        self.assertIn("中文", blocks["2"])


class DedentEdgeTests(unittest.TestCase):
    def test_only_blank_lines_returned_unchanged(self):
        self.assertEqual(cube_usercode._dedent("\n\n"), "\n\n")


class BackupFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name) / "proj"
        (self.proj / ".workbench").mkdir(parents=True)
        (self.proj / "Core" / "Src").mkdir(parents=True)
        (self.proj / "Core" / "Src" / "main.c").write_text("int x;\n", encoding="utf-8")
        (self.proj / ".workbench" / "config.json").write_text("{}", encoding="utf-8")
        self._old = (cube_usercode.shutil, cube_usercode.os)
        self._cwd = os.getcwd()
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

    def tearDown(self):
        os.chdir(self._cwd)   # 临时目录清理前先离开，Windows 不许删 cwd
        cube_usercode.shutil, cube_usercode.os = self._old
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

    def _run(self, action, shutil_ns=None, os_ns=None):
        out, err = io.StringIO(), io.StringIO()
        old_cwd = os.getcwd()
        old_argv = sys.argv
        sys.argv = ["cube_usercode.py", action]
        os.chdir(self.proj)
        if shutil_ns:
            cube_usercode.shutil = shutil_ns
        if os_ns:
            cube_usercode.os = os_ns
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = cube_usercode.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        return rc, out.getvalue(), err.getvalue()

    def test_copy_failure_keeps_old_backup(self):
        def _boom(*_a, **_k):
            raise OSError("copy denied")

        shutil_ns = SimpleNamespace(copy2=_boom, rmtree=lambda *a, **k: None,
                                    which=lambda _n: "/bin/x")
        rc, _, err = self._run("backup", shutil_ns=shutil_ns)
        self.assertEqual(rc, 1)
        self.assertIn("备份失败, 旧备份保持不动", err)

    def test_swap_failure_rolls_back(self):
        real_shutil = self._old[0]

        def _replace_boom(*_a, **_k):
            raise OSError("swap denied")

        os_ns = SimpleNamespace(path=os.path, replace=_replace_boom,
                                getcwd=os.getcwd, chdir=os.chdir)
        rc, _, err = self._run("backup", os_ns=os_ns)
        self.assertEqual(rc, 1)
        self.assertIn("备份失败, 旧备份保持不动", err)
        self.assertTrue(real_shutil is not None)

    def test_missing_project_root_exits_one(self):
        os.chdir(tempfile.gettempdir())
        out, err = io.StringIO(), io.StringIO()
        old_argv = sys.argv
        sys.argv = ["cube_usercode.py", "backup"]
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = cube_usercode.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
        finally:
            sys.argv = old_argv
            os.chdir(self.proj)
        self.assertEqual(rc, 1)
        self.assertIn("未找到工程根", err.getvalue())


if __name__ == "__main__":
    unittest.main()
