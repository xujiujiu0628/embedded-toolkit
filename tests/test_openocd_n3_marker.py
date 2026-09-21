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
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_run  # noqa: E402

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _patch_openocd_subprocess(fake_run):
    """把打桩面收窄到 `openocd_run` 模块内的 subprocess 引用 (F-182 阶段二)。

    旧法 `mock.patch.object(openocd_run.subprocess, "run", …)` 改的是**全局
    `subprocess` 模块** —— 打桩窗口内一切第三方 spawn (如 safe-delete shim 的
    回收站进程) 都被 fake 吞走 (WB-20260920-04 GAP-ENV-1, 5 例假红即此病)。

    本实现改为替换 **`openocd_run` 自己的模块属性** `subprocess`: 只有
    `openocd_run` 内对 `subprocess.run` 的调用被换掉, 全局 `subprocess.run`
    原样可跑。stub 显式带上 `openocd_run` 实际消费的另两个属性 ——
    `TimeoutExpired` (供 `except` 子句求值) 与 `CompletedProcess` (防御性留位)。
    属性集是**收窄**的, 故 fail-closed: 若 `openocd_run` 未来用到别的
    subprocess 属性, 测试会直接 `AttributeError` 报出来, 而不是静默放行。
    """
    stub = types.SimpleNamespace(
        run=fake_run,
        TimeoutExpired=subprocess.TimeoutExpired,
        CompletedProcess=subprocess.CompletedProcess,
    )
    return mock.patch.object(openocd_run, "subprocess", stub)


def _run_action(action, *, stdout="", stderr="", returncode=0, **kw):
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=[], returncode=returncode,
                                           stdout=stdout, stderr=stderr)

    with _patch_openocd_subprocess(_fake_run):
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


class StubIsolationTests(unittest.TestCase):
    """F-182 (WB-20260921-03 / GAP-ENV-1) 打桩卫生自证钉。

    打桩必须只作用在 `openocd_run` 的 subprocess 引用上, **不得**劫持全局
    `subprocess.run` —— 否则打桩窗口内任何第三方 spawn 都被 fake 吞走
    (WB-20260920-04 里 safe-delete shim 的回收站进程被吞 → 5 例假红)。

    本类不依赖 safe-delete shim 是否在场 (那是外部环境事实), 而是**在窗口内
    主动跑一次第三方 `subprocess.run`**, 用真实执行的可观测证据判定劫持。
    """

    def test_patching_does_not_hijack_global_subprocess(self):
        captured = []

        def _fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return subprocess.CompletedProcess(args=[], returncode=0,
                                               stdout="FAKE", stderr="")

        probe_argv = [sys.executable, "-c", "pass"]
        with _patch_openocd_subprocess(_fake_run):
            # 断言 A: 窗口内第三方 subprocess.run 必须真实执行
            probe = subprocess.run(probe_argv, capture_output=True, text=True)

        # A-1 返回码: 真跑 `-c pass` → 0
        with self.subTest(check="A1 rc==0"):
            self.assertEqual(
                probe.returncode, 0,
                f"第三方 subprocess.run 未真实执行: rc={probe.returncode}")
        # A-2 真实性判据: fake 恒返回 returncode=0 + args=[], 单凭 rc 无法
        #     判别真假执行 —— 故以 CompletedProcess.args (真跑时回填入参,
        #     fake 恒为 []) 与 stdout 为判据。
        with self.subTest(check="A2 args 回填"):
            self.assertEqual(
                probe.args, probe_argv,
                f"第三方 subprocess.run 被 fake 吞走 (args={probe.args!r}, "
                f"期望 {probe_argv!r})")
        with self.subTest(check="A2b stdout 真实"):
            self.assertEqual(
                probe.stdout, "",
                f"第三方 subprocess.run 被 fake 吞走 (stdout={probe.stdout!r})")
        # 断言 B: fake 的捕获序列不得含该第三方调用的 argv
        with self.subTest(check="B fake 捕获序列隔离"):
            self.assertNotIn(
                probe_argv, captured,
                f"fake 捕获了非目标调用 (全局劫持证据): {captured}")


if __name__ == "__main__":
    unittest.main()
