r"""F-239: cube_usercode 的 backup/restore 主路径进程内补测。

## 覆盖对象

`scripts/cube_usercode.py` 此前 69% 覆盖（2026-11-02 实测）：`cmd_backup`
与 `cmd_restore` 的落盘/注入主路径此前只走子进程用例（coverage 不追踪）。
本文件在进程内调 `main()`，把备份、恢复、冲突提示纳入覆盖率账本。

## 夹具

临时工程 = `.workbench/config.json` + `Core/Src/main.c`；模块全局
（`PROJECT_ROOT` 等）每例复位，cwd 用 addCleanup 还原。
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import cube_usercode  # noqa: E402


def _block(name, code):
    return f"/* USER CODE BEGIN {name} */\n{code}\n/* USER CODE END {name} */\n"


class CubeRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.proj, ".workbench"))
        os.makedirs(os.path.join(self.proj, "Core", "Src"))
        self.main_c = os.path.join(self.proj, "Core", "Src", "main.c")
        self._write(self.main_c, _block("2", "int x = 1;"))
        with open(os.path.join(self.proj, ".workbench", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        self._old_cwd = os.getcwd()
        self._reset()
        self.addCleanup(self._restore)

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _reset(self):
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

    def _restore(self):
        os.chdir(self._old_cwd)
        self._reset()

    def _call(self, action):
        out, err = io.StringIO(), io.StringIO()
        old_argv = sys.argv
        sys.argv = ["cube_usercode.py", action]
        os.chdir(self.proj)
        self._reset()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = cube_usercode.main()
                except SystemExit as exc:
                    rc = exc.code if exc.code is not None else 0
        finally:
            sys.argv = old_argv
            self._reset()
        return rc, out.getvalue(), err.getvalue()

    def test_backup_then_restore_round_trip(self):
        rc, out, _ = self._call("backup")
        self.assertEqual(rc, 0)
        self.assertIn("[OK] 已备份 1 个文件", out)
        backup = os.path.join(self.proj, ".cube_backup", "Core", "Src", "main.c")
        self.assertTrue(os.path.isfile(backup))

        # CubeMX 重生成后 USER CODE 区块变空
        self._write(self.main_c, _block("2", ""))
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 0)
        self.assertIn("[OK] 恢复完成", out)
        with open(self.main_c, encoding="utf-8") as fh:
            self.assertIn("int x = 1;", fh.read())

    def test_restore_conflict_when_markers_missing(self):
        rc, _, _ = self._call("backup")
        self.assertEqual(rc, 0)
        self._write(self.main_c, "int no_markers = 0;\n")
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 0)
        self.assertIn("无 USER CODE 标记", out)

    def test_backup_without_files_exits_one(self):
        os.remove(self.main_c)
        rc, out, _ = self._call("backup")
        self.assertEqual(rc, 1)
        self.assertIn("没有找到 CubeMX 生成的文件", out)

    def test_diff_after_backup_is_silent(self):
        self._call("backup")
        rc, out, _ = self._call("diff")
        self.assertEqual(rc, 0)
        self.assertNotIn("[CHANGED]", out)


if __name__ == "__main__":
    unittest.main()
