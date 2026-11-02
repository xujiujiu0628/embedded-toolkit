r"""F-237: cube_usercode 的 diff / main / 空目录分支补测。

## 覆盖对象

`scripts/cube_usercode.py` 此前 58% 覆盖（2026-11-02 实测）：`cmd_diff`
整段、`main` 派发、以及 backup/restore 的"没有文件/没有备份"分支从未执行。
数据保全主路径（逐字节保真/事务化/原子交换）已由 `test_cube_usercode.py`
覆盖，本文件只补命令面，不重复钉那些契约。

## 夹具

临时工程 = `.workbench/config.json` + `Core/Src|Inc` + `.cube_backup`；
走 CLI 子进程（rc 即真实退出码），与既有测试同口径。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SCRIPT = os.path.join(SCRIPTS, "cube_usercode.py")


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _block(name: str, code: str) -> str:
    return f"/* USER CODE BEGIN {name} */\n{code}\n/* USER CODE END {name} */\n"


def _make_project(tmpdir: str, with_backup: bool = True) -> str:
    proj = os.path.join(tmpdir, "proj")
    _write(os.path.join(proj, ".workbench", "config.json"), json.dumps({}))
    _write(os.path.join(proj, "Core", "Src", "main.c"), _block("2", "int x = 1;"))
    if with_backup:
        _write(os.path.join(proj, ".cube_backup", "Core", "Src", "main.c"),
               _block("2", "int x = 2;"))
    return proj


def _run(proj: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=proj, timeout=120, env=env,
    )


class ProjectRootTests(unittest.TestCase):
    def test_missing_workbench_marker_exits_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proc = _run(tmp, "diff")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("未找到工程根", proc.stderr)


class EmptyProjectTests(unittest.TestCase):
    def test_backup_without_cubemx_files_exits_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = os.path.join(tmp, "proj")
            _write(os.path.join(proj, ".workbench", "config.json"), "{}")
            proc = _run(proj, "backup")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("没有找到 CubeMX 生成的文件", proc.stdout)

    def test_restore_without_backup_exits_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp, with_backup=False)
            proc = _run(proj, "restore")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("没有找到备份目录", proc.stdout)

    def test_default_action_is_restore(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp, with_backup=False)
            proc = _run(proj)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("没有找到备份目录", proc.stdout)

    def test_invalid_action_rejected_by_argparse(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp)
            proc = _run(proj, "bogus")
        self.assertEqual(proc.returncode, 2)


class DiffTests(unittest.TestCase):
    def test_diff_without_backup_exits_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp, with_backup=False)
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("没有找到备份目录", proc.stdout)

    def test_changed_block_reported(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp)
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[CHANGED]", proc.stdout)
        self.assertIn("USER CODE 2", proc.stdout)

    def test_identical_blocks_are_silent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp, with_backup=False)
            _write(os.path.join(proj, ".cube_backup", "Core", "Src", "main.c"),
                   _block("2", "int x = 1;"))
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("[CHANGED]", proc.stdout)

    def test_new_file_reported(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp)
            _write(os.path.join(proj, "Core", "Src", "gpio.c"),
                   _block("2", "int g = 0;"))
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[NEW]", proc.stdout)
        self.assertIn("gpio.c", proc.stdout)

    def test_cleared_block_warns(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp)
            _write(os.path.join(proj, "Core", "Src", "main.c"), _block("2", ""))
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("清空了此区块", proc.stdout)

    def test_added_block_notes_new_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = _make_project(tmp, with_backup=False)
            _write(os.path.join(proj, ".cube_backup", "Core", "Src", "main.c"),
                   _block("2", ""))
            _write(os.path.join(proj, "Core", "Src", "main.c"),
                   _block("2", "int x = 1;"))
            proc = _run(proj, "diff")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("新增了内容", proc.stdout)


if __name__ == "__main__":
    unittest.main()
