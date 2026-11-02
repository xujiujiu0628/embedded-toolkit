r"""F-240: cube_usercode 的初始化/循环/头文件提取器补测。

## 覆盖对象

`scripts/cube_usercode.py` 此前 74% 覆盖（2026-11-02 实测）：`_extract_init_code`、
`_extract_loop_code` 的常规路径与 `_extract_header_code`（自定义 include /
semihost 声明 / fputc 宏）未执行。花括号/字符串态扫描的边界已由
`test_cube_usercode.py` 的 LoopCodeBraceTests 覆盖，本文件只补提取器主路径。

## 夹具

纯字符串输入，不落盘。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import cube_usercode  # noqa: E402


class ExtractInitCodeTests(unittest.TestCase):
    def test_code_between_last_mx_init_and_while(self):
        content = (
            "int main(void) {\n"
            "  MX_GPIO_Init();\n"
            "  MX_I2C1_Init();\n"
            "  my_setup();\n"
            "  while (1) {\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(cube_usercode._extract_init_code(content), "my_setup();")

    def test_no_mx_init_returns_empty(self):
        self.assertEqual(cube_usercode._extract_init_code("int main(void) {}\n"), "")

    def test_no_while_returns_empty(self):
        content = "int main(void) {\n  MX_GPIO_Init();\n}\n"
        self.assertEqual(cube_usercode._extract_init_code(content), "")


class ExtractLoopCodeTests(unittest.TestCase):
    def test_loop_body_extracted_and_dedented(self):
        content = (
            "int main(void) {\n"
            "  while (1) {\n"
            "    toggle();\n"
            "    delay();\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(cube_usercode._extract_loop_code(content),
                         "toggle();\n    delay();")

    def test_no_loop_returns_empty(self):
        self.assertEqual(cube_usercode._extract_loop_code("int main(void) {}\n"), "")


class ExtractHeaderCodeTests(unittest.TestCase):
    def test_custom_includes_and_semihost_kept(self):
        content = (
            '#include "main.h"\n'
            '#include "extra.h"\n'
            "extern void semihost_init(void);\n"
            "int main(void) {\n"
            "}\n"
        )
        got = cube_usercode._extract_header_code(content)
        self.assertIn('#include "extra.h"', got)
        self.assertIn("extern void semihost_init", got)
        self.assertNotIn('#include "main.h"', got)

    def test_fputc_macro_kept(self):
        content = (
            "#define DHCSR_ADDR 0xE000EDF0\n"
            "int fputc(int c, FILE *f) { return c; }\n"
            "int main(void) {}\n"
        )
        got = cube_usercode._extract_header_code(content)
        self.assertIn("#define DHCSR_ADDR", got)
        self.assertIn("int fputc", got)

    def test_no_main_returns_empty(self):
        self.assertEqual(cube_usercode._extract_header_code('#include "x.h"\n'), "")


class DedentTests(unittest.TestCase):
    def test_common_indent_removed(self):
        self.assertEqual(cube_usercode._dedent("    a\n    b\n"), "a\nb\n")

    def test_empty_returns_empty(self):
        self.assertEqual(cube_usercode._dedent(""), "")


if __name__ == "__main__":
    unittest.main()
