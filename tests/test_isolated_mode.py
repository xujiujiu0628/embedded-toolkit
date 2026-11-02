r"""F-236: 隔离模式（-I / -P）下入口脚本必须能自行解析兄弟模块。

## 背景

Python 3.11+ 的 ``-I`` 隐含 ``-P``：不再把脚本所在目录放进 ``sys.path[0]``。
入口脚本若靠"脚本目录恰好是 sys.path[0]"隐式导入 ``wb_common`` 等兄弟模块，
在 ``python -I scripts/verify.py`` 下会 ModuleNotFoundError（2026-11-02 实测：

    File "scripts/verify.py", line 40, in <module>
      from wb_common import (TOOLKIT_ROOT, find_project_root, load_machine,
    ModuleNotFoundError: No module named 'wb_common'

）。修复方式是入口脚本显式把自身目录插进 ``sys.path``（见各入口顶部
``_SCRIPTS_DIR`` 引导块），本钉防止回归。

## 判据

对每个入口脚本在 ``-I`` 下跑 ``--help``：stderr 不得出现
``ModuleNotFoundError``，退出码 ∈ {0, 2}（argparse ``--help`` 为 0；
个别脚本无 ``--help`` 分支时按用法错误为 2）。

## 3.10 腿说明

``-P`` 是 3.11 新增；3.10 上 ``-I`` 不剥离脚本目录，本钉在该腿是弱断言
（只保证入口能跑）。真正的隔离语义由 3.12 腿承接，不静默跳过。
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

# 与 pyproject.toml 的 [project.scripts] 一一对应：装了 console 入口的脚本
# 必须同时能在源码树里以 python -I 直接跑。
ENTRY_SCRIPTS = (
    "verify.py",
    "release.py",
    "release_audit.py",
    "gcc_build.py",
    "expectations_lint.py",
    "gen_periph.py",
    "rm_lookup.py",
    "hardfault.py",
)


class IsolatedModeImportTests(unittest.TestCase):
    """每个入口在 -I 下独立起进程，互不污染 sys.modules。"""

    def test_entries_import_under_isolated_mode(self):
        for name in ENTRY_SCRIPTS:
            with self.subTest(entry=name):
                env = dict(os.environ)
                # CI Windows 子进程默认 cp1252，--help 里的中文会
                # UnicodeEncodeError → rc=1；与 ci.yml 的 UTF-8 咒语同款。
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                proc = subprocess.run(
                    [sys.executable, "-I", os.path.join(SCRIPTS, name), "--help"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    cwd=ROOT,
                    env=env,
                )
                combined = (proc.stdout or "") + (proc.stderr or "")
                self.assertNotIn(
                    "ModuleNotFoundError", combined,
                    msg=f"{name} 在 -I 下导入失败:\n{combined[-2000:]}",
                )
                self.assertIn(
                    proc.returncode, (0, 2),
                    msg=f"{name} 在 -I 下 rc={proc.returncode}:\n{combined[-2000:]}",
                )


if __name__ == "__main__":
    unittest.main()
