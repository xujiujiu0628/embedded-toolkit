"""machine.json 缺失回退链回归 (开源门面 v0.3).

背景: machine.json 出库改本机维护后, 陌生 clone 没有该文件——load_machine
必须回退到入库模板 machine.example.json 并显式警告一次 (F-011 原则: 显式
报错/指引优于静默防御), 保证 `python -m unittest discover -s tests` 在新克隆
上直接可跑; 两档皆缺时报错信息必须含可行动指引 (复制 example 为 machine.json)。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import wb_common  # noqa: E402

EXAMPLE = {"uv4_exe": "<Keil UV4.exe 绝对路径>",
           "openocd_exe": "<openocd.exe 绝对路径>",
           "gcc_path": "<GNU Arm bin 目录>",
           "make_exe": "<make.exe 绝对路径>"}


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class MachineFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 模块级一次性警告标志: 每例独立可测
        self._patcher = mock.patch.object(wb_common, "_FALLBACK_WARNED", False)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _load_capturing_stderr(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = wb_common.load_machine()
        return result, err.getvalue()

    def test_missing_machine_falls_back_to_example(self):
        _write_json(os.path.join(self.tmp, "machine.example.json"), EXAMPLE)
        with mock.patch.object(wb_common, "TOOLKIT_ROOT", self.tmp):
            result, warned = self._load_capturing_stderr()
        self.assertEqual(result, EXAMPLE)
        self.assertIn("machine.json", warned)
        self.assertIn("machine.example.json", warned)

    def test_real_machine_preferred_and_silent(self):
        _write_json(os.path.join(self.tmp, "machine.example.json"), EXAMPLE)
        real = dict(EXAMPLE, openocd_exe=r"C:\real\openocd.exe")
        _write_json(os.path.join(self.tmp, "machine.json"), real)
        with mock.patch.object(wb_common, "TOOLKIT_ROOT", self.tmp):
            result, warned = self._load_capturing_stderr()
        self.assertEqual(result["openocd_exe"], r"C:\real\openocd.exe")
        self.assertEqual(warned, "")

    def test_neither_files_raises_actionable(self):
        with mock.patch.object(wb_common, "TOOLKIT_ROOT", self.tmp):
            with self.assertRaises(FileNotFoundError) as cm:
                wb_common.load_machine()
        self.assertIn("machine.example.json", str(cm.exception))

    def test_warning_emitted_only_once(self):
        _write_json(os.path.join(self.tmp, "machine.example.json"), EXAMPLE)
        with mock.patch.object(wb_common, "TOOLKIT_ROOT", self.tmp):
            _, first = self._load_capturing_stderr()
            _, second = self._load_capturing_stderr()
        self.assertIn("machine.json", first)
        self.assertEqual(second, "")


if __name__ == "__main__":
    unittest.main()
