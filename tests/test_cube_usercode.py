r"""F-178 (WB-20260920-04, H-2 + M-10) cube_usercode 数据保全回归钉。

背景: 本工具是 CubeMX 重生成后恢复用户代码的**唯一保全工具** ——
一旦它自己损坏要保护的代码, 用户没有任何兜底。

契约:
  1. restore 注入的 USER CODE 原文必须**逐字节保真**。旧实现把旧文件
     源码原文拼进 `re.sub` 的 replacement 模板 (`rf'\1\n{code}\3'`),
     反斜杠被模板二次解释: `\r\n` 变真实 CR/LF (C 字符串字面量被拆断,
     编译必炸)、`\0` 变真实 NUL 字节写进源文件、正文含 `\d`/`\s` 直接抛
     `re.PatternError` 使 restore 崩溃;
  2. restore **事务化**: 全部文件先在内存组装成功再统一落盘 —— 任一文件
     中途失败, 原文件一个都不许动 (旧实现逐文件即时写, 前几个文件已写坏
     而末尾照报 "[OK] 恢复完成");
  3. backup **原子性**: 新备份先写临时目录、成功后整体交换 —— 复制中途
     失败时旧备份 (.cube_backup/) 必须仍可读出完整旧内容 (旧实现先
     `rmtree` 旧备份再复制, 失败即两头皆失)。

用例走 CLI 子进程 (rc 语义即真实退出码); ⑤ 需注入复制中途失败, 走模块内
mock (子进程内无法注入)。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "cube_usercode.py")

sys.path.insert(0, os.path.join(ROOT, "scripts"))

import cube_usercode  # noqa: E402

# ── 载荷: 全部是真实 C 代码里极常见的反斜杠字面量 ──
PLAIN = "  int counter = 0;"
# ① printf 的 \r\n 转义 (串口打印必用)
PAYLOAD_CRLF = '  printf("hi\\r\\n");'
# ② \0 字符字面量
PAYLOAD_NUL = "  char c = '\\0';"
# ③ 正文含 \d 的注释 (re replacement 的非法转义)
PAYLOAD_BACKD = "  // match \\d+ digits"


def main_c(user_code):
    """CubeMX 风格的最小 main.c (单块 USER CODE 2)。"""
    return ('#include "main.h"\n'
            '\n'
            'int main(void)\n'
            '{\n'
            '  /* USER CODE BEGIN 2 */\n'
            f'{user_code}\n'
            '  /* USER CODE END 2 */\n'
            '  while (1) { }\n'
            '}\n')


def gpio_c(user_code, block="2"):
    """第二个文件 (验证多文件事务性)。"""
    return ('#include "main.h"\n'
            '\n'
            'void MX_GPIO_Init(void)\n'
            '{\n'
            f'  /* USER CODE BEGIN {block} */\n'
            f'{user_code}\n'
            f'  /* USER CODE END {block} */\n'
            '}\n')


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def mk_project(ws, core_files, backup_files=None):
    """建工程 fixture: ws 为工程根 (含 .workbench/config.json 标记)。

    core_files / backup_files = {"Core/Src/main.c": 文本}。
    """
    _write(os.path.join(ws, ".workbench", "config.json"),
           json.dumps({"builder": "gcc"}))
    for rel, text in core_files.items():
        _write(os.path.join(ws, *rel.split("/")), text)
    for rel, text in (backup_files or {}).items():
        _write(os.path.join(ws, ".cube_backup", *rel.split("/")), text)


def cli(action, cwd):
    """子进程跑 CLI, 返回 CompletedProcess (rc 即真实退出码)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, SCRIPT, action], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, env=env)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class RestoreByteFidelityTests(unittest.TestCase):
    """① ② ③: 注入载荷必须逐字节保真。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # 只读夹具先恢复可写, 否则 Windows 上删不掉
        for r, _d, fs in os.walk(self.ws):
            for f in fs:
                try:
                    os.chmod(os.path.join(r, f), stat.S_IWRITE)
                except OSError:
                    pass
        shutil.rmtree(self.ws, ignore_errors=True)

    def _roundtrip(self, payload):
        """旧文件块含 payload → 新文件块空 → restore → 返回 (rc, 结果字节, stderr)"""
        mk_project(
            self.ws,
            {"Core/Src/main.c": main_c("")},
            {"Core/Src/main.c": main_c(payload)})
        r = cli("restore", self.ws)
        return (r.returncode,
                read_bytes(os.path.join(self.ws, "Core", "Src", "main.c")),
                r.stderr or "")

    def test_plain_payload_is_injected_at_all(self):
        # 夹具自证: 纯 ASCII 载荷必须被真的注入进去 —— 否则下面三条会
        # 因"什么都没做"而假绿。
        rc, data, _err = self._roundtrip(PLAIN)
        self.assertEqual(rc, 0)
        self.assertIn(PLAIN.encode("utf-8"), data)

    def test_crlf_escape_survives_byte_for_byte(self):
        # ① \r\n 必须原样回来: 反斜杠字面量在位, 且不得退化成真实控制字符。
        # 注: 落盘走 write_text 默认 newline 翻译, 整个文件在 Windows 上是
        # CRLF 行尾 —— 那不是本缺陷, 故只针对**字符串字面量内部**取证。
        rc, data, _err = self._roundtrip(PAYLOAD_CRLF)
        self.assertEqual(rc, 0)
        self.assertIn(b'printf("hi\\r\\n");', data,
                      f"反斜杠字面量被 re.sub 模板吃掉: {data!r}")
        self.assertNotIn(b'printf("hi\r\n");', data,
                         f"字面量退化成真实 CR/LF 控制字符: {data!r}")

    def test_nul_escape_does_not_become_real_nul_byte(self):
        # ② '\0' 必须保持两字符转义, 不得落真实 NUL 字节
        rc, data, _err = self._roundtrip(PAYLOAD_NUL)
        self.assertEqual(rc, 0)
        self.assertIn(b"'\\0'", data)
        self.assertNotIn(b"\x00", data,
                         f"源文件出现真实 NUL 字节: {data!r}")

    def test_backslash_d_in_body_does_not_crash_restore(self):
        # ③ 正文含 \d → 旧实现 re.PatternError 崩溃且前面文件已写坏
        rc, data, err = self._roundtrip(PAYLOAD_BACKD)
        self.assertEqual(rc, 0, f"restore 崩溃: rc={rc}\nstderr={err}")
        self.assertIn(b"\\d+", data)
        self.assertNotIn("PatternError", err)


class RestoreTransactionTests(unittest.TestCase):
    """④: 中途失败 → 原文件一个都不许动 + rc != 0。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for r, _d, fs in os.walk(self.ws):
            for f in fs:
                try:
                    os.chmod(os.path.join(r, f), stat.S_IWRITE)
                except OSError:
                    pass
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_midway_write_failure_leaves_every_original_untouched(self):
        mk_project(
            self.ws,
            {"Core/Src/gpio.c": gpio_c(""),
             "Core/Src/main.c": main_c("")},
            {"Core/Src/gpio.c": gpio_c("  int gpio_ready = 1;"),
             "Core/Src/main.c": main_c("  int main_ready = 1;")})

        gpio_path = os.path.join(self.ws, "Core", "Src", "gpio.c")
        main_path = os.path.join(self.ws, "Core", "Src", "main.c")
        before_gpio = read_bytes(gpio_path)
        before_main = read_bytes(main_path)

        # 制造真实落盘失败: main.c 只读。find_cubemx_files 排序下 gpio.c
        # 先于 main.c —— 旧实现会先把 gpio.c 写坏, 再在 main.c 上炸掉。
        os.chmod(main_path, stat.S_IREAD)
        try:
            r = cli("restore", self.ws)
        finally:
            os.chmod(main_path, stat.S_IWRITE)

        self.assertNotEqual(r.returncode, 0,
                            f"中途失败必须非零退出\nstdout={r.stdout}")
        self.assertEqual(read_bytes(gpio_path), before_gpio,
                         "gpio.c 已被写坏 (事务化缺失) — 原文件必须保持不动")
        self.assertEqual(read_bytes(main_path), before_main,
                         "main.c 原文件被动过")


