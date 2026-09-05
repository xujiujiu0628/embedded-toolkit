r"""import 卫生钉 (F-054): verify / hardfault 不得在 import 期读 machine.json.

背景: 两脚本曾有模块级 `OPENOCD_EXE = load_machine()[...]`——import 即文件 IO,
machine.json 缺失时还向 stderr 吐回退警告; 6 个测试文件被迫以 "# noqa (import
期读 machine.json)" 注释豁免, CONTRIBUTING 禁令 #2 亦以此为存在理由之一。
F-054 惰性化后本钉防回潮: 在 wb_common.load_machine 上插 spy 断言 import 期
零调用, 并捕获 stderr 断言零输出。openocd_runtime / runtime_common 本就无
import 期 machine 读取 (F-029 防环约束), 一并经由 verify 的 import 链覆盖。
"""
import contextlib
import importlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import wb_common  # noqa: E402


class ImportSideEffectTests(unittest.TestCase):
    def _fresh_import(self, modname):
        """弹出模块缓存后, 在 load_machine spy + stderr 捕获下重新 import。

        返回 (module, stderr 全文)。spy 触发即说明 import 期发生了 machine 读取。"""
        saved = sys.modules.pop(modname, None)
        try:
            err = io.StringIO()
            with mock.patch.object(
                    wb_common, "load_machine",
                    side_effect=AssertionError(
                        "import 期不得调用 load_machine (F-054)")), \
                    contextlib.redirect_stderr(err):
                mod = importlib.import_module(modname)
            return mod, err.getvalue()
        finally:
            if saved is not None:
                sys.modules[modname] = saved

    def test_verify_import_has_no_machine_io(self):
        _, err = self._fresh_import("verify")
        self.assertEqual(
            "", err,
            "import verify 产生了 stderr 输出 (machine 回退警告?) —— "
            "模块级副作用回潮")

    def test_hardfault_import_has_no_machine_io(self):
        _, err = self._fresh_import("hardfault")
        self.assertEqual("", err)

    def test_verify_no_longer_binds_openocd_exe_constant(self):
        """OPENOCD_EXE 不再是 import 期绑定的模块常量（改为 _openocd_exe() 惰性解析）。"""
        mod, _ = self._fresh_import("verify")
        self.assertFalse(
            hasattr(mod, "OPENOCD_EXE"),
            "模块常量 OPENOCD_EXE 回潮 —— import 期副作用随之回潮")
        self.assertTrue(callable(getattr(mod, "_openocd_exe", None)),
                        "惰性解析函数 _openocd_exe 缺失")


if __name__ == "__main__":
    unittest.main()
