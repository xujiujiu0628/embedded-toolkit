r"""openocd_telnet 失败语义检查 + 烧录判据收紧的回归钉 (F-090, WB-20260909-04)。

背景 (审计 WB-B2 / P1-1 / P1-2): openocd_telnet 的 halt/reg/read-mem 三个
action 从不检查命令错误（halt 的 "halted": True 硬编码; reg 全空仍 ok;
read-mem 非法地址返回"成功+空 memory"），而 write-mem/bp/rbp 都查了——
属漏查非设计。verify.run_cmd 与 openocd_run 的烧录成功判据是 fail-open
（非零退出码 + stdout 含 "verified" 文本 → ok）。

本文件全部用假 Telnet 连接/假 proc 复现, 不碰真机。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_telnet  # noqa: E402


class _FakeTelnet:
    """按脚本逐次返回 send() 结果的最小假连接"""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)
        return self.script.pop(0) if self.script else ""


class _Args:
    def __init__(self, **kw):
        self.action = kw.get("action", "halt")
        self.width = kw.get("width", "32")
        self.address = kw.get("address", "0x20000000")
        self.length = kw.get("length", 4)
        self.value = kw.get("value", "0x0")
        self.bp_length = kw.get("bp_length", 2)


class HaltFailureSemanticsTests(unittest.TestCase):
    """F-090-A: halt 链路的失败语义"""

    def test_halt_error_response_returns_error_not_ok(self):
        """halt 命令报错 → status=error (旧版恒 ok + halted:True)"""
        telnet = _FakeTelnet([
            "Error: target not halted",   # halt 响应
            "", "", "",                    # reg pc/xpsr/msp
        ])
        out = openocd_telnet.execute_action(telnet, _Args(action="halt"))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "halt_failed")

    def test_halt_reg_query_failure_returns_error(self):
        """halt 后 reg 查询报错 → error (reg 链路是 halt 确认手段)"""
        telnet = _FakeTelnet([
            "halted.",                     # halt 响应
            "Error: target not halted",    # reg pc 失败
            "", "",
        ])
        out = openocd_telnet.execute_action(telnet, _Args(action="halt"))
        self.assertEqual(out["status"], "error")

    def test_halt_success_keeps_ok_and_halted_true(self):
        """正常 halt + reg pc 有值 → ok, halted=True (正向不回归)"""
        telnet = _FakeTelnet([
            "target halted due to debug-request, current mode: Thread",
            "pc (/32): 0x080001ce",
            "xpsr (/32): 0x01000000",
            "msp (/32): 0x20005000",
        ])
        out = openocd_telnet.execute_action(telnet, _Args(action="halt"))
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["details"]["halted"])
        self.assertIn("080001ce", out["summary"])


class RegFailureSemanticsTests(unittest.TestCase):
    """F-090-A: reg 动作的失败语义"""

    def test_all_regs_empty_returns_error_not_ok(self):
        """全部寄存器读空 → error (旧版 '读取到 0 个寄存器' 仍 ok)"""
        telnet = _FakeTelnet([""] * 50)   # halt + 23 个 reg 全空
        out = openocd_telnet.execute_action(telnet, _Args(action="reg"))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "reg_read_failed")

    def test_partial_reg_failure_still_ok_but_reported(self):
        """部分失败 → 仍 ok 但 summary/details 如实带 errors (不谎报全量)"""
        # 响应格式须与 parse_reg_single 的真实格式一致: "r0 (/32): 0x0"
        script = ["halted."] + \
                 ["Error: read failed" if n == "r5"
                  else f"{n} (/32): 0x0"
                  for n in ["r0", "r1", "r2", "r3", "r4", "r5"]]
        telnet = _FakeTelnet(script)
        out = openocd_telnet.execute_action(telnet, _Args(action="reg"))
        self.assertEqual(out["status"], "ok")
        self.assertIn("读取失败", out["summary"])
        self.assertTrue(out["details"]["errors"])


class ReadMemFailureSemanticsTests(unittest.TestCase):
    """F-090-A: read-mem 动作的失败语义"""

    def test_invalid_address_error_response_returns_error(self):
        """非法地址 (OpenOCD 报错) → error (旧版返回成功+空 memory)"""
        telnet = _FakeTelnet(["Error: invalid address"])
        out = openocd_telnet.execute_action(
            telnet, _Args(action="read-mem", address="0xDEADBEEF"))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "read_failed")

    def test_empty_response_returns_error_not_ok(self):
        """无数据返回 (空响应) → error, 不产出假成功"""
        telnet = _FakeTelnet([""])
        out = openocd_telnet.execute_action(telnet, _Args(action="read-mem"))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "read_empty")

    def test_valid_memory_read_still_ok(self):
        """正常读取 → ok + memory 非空 (正向不回归)"""
        telnet = _FakeTelnet([
            "0x20000000: 0x12345678 0x9abcdef0"
        ])
        out = openocd_telnet.execute_action(telnet, _Args(action="read-mem"))
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["details"]["memory"])


class FlashSuccessCriteriaTests(unittest.TestCase):
    """F-090-B: 烧录成功判据只信 returncode"""

    def test_run_cmd_nonzero_with_verified_text_is_error(self):
        """verify.run_cmd: rc!=0 + stdout 含 'not verified' → error
        (旧 fail-open 判据会被 'verified' 子串误中)"""
        import verify
        fake = mock.Mock()
        fake.returncode = 1
        fake.stdout = "flash image ** not verified **"
        fake.stderr = ""
        with mock.patch.object(verify, "WORKSPACE", "."), \
             mock.patch("subprocess.run", return_value=fake):
            out = verify.run_cmd(["fake-openocd"])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["returncode"], 1)

    def test_run_cmd_zero_rc_still_ok(self):
        """rc=0 → ok (正向不回归)"""
        import verify
        fake = mock.Mock()
        fake.returncode = 0
        fake.stdout = "** Verified OK **"
        fake.stderr = ""
        with mock.patch.object(verify, "WORKSPACE", "."), \
             mock.patch("subprocess.run", return_value=fake):
            out = verify.run_cmd(["fake-openocd"])
        self.assertEqual(out["status"], "ok")


if __name__ == "__main__":
    unittest.main()
