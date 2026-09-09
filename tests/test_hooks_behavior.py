r"""hooks/ 三条 C 铁律脚本的行为级探针 (F-093, WB-C3)。

⚠️ 本文件性质 = **行为记录 + 缺陷登记**, 不是回归钉:
F-093 施工实测发现三条 hook 共用的 diff 判据存在**漏报缺陷**（见
CanaryDetectionGapTests）——staged 且工作树一致的真实 pre-commit 场景下
`git diff -U0 -- <files>` (worktree vs index) 输出为空, 全部 hook 恒 exit 0,
**形同虚设**。hooks/ 是 CONTRIBUTING 禁区（判据变更须 issue 单独论证）,
故本文件只把现实行为钉住 + 登记缺陷, 修复交维护者拍板。

已登记缺陷（F-096 待拍板）:
  gap-1 三 hook 的 `git diff -U0 -- $files` 缺 --cached, staged 内容永不入检
  gap-2 同理 warn-volatile 的第二路也漏; 且 `grep -ql ... $files` 对已删除
       文件报"文件不存在"
修复选项（二选一, 维护者拍板）:
  A. 判据改 `git diff --cached -U0` + 保留 working-tree 回落（最小改动）
  B. 换 pre-commit framework（重）
"""
import os
import shutil
import subprocess
import tempfile
import unittest


class HookProbeBase(unittest.TestCase):
    """真实 git 仓 fixture + 直接执行 hook 脚本"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
            HOME=self.ws)
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        # 关键: 关掉 autocrlf —— 全局 true 时 git diff 输出行尾漂移会让
        # hook 里 grep -E 的词边界/行匹配失灵 (F-093 施工实录)
        self._git("config", "core.autocrlf", "false")
        with open(os.path.join(self.ws, "README.md"), "w") as f:
            f.write("base\n")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "base")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)

    def _git(self, *args):
        return subprocess.run(
            ["git"] + list(args), cwd=self.ws, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            env=self.env, timeout=30)

    def _stage_c(self, name, content):
        path = os.path.join(self.ws, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        self._git("add", name)

    def _run_hook(self, hook):
        r = subprocess.run(
            [BASH, os.path.join(HOOKS_DIR, hook)], cwd=self.ws,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        return r.returncode, (r.stdout or "") + (r.stderr or "")


HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "hooks")

# ⚠️ 必须用绝对路径: subprocess 的 "bash" 会被 CreateProcess 安全搜索命中
# System32ash.exe (WSL stub, 未装 Linux 子系统 → 输出 UTF-16 错误并 exit 1)。
# shutil.which 沿 PATH 找到 Git for Windows 的 bash —— 但为了防 CI/其他机器
# 的 PATH 漂移, 这里同样用 which 结果并断言不是 System32。
BASH = shutil.which("bash") or ""
if "system32" in BASH.lower():
    BASH = shutil.which("bash.exe") or BASH


class HookWorktreePathTests(HookProbeBase):
    """工作树路径 (dirty worktree) 下 hook 判据有效——脚本双路径的第二条"""

    def test_malloc_in_modified_worktree_blocks(self):
        """基线已有文件 + 工作树改动(未 add) → working-tree diff 路径命中"""
        self._stage_c("app.c", "void f(void);\n")
        self._git("commit", "-q", "-m", "c")
        with open(os.path.join(self.ws, "app.c"), "a",
                  encoding="utf-8", newline="\n") as f:
            f.write("void g(void) {\n    char *p = malloc(4);\n}\n")
        code, out = self._run_hook("block-malloc.sh")
        self.assertEqual(code, 2, f"工作树路径应命中 malloc: {out}")
        self.assertIn("动态内存分配", out)

    def test_hal_delay_in_modified_worktree_blocks(self):
        self._stage_c("app.c", "void f(void);\n")
        self._git("commit", "-q", "-m", "c")
        with open(os.path.join(self.ws, "app.c"), "a",
                  encoding="utf-8", newline="\n") as f:
            f.write("void g(void) {\n    HAL_Delay(10);\n}\n")
        code, out = self._run_hook("block-hal-delay-in-logic.sh")
        self.assertEqual(code, 2, "工作树路径应命中 HAL_Delay")

    def test_volatile_warning_in_modified_worktree(self):
        self._stage_c("isr.c", "#include <stdint.h>\n"
                               "void USART1_IRQHandler(void);\n")
        self._git("commit", "-q", "-m", "c")
        with open(os.path.join(self.ws, "isr.c"), "a",
                  encoding="utf-8", newline="\n") as f:
            f.write("static uint32_t tick = 0;\n")
        code, out = self._run_hook("warn-volatile-missing.sh")
        self.assertEqual(code, 0, "警告级永不阻断")
        self.assertIn("volatile", out)


class StagedContentDetectionTests(HookProbeBase):
    """F-096 修复钉: staged 且工作树一致 (真实 pre-commit 时刻) 的内容
    必须被检查。维护者 2026-09-09 拍板选项 A (判据加 --cached 优先);
    修复前的金丝雀组已按承诺翻转并改名。"""

    def _staged_only(self, name, content):
        """staged 且工作树一致 (真实 pre-commit 时刻的状态)"""
        path = os.path.join(self.ws, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        self._git("add", name)
        # 工作树与 index 一致, 未 commit

    def test_malloc_staged_is_blocked_f096(self):
        """staged malloc 必须阻断 (F-096 修复后翻转)"""
        self._staged_only("app.c", "int main(void) {" + chr(10)
                                   + "    char *p = malloc(16);" + chr(10) + "}" + chr(10))
        code, out = self._run_hook("block-malloc.sh")
        self.assertEqual(code, 2, f"staged malloc 必须拦截: {out}")
        self.assertIn("动态内存分配", out)

    def test_hal_delay_staged_is_blocked_f096(self):
        self._staged_only("logic.c", "void poll(void) {" + chr(10)
                                   + "    HAL_Delay(1);" + chr(10) + "}" + chr(10))
        code, out = self._run_hook("block-hal-delay-in-logic.sh")
        self.assertEqual(code, 2, f"staged HAL_Delay 必须拦截: {out}")

    def test_volatile_staged_warns_f096(self):
        self._staged_only("isr.c", "#include <stdint.h>" + chr(10)
                                   + "void USART1_IRQHandler(void);" + chr(10)
                                   + "static uint32_t tick = 0;" + chr(10))
        code, out = self._run_hook("warn-volatile-missing.sh")
        self.assertEqual(code, 0, "警告级仍不阻断")
        self.assertIn("volatile", out, "staged 缺 volatile 必须提醒")

    def test_non_c_changes_pass_all_hooks(self):
        """非 .c/.h 变更不触发（该判据两个路径均成立）"""
        path = os.path.join(self.ws, "docs.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("malloc free HAL_Delay\n")
        self._git("add", "docs.md")
        for hook in ("block-malloc.sh", "block-hal-delay-in-logic.sh",
                     "warn-volatile-missing.sh"):
            with self.subTest(hook=hook):
                code, _ = self._run_hook(hook)
                self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
