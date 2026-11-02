r"""F-237: openocd_gdb_common 的纯解析与进程封装补测。

## 覆盖对象

`scripts/openocd_gdb_common.py` 此前 13% 覆盖（2026-11-02 实测）：GDB 命令
构造、输出解析、子进程封装三层几乎全未执行。本文件只测**不接真探针**的
部分——假 GDB 脚本由临时目录生成，真实 OpenOCD/GDB 不在场也能跑。

## 纪律

断言的是"解析结果该是什么"，不是"跑过就算"：每个样例都钉住字段值，
解析器改坏即红。发现真实缺陷时先写红测试再修（`_parse_threads` 的
未选中线程丢行即本批抓出）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_gdb_common as gc  # noqa: E402


def _write_fake_gdb(tmpdir: str, body: list[str], returncode: int = 0) -> str:
    """生成一个假 GDB：忽略全部参数，按 body 输出后以 returncode 退出。"""
    if os.name == "nt":
        path = os.path.join(tmpdir, "fake_gdb.bat")
        lines = ["@echo off", *body, f"exit /b {returncode}"]
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        path = os.path.join(tmpdir, "fake_gdb.sh")
        lines = ["#!/bin/sh", *body, f"exit {returncode}"]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(path, 0o755)
    return path


class BuildGdbCommandsTests(unittest.TestCase):
    def test_backtrace_halts_before_introspection(self):
        self.assertEqual(
            gc.build_gdb_commands("backtrace"), ["monitor halt", "backtrace"])

    def test_halt_before_false_omits_monitor_halt(self):
        self.assertEqual(
            gc.build_gdb_commands("backtrace", halt_before=False), ["backtrace"])

    def test_continue_resumes_without_halt(self):
        self.assertEqual(gc.build_gdb_commands("continue"), ["monitor resume"])

    def test_break_requires_expr(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("break")

    def test_break_with_expr_lists_breakpoints(self):
        self.assertEqual(
            gc.build_gdb_commands("break", "main"),
            ["monitor halt", "break main", "info breakpoints"],
        )

    def test_frame_requires_expr(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("frame")

    def test_print_requires_expr(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("print")

    def test_watch_requires_expr(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("watch")

    def test_until_without_expr(self):
        self.assertEqual(gc.build_gdb_commands("until"), ["monitor halt", "until"])

    def test_until_with_expr(self):
        self.assertEqual(
            gc.build_gdb_commands("until", "main.c:10"),
            ["monitor halt", "until main.c:10"],
        )

    def test_disassemble_with_and_without_expr(self):
        self.assertEqual(
            gc.build_gdb_commands("disassemble", "main"),
            ["monitor halt", "disassemble main"],
        )
        self.assertEqual(
            gc.build_gdb_commands("disassemble"),
            ["monitor halt", "disassemble"],
        )

    def test_threads_requests_all_backtraces(self):
        self.assertEqual(
            gc.build_gdb_commands("threads"),
            ["monitor halt", "info threads", "thread apply all backtrace 1"],
        )

    def test_crash_report_collects_six_commands(self):
        commands = gc.build_gdb_commands("crash-report")
        self.assertEqual(commands[0], "monitor halt")
        self.assertIn("backtrace full", commands)
        self.assertIn("info registers", commands)
        self.assertIn("frame 0", commands)
        self.assertIn("info locals", commands)
        self.assertIn("info threads", commands)
        self.assertIn("disassemble /m $pc,$pc+32", commands)

    def test_run_must_be_supplied_by_caller(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("run")

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            gc.build_gdb_commands("bogus")


class RequireActionExprTests(unittest.TestCase):
    def test_empty_expr_raises_with_hint(self):
        with self.assertRaises(ValueError) as ctx:
            gc.require_action_expr("print", "", "--expr")
        self.assertIn("--expr", str(ctx.exception))

    def test_non_empty_expr_returned_unchanged(self):
        self.assertEqual(gc.require_action_expr("print", "x", "--expr"), "x")


class ParseFramesTests(unittest.TestCase):
    def test_parses_index_function_args_and_location(self):
        stdout = (
            "#0  main () at main.c:10\n"
            "#1  0x08000123 in foo (a=1, b=2) at foo.c:5\n"
        )
        frames = gc._parse_frames(stdout)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], {"frame": 0, "function": "main", "location": "main.c:10"})
        self.assertEqual(frames[1]["frame"], 1)
        self.assertEqual(frames[1]["address"], "0x08000123")
        self.assertEqual(frames[1]["function"], "foo")
        self.assertEqual(frames[1]["args"], "a=1, b=2")
        self.assertEqual(frames[1]["location"], "foo.c:5")

    def test_missing_function_becomes_unknown(self):
        frames = gc._parse_frames("#2  0x08000000 in ?? ()\n")
        self.assertEqual(frames[0]["function"], "??")

    def test_non_frame_lines_ignored(self):
        self.assertEqual(gc._parse_frames("Breakpoint 1 at 0x8000000\n"), [])


class ParseVariablesTests(unittest.TestCase):
    def test_parses_plain_and_member_names(self):
        variables = gc._parse_variables(
            "x = 5\n"
            "p->field = 0x10\n"
            "arr[3] = 7\n"
            "info locals\n"
        )
        self.assertEqual(variables, {"x": "5", "p->field": "0x10", "arr[3]": "7"})


class ParseRegistersTests(unittest.TestCase):
    def test_parses_register_names_and_hex_values(self):
        registers = gc._parse_registers(
            "r0             0x00000001      1\n"
            "pc             0x08000100      <main>\n"
            "noise line\n"
        )
        self.assertEqual(registers, {"r0": "0x00000001", "pc": "0x08000100"})


class ParseThreadsTests(unittest.TestCase):
    def test_parses_selected_and_unselected_threads(self):
        """未选中线程行以两个空格开头，strip() 会吃掉选择标记——本测试钉住。"""
        threads = gc._parse_threads(
            "* 1 Thread 0x20000100 (main) at main.c:10\n"
            "  2 Thread 0x20000200 (idle) at port.c:1\n"
        )
        self.assertEqual(len(threads), 2)
        self.assertEqual(threads[0], {
            "selected": True, "id": 1,
            "description": "0x20000100 (main) at main.c:10",
        })
        self.assertEqual(threads[1]["selected"], False)
        self.assertEqual(threads[1]["id"], 2)


class ParseDisassemblyTests(unittest.TestCase):
    def test_parses_selected_line_and_symbol(self):
        items = gc._parse_disassembly(
            "=> 0x08000000 <main>: mov r0, r1\n"
            "   0x08000002 <main+2>: bx lr\n"
        )
        self.assertEqual(items[0], {
            "address": "0x08000000", "instruction": "mov r0, r1",
            "selected": "true", "symbol": "main",
        })
        self.assertNotIn("selected", items[1])
        self.assertEqual(items[1]["instruction"], "bx lr")


class ExtractSourceLocationTests(unittest.TestCase):
    def test_prefers_frame_location(self):
        frames = [{"frame": 0, "function": "main", "location": "main.c:10"}]
        self.assertEqual(gc._extract_source_location("", frames), "main.c:10")

    def test_falls_back_to_stdout_regex(self):
        self.assertEqual(
            gc._extract_source_location("Program stopped at main.c:42.", []),
            "main.c:42",
        )

    def test_returns_empty_when_absent(self):
        self.assertEqual(gc._extract_source_location("nothing here", []), "")


class ParseSelectedFrameTests(unittest.TestCase):
    def test_parses_frame_and_location(self):
        self.assertEqual(
            gc._parse_selected_frame("#1  foo () at foo.c:5\n"),
            {"frame": 1, "location": "foo.c:5"},
        )

    def test_returns_empty_without_frame(self):
        self.assertEqual(gc._parse_selected_frame("no frame"), {})


class ParseGdbOutputTests(unittest.TestCase):
    def test_aggregates_every_section(self):
        stdout = (
            "#0  main () at main.c:10\n"
            "x = 5\n"
            "r0             0x00000001      1\n"
            "* 1 Thread 0x20000100 (main) at main.c:10\n"
            "   0x08000002 <main+2>: bx lr\n"
        )
        parsed = gc.parse_gdb_output(stdout, "backtrace")
        self.assertEqual(parsed["output"], stdout)
        self.assertEqual(parsed["frames"][0]["function"], "main")
        self.assertEqual(parsed["variables"], {"x": "5"})
        self.assertEqual(parsed["registers"], {"r0": "0x00000001"})
        self.assertEqual(parsed["threads"][0]["id"], 1)
        self.assertEqual(parsed["disassembly"][0]["address"], "0x08000002")
        self.assertEqual(parsed["selected_frame"], {"frame": 0, "location": "main.c:10"})
        self.assertEqual(parsed["source_location"], "main.c:10")

    def test_print_action_extracts_value(self):
        parsed = gc.parse_gdb_output("$1 = 42\n", "print")
        self.assertEqual(parsed["value"], "42")

    def test_empty_output_keeps_only_raw_text(self):
        self.assertEqual(gc.parse_gdb_output("", "backtrace"), {"output": ""})

    def test_selected_frame_falls_back_to_first_frame(self):
        parsed = gc.parse_gdb_output("#0  main () at main.c:10\n", "backtrace")
        self.assertEqual(parsed["selected_frame"]["frame"], 0)


class RunGdbCommandsTests(unittest.TestCase):
    def test_success_reports_stdout_and_returncode(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = _write_fake_gdb(tmp, ["echo GDBFAKE-OK"], returncode=0)
            result = gc.run_gdb_commands(exe, "", "localhost:3333", ["backtrace"], timeout=30)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("GDBFAKE-OK", result["stdout"])

    def test_nonzero_exit_reports_error_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = _write_fake_gdb(tmp, ["echo GDBFAKE-FAIL"], returncode=3)
            result = gc.run_gdb_commands(exe, "fw.elf", "localhost:3333", [], timeout=30)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["returncode"], 3)
        self.assertIn("GDBFAKE-FAIL", result["stdout"])

    def test_timeout_is_reported_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            if os.name == "nt":
                exe = _write_fake_gdb(tmp, ["ping -n 3 127.0.0.1 >nul"], returncode=0)
            else:
                exe = _write_fake_gdb(tmp, ["sleep 2"], returncode=0)
            result = gc.run_gdb_commands(exe, "", "localhost:3333", [], timeout=0.2)
        self.assertEqual(result["status"], "error")
        self.assertIn("超时", result["error"])


if __name__ == "__main__":
    unittest.main()
