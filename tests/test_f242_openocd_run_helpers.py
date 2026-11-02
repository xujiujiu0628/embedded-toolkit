r"""F-242: openocd_run 的命令构造与输出解析补测。

## 覆盖对象

`scripts/openocd_run.py` 此前 79% 覆盖（2026-11-02 实测）：`build_action_commands`
的 flash/erase/reset/raw 全部分支、`infer_mass_erase_command` 的芯片映射，
以及 `parse_output` 的 error/probe/flash/erase/flash-banks/adapter-info 解析
未执行。

## 夹具

纯字符串输入，不启动 OpenOCD。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_run  # noqa: E402


class InferMassEraseTests(unittest.TestCase):
    def test_known_families(self):
        self.assertEqual(openocd_run.infer_mass_erase_command("stm32f1x.cfg", ""),
                         "stm32f1x mass_erase 0")
        self.assertEqual(openocd_run.infer_mass_erase_command("", "stm32f4.cfg"),
                         "stm32f4x mass_erase 0")
        self.assertEqual(openocd_run.infer_mass_erase_command("gd32f1.cfg", ""),
                         "stm32f1x mass_erase 0")

    def test_unknown_returns_empty(self):
        self.assertEqual(openocd_run.infer_mass_erase_command("nrf52.cfg", ""), "")


class BuildActionTests(unittest.TestCase):
    def test_simple_actions(self):
        self.assertEqual(openocd_run.build_action_commands("probe"),
                         (["init", "targets", "shutdown"], None))
        self.assertEqual(openocd_run.build_action_commands("targets"),
                         (["init", "targets", "shutdown"], None))
        self.assertEqual(openocd_run.build_action_commands("flash-banks"),
                         (["init", "flash banks", "shutdown"], None))
        self.assertEqual(openocd_run.build_action_commands("adapter-info"),
                         (["adapter name", "transport list", "adapter speed", "shutdown"], None))

    def test_flash_hex_and_bin(self):
        cmds, err = openocd_run.build_action_commands("flash", file="fw.hex")
        self.assertIsNone(err)
        self.assertTrue(cmds[1].startswith("program {"))
        self.assertTrue(cmds[1].endswith("verify reset"))
        cmds, _ = openocd_run.build_action_commands("flash", file="fw.bin", address="0x08000000")
        self.assertTrue(cmds[1].endswith("verify reset 0x08000000"))

    def test_erase_mass_sector_and_auto(self):
        mass, _ = openocd_run.build_action_commands(
            "erase", target="stm32f1x.cfg", erase_mode="mass")
        self.assertIn("stm32f1x mass_erase 0", mass)
        sector, _ = openocd_run.build_action_commands(
            "erase", target="stm32f1x.cfg", erase_mode="sector", bank="1")
        self.assertIn("flash erase_sector 1 0 last", sector)
        auto, _ = openocd_run.build_action_commands(
            "erase", target="unknown.cfg", erase_mode="auto")
        self.assertIn("flash erase_sector 0 0 last", auto)

    def test_reset_modes(self):
        self.assertIn("reset run", openocd_run.build_action_commands("reset")[0])
        self.assertIn("reset halt",
                      openocd_run.build_action_commands("reset", reset_mode="halt")[0])
        self.assertIn("reset init",
                      openocd_run.build_action_commands("reset", reset_mode="init")[0])
        self.assertIn("reset init", openocd_run.build_action_commands("reset-init")[0])

    def test_raw_and_unknown(self):
        cmds, err = openocd_run.build_action_commands("raw", raw_commands=["reset", "halt"])
        self.assertEqual(cmds, ["reset", "halt", "shutdown"])
        self.assertIsNone(err)
        cmds, err = openocd_run.build_action_commands("bogus")
        self.assertEqual(cmds, [])
        self.assertEqual(err, "unknown_action")


class ParseOutputTests(unittest.TestCase):
    def test_error_pattern_wins(self):
        out = openocd_run.parse_output("Error: open failed\nInfo: other", "probe")
        self.assertEqual(out["error_code"], "adapter_open_failed")
        self.assertIn("raw", out)

    def test_probe_core_and_tap(self):
        text = ("Info : stm32f1x.cm3\n"
                "Info : JTAG tap: stm32f1x.cpu tap/device found\n")
        out = openocd_run.parse_output(text, "probe")
        self.assertEqual(out["core"], "stm32f1x.cm3")
        self.assertEqual(out["jtag_tap"], "stm32f1x.cpu")

    def test_flash_metrics(self):
        text = ("wrote 1024 bytes from file fw.hex in 0.500000s (2.000000 KiB/s)\n"
                "** Verified OK **\n"
                "** Programming Finished **\n")
        out = openocd_run.parse_output(text, "flash")
        self.assertEqual(out["bytes_written"], 1024)
        self.assertEqual(out["elapsed_s"], 0.5)
        self.assertEqual(out["speed_kbps"], 2.0)
        self.assertTrue(out["verified"])
        self.assertTrue(out["programmed"])

    def test_erase_sector_and_mass(self):
        sector = openocd_run.parse_output(
            "erased sectors 0 through 3 on flash bank 0 in 0.1s", "erase")
        self.assertTrue(sector["erased"])
        self.assertEqual(sector["mode"], "sector")
        self.assertEqual(sector["last_sector"], 3)
        mass = openocd_run.parse_output("mass erase complete", "erase")
        self.assertEqual(mass["mode"], "mass")

    def test_flash_banks_and_adapter(self):
        banks = openocd_run.parse_output("flash bank 0 stm32f1x\nother", "flash-banks")
        self.assertEqual(banks["flash_banks"], ["flash bank 0 stm32f1x"])
        adapter = openocd_run.parse_output(
            "adapter name: stlink\nTransport swd available", "adapter-info")
        self.assertEqual(adapter["adapter_name"], "stlink")
        self.assertIn("Transport swd available", adapter["transport_info"])


if __name__ == "__main__":
    unittest.main()