class BackupAtomicityTests(unittest.TestCase):
    """⑤: 复制中途失败 → 旧备份仍可读出完整旧内容。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_failed_copy_keeps_old_backup_readable(self):
        mk_project(
            self.ws,
            {"Core/Src/gpio.c": gpio_c("  int gpio_new = 2;"),
             "Core/Src/main.c": main_c("  int main_new = 2;")},
            {"Core/Src/gpio.c": gpio_c("  int gpio_old = 1;"),
             "Core/Src/main.c": main_c("  int main_old = 1;")})

        # 注入"复制中途失败": 第 2 次 copy2 抛 OSError。
        real_copy2 = shutil.copy2
        state = {"n": 0}

        def flaky_copy2(src, dst, **kw):
            state["n"] += 1
            if state["n"] == 2:
                raise OSError(13, "模拟: 文件被编辑器占用")
            return real_copy2(src, dst, **kw)

        cube_usercode.PROJECT_ROOT = None
        cube_usercode.CORE_SRC = None
        cube_usercode.CORE_INC = None
        cube_usercode.BACKUP_DIR = None
        prev = os.getcwd()
        os.chdir(self.ws)
        try:
            with mock.patch.object(cube_usercode.shutil, "copy2",
                                   side_effect=flaky_copy2):
                try:
                    rc = cube_usercode.cmd_backup()
                except OSError:
                    rc = 1  # 未捕获 → CLI 侧同为非零退出 (与 ④ 同口径)
        finally:
            os.chdir(prev)
            cube_usercode.PROJECT_ROOT = None
            cube_usercode.CORE_SRC = None
            cube_usercode.CORE_INC = None
            cube_usercode.BACKUP_DIR = None

        self.assertNotEqual(rc, 0, "复制失败必须非零返回")
        self.assertGreaterEqual(state["n"], 2,
                                "夹具失效: copy2 未被调用两次, 未注入到失败")
        old_main = os.path.join(self.ws, ".cube_backup", "Core", "Src", "main.c")
        old_gpio = os.path.join(self.ws, ".cube_backup", "Core", "Src", "gpio.c")
        self.assertTrue(os.path.isfile(old_main), "旧备份 main.c 已丢失")
        self.assertTrue(os.path.isfile(old_gpio), "旧备份 gpio.c 已丢失")
        self.assertIn(b"main_old", read_bytes(old_main),
                      "旧备份 main.c 内容已被破坏")
        self.assertIn(b"gpio_old", read_bytes(old_gpio),
                      "旧备份 gpio.c 内容已被破坏")


class LoopCodeBraceTests(unittest.TestCase):
    """F-178 P1 (L-6): `_extract_loop_code` 的花括号计数必须只在**代码态**进行。

    旧实现逐字符裸数 `{`/`}` —— 被 `printf("}")`、`'{'`、含括号的注释欺骗,
    while(1) 体被提前截断或过度延展, 用户代码静默丢尾/串味。
    """

    def _body(self, loop_lines):
        content = ("int main(void)\n{\n"
                   "    while (1) {\n"
                   + "".join("        %s\n" % ln for ln in loop_lines)
                   + "    }\n"
                     "    return 0;\n"
                     "}\n")
        return cube_usercode._extract_loop_code(content)

    def test_brace_in_string_literal_does_not_truncate(self):
        body = self._body(['printf("}");', "tick++;", "if (tick > 3) break;"])
        self.assertIn('printf("}");', body)
        self.assertIn("tick++;", body)
        self.assertIn("if (tick > 3) break;", body)

    def test_brace_in_char_literal_does_not_truncate(self):
        body = self._body(["if (c == '}') { flag = 1; }", "tick++;"])
        self.assertIn("tick++;", body)

    def test_brace_in_comment_does_not_truncate(self):
        body = self._body(["/* } 假的闭合 */", "tick++;"])
        self.assertIn("tick++;", body)

    def test_escaped_quote_in_string_does_not_confuse_scanner(self):
        body = self._body(['printf("a\\"}" );', "tick++;"])
        self.assertIn("tick++;", body)


class ConflictAccountingTests(unittest.TestCase):
    """F-178 P1 (L-6): 旧 main.c 有 USER CODE 块而新文件无标记时, 必须**如实
    落 conflict** —— 旧版 `pass # fall through to conflict` 从不记录, 该文件
    既不进 restored 也不进 conflicts, 三计数全部蒸发, 用户只看到
    "[OK] 恢复完成" 便以为没丢代码。
    """

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_markerless_new_file_is_reported_as_conflict(self):
        mk_project(
            self.ws,
            # 新文件完全没有 USER CODE 标记 (CubeMX 模板大变)
            {"Core/Src/main.c": '#include "main.h"\n\nint main(void)\n{\n'
                                '  while (1) { }\n}\n'},
            {"Core/Src/main.c": main_c("  int precious = 42;")})

        r = cli("restore", self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("无 USER CODE 标记", r.stdout,
                      f"conflict 未被上报 (三计数蒸发): {r.stdout}")
        self.assertIn("main.c", r.stdout)
        self.assertIn("恢复完成: 0 个文件已更新", r.stdout,
                      f"计数口径不诚实: {r.stdout}")
        # 新文件一个字节都不该被动
        self.assertNotIn(b"precious", read_bytes(
            os.path.join(self.ws, "Core", "Src", "main.c")))


if __name__ == "__main__":
    unittest.main()
