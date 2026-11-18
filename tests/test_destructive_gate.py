"""破坏性动作闸（openocd_run）：整片擦除与 raw 解锁命令默认拒绝。

## 为什么要有

`physical_checklist` 只挂在 verify.py 的 Step 0（`verify.py:933`）。单独调用
`openocd_run.py erase --mode mass` 时不经过任何清单/确认，等于给"闸站在硬件
前面"这条纪律开了一个侧门。本组测试把三个口子钉死：

1. `erase --mode mass` 缺 `--allow-mass-erase` → 拒绝；
2. `raw` 命令串含 mass_erase/unlock/lock/option → 缺 `--allow-raw` 即拒绝；
3. 无害 raw（如 mdw）不受影响，免得把闸做成"什么都拦"。

拒绝必须发生在碰探针之前：CLI 级用例断言进程退出码为 1 且没有任何
OpenOCD spawn（这两条一起才能证明"目标一个字节没动"）。
"""
import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_run  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _args(**over):
    base = dict(action="probe", mode="run", allow_mass_erase=False,
                allow_raw=False, command=None)
    base.update(over)
    return SimpleNamespace(**base)


class DestructiveRefusalTests(unittest.TestCase):
    def test_mass_erase_blocked_by_default(self):
        err = openocd_run.destructive_refusal(_args(action="erase", mode="mass"))
        self.assertIsNotNone(err)
        self.assertEqual(err["code"], "permission_denied")
        self.assertIn("--allow-mass-erase", err["message"])

    def test_mass_erase_allowed_with_flag(self):
        self.assertIsNone(openocd_run.destructive_refusal(
            _args(action="erase", mode="mass", allow_mass_erase=True)))

    def test_sector_erase_not_gated(self):
        self.assertIsNone(openocd_run.destructive_refusal(
            _args(action="erase", mode="sector")))

    def test_raw_destructive_command_blocked(self):
        for cmd in (["stm32f1x", "mass_erase", "0"],
                    ["stm32f1x", "unlock", "0"],
                    ["stm32f1x", "lock", "0"],
                    ["stm32f1x", "option_write", "0", "0"],
                    ["stm32f1x", "ob_erase", "0"]):
            with self.subTest(cmd=cmd):
                err = openocd_run.destructive_refusal(
                    _args(action="raw", command=cmd))
                self.assertIsNotNone(err, f"{cmd} 应被拒绝")
                self.assertEqual(err["code"], "permission_denied")

    def test_raw_harmless_command_allowed(self):
        self.assertIsNone(openocd_run.destructive_refusal(
            _args(action="raw", command=["mdw", "0x20000000", "4"])))

    def test_raw_does_not_false_positive_on_lock_substring(self):
        # "block" 以 "lock" 结尾: 子串匹配会误伤, 词匹配不会
        self.assertIsNone(openocd_run.destructive_refusal(
            _args(action="raw", command=["mdb", "0x20000000", "block"])))

    def test_raw_destructive_allowed_with_flag(self):
        self.assertIsNone(openocd_run.destructive_refusal(
            _args(action="raw", command=["stm32f1x", "mass_erase", "0"],
                  allow_raw=True)))


class CliGateTests(unittest.TestCase):
    """端到端：拒绝发生在解析后、碰探针前。"""

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "openocd_run.py"), *extra],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            cwd=os.path.dirname(SCRIPTS))

    def test_cli_mass_erase_refused_before_probe(self):
        proc = self._run("erase", "--mode", "mass", "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "permission_denied")
        # 没有探针错误字样 = 没起 OpenOCD
        self.assertNotIn("openocd", proc.stderr.lower())

    def test_cli_raw_refused(self):
        proc = self._run("raw", "--command", "stm32f1x", "unlock", "0", "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"]["code"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
