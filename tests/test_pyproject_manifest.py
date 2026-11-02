r"""F-236: pyproject.toml 的模块清单与 console 入口必须和 scripts/ 现状一致。

## 为什么需要这颗钉

`pyproject.toml` 用 `py-modules` 平铺列出 47 个模块（`package-dir = scripts`，
不搬目录）。新增/删除脚本时若忘记同步清单，`pip install` 会静默漏装，
而源码树里的 `python scripts/xxx.py` 仍然全绿——属于"只在安装形态暴露"的
漂移。本钉把这份清单钉到 `scripts/*.py` 的实际集合上。

## 判据

1. `py-modules` 集合 == `scripts/*.py` 的 stem 集合（双向，多一个少一个都红）；
2. `[project.scripts]` 的每个 `module:attr`：module 在清单内，且模块里确有
   顶层 `def attr(`；
3. console 命令统一 `etk-` 前缀（避免装进全局后与 `verify`/`release` 这类
   通用名撞车）；
4. `dynamic = ["version"]` 且版本源是 `VERSION` 文件——版本唯一事实源不变。

## 3.10 腿说明

`tomllib` 是 3.11+ 标准库；3.10 腿显式 skip（消息写明由 3.12 腿承接），
与 `test_py_floor.py` 同口径，不静默通过。
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
SCRIPTS = os.path.join(ROOT, "scripts")

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


@unittest.skipUnless(tomllib is not None, "tomllib 需 3.11+；本钉由 CI 3.12 腿承接")
class PyprojectManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PYPROJECT, "rb") as fh:
            cls.cfg = tomllib.load(fh)
        cls.modules = set(cls.cfg["tool"]["setuptools"]["py-modules"])
        cls.scripts = {
            name[:-3]
            for name in os.listdir(SCRIPTS)
            if name.endswith(".py") and os.path.isfile(os.path.join(SCRIPTS, name))
        }

    def test_py_modules_match_scripts_directory(self):
        self.assertEqual(
            self.scripts - self.modules, set(),
            msg=f"scripts/ 里有但 py-modules 漏装: {sorted(self.scripts - self.modules)}",
        )
        self.assertEqual(
            self.modules - self.scripts, set(),
            msg=f"py-modules 有但 scripts/ 已无: {sorted(self.modules - self.scripts)}",
        )

    def test_console_scripts_point_at_real_mains(self):
        entries = self.cfg["project"]["scripts"]
        self.assertTrue(entries, "至少要有 etk-* console 入口")
        for name, target in entries.items():
            with self.subTest(entry=name):
                self.assertTrue(name.startswith("etk-"), f"{name} 未用 etk- 前缀")
                module, _, attr = target.partition(":")
                self.assertIn(module, self.modules, f"{name} 指向未安装模块 {module}")
                with open(os.path.join(SCRIPTS, module + ".py"), encoding="utf-8") as fh:
                    src = fh.read()
                self.assertRegex(
                    src, rf"(?m)^def {re.escape(attr)}\(",
                    f"{name} 指向 {module}.{attr}，但模块里没有该顶层函数",
                )

    def test_version_comes_from_version_file(self):
        project = self.cfg["project"]
        self.assertIn("version", project.get("dynamic", []))
        version_file = self.cfg["tool"]["setuptools"]["dynamic"]["version"]["file"]
        self.assertEqual(version_file, "VERSION")
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            self.assertRegex(fh.read().strip(), r"^\d+\.\d+(\.\d+)?$")


if __name__ == "__main__":
    unittest.main()
