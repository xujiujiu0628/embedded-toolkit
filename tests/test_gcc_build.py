"""F-006 回归: gcc_build 的 import time 上移模块顶部 (2026-08-30 代管 Day 3).

修复前: import time 在 if __name__ == "__main__" 块内, main() 引用 time —
作为脚本运行正常, 但任何未来调用方 import gcc_build 再调 main() 即 NameError
(verify.py 走 subprocess 故未触发, 属埋雷)。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gcc_build  # noqa: E402


class ModuleImportSafetyTests(unittest.TestCase):
    def test_time_bound_at_module_level(self):
        # 修复前 False (time 仅在 __main__ 块内绑定), 被调用方 import 即埋雷
        self.assertTrue(hasattr(gcc_build, "time"))

    def test_main_importable(self):
        from gcc_build import main  # noqa: F401  引用本身不炸
        self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main()
