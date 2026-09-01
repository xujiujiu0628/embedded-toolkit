"""F-027 回归: Windows-only subprocess 常量的平台守卫静态钉 (2026-09-01 代管 R3).

CREATE_NEW_PROCESS_GROUP / CREATE_NEW_CONSOLE / DETACHED_PROCESS 仅在 CPython
subprocess 的 `if _mswindows:` 分支内绑定 (实证: subprocess.py 定义处位于
top-level 守卫块内), Linux/macOS 上裸属性访问即 AttributeError。verify.py 的
_step_capture_rtt() 曾裸用该常量 —— README「5 分钟上手」第 1 步示例即
"backend": "rtt", Linux 用户照抄, 首次真机运行必崩 (P0)。

判据: scripts/*.py 顶层 (不含 legacy/ 子目录) 任何 `subprocess.<WINONLY>`
直接属性访问必须与平台守卫同处一行 —— 仓库既有惯用法:
  1. `subprocess.X if sys.platform == "win32" else 0` (openocd_* 四件)
  2. `getattr(subprocess, "X", 0)` (wb/openocd_runtime; 构造性安全,
     正则匹配不到 getattr 形态, 天然豁免)
纯注释提及豁免。修前以 verify.py:134 证红, 修后证绿。
"""
import os
import re
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")

_WINONLY = ("CREATE_NEW_CONSOLE", "CREATE_NEW_PROCESS_GROUP",
            "CREATE_NO_WINDOW", "DETACHED_PROCESS")
_REF_RE = re.compile(r"subprocess\.(" + "|".join(_WINONLY) + r")\b")
_GUARD_MARKERS = ("sys.platform", '"win32"', "'win32'")


class WindowsOnlyConstantGuardTests(unittest.TestCase):
    def test_winonly_subprocess_constants_are_platform_guarded(self):
        offenders = []
        for fname in sorted(os.listdir(SCRIPTS_DIR)):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS_DIR, fname), encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    code = line.split("#", 1)[0]
                    if not _REF_RE.search(code):
                        continue
                    if not any(mk in code for mk in _GUARD_MARKERS):
                        offenders.append(
                            f"{fname}:{lineno}: {line.strip()}")
        self.assertEqual(
            [], offenders,
            "裸用 Windows-only subprocess 常量 (Linux 上 AttributeError), "
            '请改为惯用法: subprocess.X if sys.platform == "win32" else 0')


if __name__ == "__main__":
    unittest.main()
