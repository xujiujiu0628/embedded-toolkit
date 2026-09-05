r"""失败现场 agent_hint 路径来源回归 (开源门面 C5/C6b).

背景: 提示串曾硬编码维护者机器的工作区绝对路径 (盘符:\...\embedded-toolkit\...),
对陌生 clone 是坏指引——verify 的失败提示必须随 TOOLKIT_ROOT 推导 (用 patch
证明"跟着变量走"), gen_periph 的生成物注释必须用仓相对命令; 静态守卫防源码回潮
(2026-09-01 历史重写后改通用盘符判据: 任何 `盘符:/(Users|claude)` 形态都视为回潮,
归一化转义后匹配)。

F-053: 本 docstring 曾用非原始形态, 其中 `\.` 触发 SyntaxWarning (3.12+),
coverage_lint 的 AST 全扫每轮被污染 —— 改 raw 并由 test_source_hygiene 防回潮。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
FAKE_TK = "X:\\fake-toolkit"


class FlashCaptureHintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _hint_for(self, result):
        with mock.patch.object(verify, "WORKSPACE", self.tmp), \
             mock.patch.object(verify, "TOOLKIT_ROOT", FAKE_TK):
            verify._save_failure_context(result, 0)
        with open(os.path.join(self.tmp, ".workbench", "build",
                               "last_failure.json"), encoding="utf-8") as f:
            return json.load(f)["agent_hint"]

    def test_flash_failed_hint_follows_toolkit_root(self):
        hint = self._hint_for({"status": "flash_failed",
                               "steps": {"flash": {"status": "flash_failed",
                                                   "attempts": []}}})
        self.assertIn(os.path.join(FAKE_TK, "scripts", "hardfault.py"), hint)

    def test_capture_failed_hint_follows_toolkit_root(self):
        hint = self._hint_for({"status": "capture_failed",
                               "steps": {"capture": {"status": "capture_failed"}}})
        self.assertIn(os.path.join(FAKE_TK, "scripts", "hardfault.py"), hint)


_MAINTAINER_PATH = re.compile(r"[A-Za-z]:[\\/]{1,2}(Users|claude)")


class NoHardcodedMaintainerPathsTest(unittest.TestCase):
    """静态守卫: 提示/生成物源码不得嵌入维护者机器绝对路径 (通用盘符判据)。"""

    @staticmethod
    def _normalized(name):
        with open(os.path.join(SCRIPTS_DIR, name), encoding="utf-8") as f:
            return f.read().replace("\\\\", "\\")

    def test_gen_periph_source_clean(self):
        self.assertIsNone(_MAINTAINER_PATH.search(self._normalized("gen_periph.py")))

    def test_verify_source_clean(self):
        self.assertIsNone(_MAINTAINER_PATH.search(self._normalized("verify.py")))


if __name__ == "__main__":
    unittest.main()
