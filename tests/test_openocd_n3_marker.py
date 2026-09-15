r"""F-155 (总工单 v2 T8/N-3) openocd 构造性标记法回归钉。

契约:
  1. flash/erase 命令串尾追加 `echo MARK_ACTION_DONE` — 只有脚本真跑到底
     标记才在场 (构造性证据, 不靠措辞嗅探);
  2. 成功 = exit 0 **且**标记在场; exit 0 但标记缺席 = action_incomplete
     (OpenOCD 提前退出, 拒绝按成功入账);
  3. 失败措辞行 (Error:/Warn: 文案) → details.backend_warnings 留痕,
     **不改判** — 克隆适配器的吓人文案与真实失败解耦;
  4. probe 只读动作不上标记 (rc!=0 + jtag_tap/core 实证的既有豁免保留)。
三条 mock 钉 (1/2/3) + probe 反向钉, 全程 mock subprocess。
"""
import subprocess
import sys
import os
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_run  # noqa: E402

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _run_action(action, *, stdout="", stderr="", returncode=0, **kw):
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=[], returncode=returncode,
                                           stdout=stdout, stderr=stderr)

    with mock.patch.object(openocd_run.subprocess, "run", _fake_run):
        rs = openocd_run.run_openocd(
            "openocd-fake", action, board="st-link",
            interface="interface/stlink.cfg", target="target/stm32f1x.cfg",
            file="fw.hex" if action == "flash" else "", **kw)
    return rs, captured["cmd"]


_FLASH_OK_STDERR = (
    "Open On-Chip Debugger\n> flash write_image erase fw.hex\n"
    "wrote 4096 bytes from file fw.hex in 0.1s (32 KiB/s)\n"
    "verified 4096 bytes\n")


class MarkerContractTests(unittest.TestCase):
    """验收钉 1: 标记在串尾 + 措辞行留痕不改判"""

    def test_success_requires_exit0_and_marker(self):
        stderr = _FLASH_OK_STDERR + f"{openocd_run.ACTION_DONE_MARKER}\n"
        rs, cmd = _run_action("flash", stderr=stderr, returncode=0)
        self.assertEqual(rs["status"], "ok", rs)
        # F-172: 标记必须在 exit/shutdown 门闩之前 — OpenOCD 收到 exit 即
        # 终止脚本, 后置 echo 永不执行 (旧序"exit, ..., echo MARK"真机必假红)
        self.assertEqual(cmd[-1], "exit")
        self.assertEqual(cmd[-3], "echo MARK_ACTION_DONE")

    def test_marker_unreachable_after_exit_gate(self):
        # F-172 结构性钉: 命令串里 exit/shutdown 之后不得再有动作命令
        for action in ("flash", "erase"):
            with self.subTest(action=action):
                _rs, cmd = _run_action(action, stderr="wrote 4096 bytes\n",
                                       returncode=0)
                gates = [i for i, c in enumerate(cmd)
                         if c in ("exit", "shutdown")]
                self.assertTrue(gates, f"{action} 串必须含退出门闩: {cmd}")
                last_gate = max(gates)
                self.assertEqual(cmd[last_gate:], ["exit"],
                                 f"{action}: 门闩后仍有动作 (标记不可达): {cmd}")

    def test_erase_marker_order(self):
        # F-172: erase 自带尾部 shutdown 同样须被摘除重排
        stderr = " erased\n" + f"{openocd_run.ACTION_DONE_MARKER}\n"
        rs, cmd = _run_action("erase", stderr=stderr, returncode=0)
        self.assertEqual(rs["status"], "ok", rs)
        self.assertNotIn("shutdown", cmd)
        self.assertEqual(cmd[-1], "exit")

    def test_warning_wording_does_not_flip_verdict(self):
        # 克隆适配器吓人文案在场, 但 rc=0 + 标记在场 → 仍 ok,
        # 文案进 backend_warnings 留痕
        stderr = (_FLASH_OK_STDERR
                  + "Error: bogus adapter hiccup (non-fatal)\n"
                  + f"{openocd_run.ACTION_DONE_MARKER}\n")
        rs, _cmd = _run_action("flash", stderr=stderr, returncode=0)
        self.assertEqual(rs["status"], "ok", rs)
        warnings = rs["details"].get("backend_warnings", [])
        self.assertTrue(any("bogus adapter hiccup" in w for w in warnings),
                        f"措辞行必须留痕: {warnings}")

    def test_exit0_without_marker_is_action_incomplete(self):
        # 验收钉 2: exit 0 但脚本没跑完 (标记缺席) → 不许按成功入账
        rs, _cmd = _run_action("flash", stderr=_FLASH_OK_STDERR, returncode=0)
        self.assertEqual(rs["status"], "error")
        self.assertEqual(rs["error"]["code"], "action_incomplete")

    def test_nonzero_exit_still_command_failed(self):
        # 验收钉 3 的另一半: rc!=0 → 既有 command_failed 契约不变
        # (ERROR_PATTERNS 命中时走 pattern code, 此处用未编目文案)
        stderr = _FLASH_OK_STDERR + "Error: something unclassified happened\n"
        rs, _cmd = _run_action("flash", stderr=stderr, returncode=1)
        self.assertEqual(rs["status"], "error")
        self.assertEqual(rs["error"]["code"], "command_failed")

    def test_probe_has_no_marker_and_keeps_exemption(self):
        # 反向钉: probe 只读动作不上标记 (rc!=0 + tap 实证豁免保留)
        stdout = 'jtag_tap "stm32f1x.cpu" tap/ipc enabled\n'
        rs, cmd = _run_action("probe", stdout=stdout, returncode=1)
        self.assertNotIn("echo MARK_ACTION_DONE", cmd)
        self.assertNotEqual(rs.get("error", {}).get("code"),
                            "action_incomplete")


class N3SharedContractTests(unittest.TestCase):
    """F-163 (L-4): 标记常量与缺席判定抽为公开共享件 —
    openocd_run 自身与 verify.step_flash 消费同一判据，无双实现漂移。"""

    def test_public_cmd_alias_same_value(self):
        self.assertEqual(openocd_run.ACTION_DONE_CMD, openocd_run._ACTION_DONE_CMD)
        self.assertEqual(openocd_run.ACTION_DONE_CMD,
                         f"echo {openocd_run.ACTION_DONE_MARKER}")

    def test_marker_present_true_only_when_marker_in_output(self):
        self.assertTrue(openocd_run.marker_present(
            "Info : Programming... / Mark action done: MARK_ACTION_DONE"))
        self.assertFalse(openocd_run.marker_present(
            "Info : Programming started but OpenOCD exited early"))

    def test_marker_present_empty_output_false(self):
        self.assertFalse(openocd_run.marker_present(""))


if __name__ == "__main__":
    unittest.main()
