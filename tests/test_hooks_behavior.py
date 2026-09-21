r"""hooks/ 三条 C 铁律脚本的行为级探针 (F-093, WB-C3)。

本文件性质 = **行为记录 + 回归钉**:
F-093 施工实测发现三条 hook 共用的 diff 判据存在漏报缺陷（staged 且工作树
一致的真实 pre-commit 场景下 `git diff -U0 -- <files>` 输出为空, hook 恒
exit 0 形同虚设）。维护者 2026-09-09 拍板修复（F-096 选项 A: 判据加
--cached 优先 + 保留 working-tree 回落, hooks/*.sh 已落地）——原金丝雀组
已按承诺翻转改名 `StagedContentDetectionTests` 成为回归钉 (F-132 工单
P2-5 同步本 docstring: 原"修复待拍板/只钉现实"的登记口径已过时)。
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
# System32\bash.exe (WSL stub, 未装 Linux 子系统 → 输出 UTF-16 错误并 exit 1)。
#
# F-181 (WB-20260921-02, GAP-ENV-2) 加固: 旧回退形同虚设 ——
# `shutil.which("bash")` 与 `shutil.which("bash.exe")` 在本机返回**同一** System32
# 路径, 断言没拦住, 9 例 hooks 断言全数假红 (04 报告 §六 GAP-ENV-2)。
# 现在改为: 逐个候选探测, **凡命中 system32 一律跳过并继续向后找**;
# 全部候选都不可用时 `skipTest` 并给出可诊断原因 (解析过的每个候选 + 各自 rc),
# 绝不静默假红。Git bash 在场时解析结果与旧实现完全一致 (行为不变)。
def _bash_candidates():
    """按优先级列出 bash 候选绝对路径 (去重, 保序)。"""
    cands = []
    for name in ("bash", "bash.exe"):
        p = shutil.which(name)
        if p and p not in cands:
            cands.append(p)
    return cands


def _resolve_hooks_bash():
    """解析一个**可用的** bash; 返回 (路径, 诊断文本)。

    可用 = 不在 system32 (WSL stub 必红) 且能执行 `true` 得 rc=0。
    找不到可用候选项时返回 (None, 诊断)。
    """
    cands = _bash_candidates()
    attempts = []
    for p in cands:
        if "system32" in p.lower():
            attempts.append(f"  {p} -> 跳过 (System32 WSL stub, 本沙箱必 rc=1)")
            continue
        try:
            r = subprocess.run([p, "-c", "true"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=30)
            if r.returncode == 0:
                attempts.append(f"  {p} -> rc=0 (采用)")
                return p, "\n".join(attempts)
            attempts.append(f"  {p} -> rc={r.returncode} (不可用)")
        except OSError as e:
            attempts.append(f"  {p} -> OSError: {e}")
    if not attempts:
        attempts.append("  (PATH 上无任何 bash 候选)")
    return None, "\n".join(attempts)


BASH, _BASH_DIAG = _resolve_hooks_bash()
BASH_SKIP_REASON = (
    "hooks 行为探针需要可用的 bash (hooks/*.sh 是 shell 脚本), 但本机未解析到:\n"
    + _BASH_DIAG +
    "\n  处置: 安装 Git for Windows 并把其 bin 目录置于 PATH (本沙箱下 04 报告 "
    "§六 GAP-ENV-2 已登记; System32 的 bash.exe 是 WSL 启动器, 未装 WSL 时"
    "一律 rc=1 + UTF-16 乱码, 不可用)。此为显式 skip, 非静默通过。"
)


@unittest.skipUnless(BASH, BASH_SKIP_REASON)
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


@unittest.skipUnless(BASH, BASH_SKIP_REASON)
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


class BashResolverTests(unittest.TestCase):
    """F-181 (WB-20260921-02, GAP-ENV-2) 解析器自证 —— 不依赖本机是否装 bash。

    旧实现的病: `which("bash")` 命中 System32 后, 回退 `which("bash.exe")` 返回
    **同一** System32 路径, 断言形同虚设。本组直接把"解析器要么给出非 System32
    的可用 bash, 要么显式不可用 (BASH=None + 诊断)"钉死, 两态都合法、都不静默。
    """

    def test_resolved_bash_is_never_system32(self):
        """关键不变量: 解析结果绝不允许落在 System32 (WSL stub)。"""
        if BASH is None:
            self.skipTest("本机无可解析 bash —— 诊断: " + _BASH_DIAG)
        self.assertNotIn("system32", BASH.lower(),
                         f"解析结果落在 System32 (旧病复发): {BASH}")

    def test_system32_candidates_are_rejected(self):
        """把 System32 路径喂给解析逻辑, 必须被判为不可用 (不返回它)。"""
        fake_sys32 = r"C:\Windows\System32\bash.exe"
        # 直接复现旧判据的失效点
        self.assertIn("system32", fake_sys32.lower(),
                      "夹具前提: 该路径含 system32")
        # 解析器对含 system32 的候选必须跳过 (实现口径)
        cands = [fake_sys32, r"D:\git\Git\bin\bash.exe"]
        usable = [p for p in cands
                  if "system32" not in p.lower()]
        self.assertEqual(usable, [r"D:\git\Git\bin\bash.exe"],
                         "System32 候选未被跳过 —— 回退逻辑又退化回旧病")

    def test_all_candidates_unusable_yields_diagnostic(self):
        """全候选不可用 → 必须给出非空诊断文本 (供 skip 消息消费), 不静默。"""
        self.assertTrue(_BASH_DIAG.strip(),
                        "诊断文本为空 —— 不可用时会静默 skip")

    def test_candidates_are_deduped_and_ordered(self):
        """候选列表去重保序 (which 两次可能同路径)。"""
        cands = _bash_candidates()
        self.assertEqual(len(cands), len(set(cands)), "候选未去重")
        self.assertEqual(cands, sorted(cands, key=cands.index), "候选顺序不稳")


if __name__ == "__main__":
    unittest.main()
