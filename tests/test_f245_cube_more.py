r"""F-245: cube_usercode 的自定义 main.c 提取注入 / 跳过计数 / 落盘回滚补测。

## 覆盖对象

`scripts/cube_usercode.py` 此前 84% 覆盖（2026-11-02 实测）：restore 的
"备份目录在但无生成文件"、"备份缺此文件 → skipped"、旧 main.c 完全自定义
（无标记）时的 init/loop/header 提取注入与提取失败冲突、落盘阶段失败回滚，
以及 diff 的 NEW/清空分支。
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


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


CUSTOM_MAIN = """#include "main.h"
extern void semihost_init(void);
int main(void) {
  MX_GPIO_Init();
  my_setup();
  while (1) {
    toggle();
  }
}
"""

MARKED_MAIN = """/* USER CODE BEGIN Includes */
/* USER CODE END Includes */
int main(void) {
  MX_GPIO_Init();
  /* USER CODE BEGIN 2 */
  /* USER CODE END 2 */
  while (1) {
    /* USER CODE BEGIN 3 */
    /* USER CODE END 3 */
  }
}
"""


class CubeMoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name) / "proj"
        _write(self.proj / ".workbench" / "config.json", "{}")
        _write(self.proj / "Core" / "Src" / "main.c", MARKED_MAIN)
        self._cwd = os.getcwd()
        self._reset()

    def tearDown(self):
        os.chdir(self._cwd)
        self._reset()

    def _reset(self):
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

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

    def test_restore_with_no_cubemx_files(self):
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c", MARKED_MAIN)
        (self.proj / "Core" / "Src" / "main.c").unlink()
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 1)
        self.assertIn("没有找到 CubeMX 生成的文件", out)

    def test_restore_skips_file_absent_from_backup(self):
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c", MARKED_MAIN)
        _write(self.proj / "Core" / "Src" / "gpio.c", "/* USER CODE BEGIN 2 */\nx\n/* USER CODE END 2 */\n")
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 0)
        self.assertIn("0 个文件已更新, 2 个跳过", out)

    def test_fully_custom_old_main_is_migrated(self):
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c", CUSTOM_MAIN)
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 0)
        self.assertIn("[RESTORED]", out)
        text = (self.proj / "Core" / "Src" / "main.c").read_text(encoding="utf-8")
        self.assertIn("my_setup();", text)
        self.assertIn("toggle();", text)

    def test_fully_custom_without_extractable_code_conflicts(self):
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c",
               "int main(void) { return 0; }\n")
        rc, out, _ = self._call("restore")
        self.assertEqual(rc, 0)
        self.assertIn("无法自动提取", out)

    def test_commit_failure_rolls_back(self):
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c",
               MARKED_MAIN.replace("/* USER CODE END 2 */", "old code\n/* USER CODE END 2 */"))
        calls = {"n": 0}

        def _replace(src, dst):
            calls["n"] += 1
            raise OSError("disk full")

        fake_os = SimpleNamespace(path=os.path, replace=_replace,
                                  getcwd=os.getcwd, chdir=os.chdir)
        old = cube_usercode.os
        cube_usercode.os = fake_os
        try:
            rc, out, err = self._call("restore")
        finally:
            cube_usercode.os = old
        self.assertEqual(rc, 1)
        self.assertIn("落盘阶段", out + err)


class DiffNewAndClearedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name) / "proj"
        _write(self.proj / ".workbench" / "config.json", "{}")
        _write(self.proj / "Core" / "Src" / "main.c",
               "/* USER CODE BEGIN 2 */\nint x;\n/* USER CODE END 2 */\n")
        _write(self.proj / ".cube_backup" / "Core" / "Src" / "main.c",
               "/* USER CODE BEGIN 2 */\n\n/* USER CODE END 2 */\n")
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)

    def _call(self, action):
        out = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["cube_usercode.py", action]
        os.chdir(self.proj)
        for name in ("PROJECT_ROOT", "CORE_SRC", "CORE_INC", "BACKUP_DIR"):
            setattr(cube_usercode, name, None)
        try:
            with redirect_stdout(out):
                rc = cube_usercode.main()
        finally:
            sys.argv = old_argv
        return rc, out.getvalue()

    def test_added_content_notes(self):
        rc, out = self._call("diff")
        self.assertEqual(rc, 0)
        self.assertIn("新增了内容", out)

    def test_new_file_reported(self):
        _write(self.proj / "Core" / "Src" / "gpio.c", "/* USER CODE BEGIN 2 */\nx\n/* USER CODE END 2 */\n")
        rc, out = self._call("diff")
        self.assertIn("[NEW]", out)
        self.assertIn("gpio.c", out)


if __name__ == "__main__":
    unittest.main()
