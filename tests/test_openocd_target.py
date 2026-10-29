"""F-235: openocd 按 toolchain 分流 exe 与 cfg 列表; 探针跟随 cfg。"""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_runtime  # noqa: E402
import runtime_common  # noqa: E402

MACHINE = {
    "openocd_exe": "/xpack/openocd",
    "wch_openocd_exe": "/wch/openocd",
    "wch_openocd_cfg": "/wch/wch-riscv.cfg",
}


class ResolveTargetTests(unittest.TestCase):
    def test_arm_returns_pair(self):
        with mock.patch.object(runtime_common, "resolve_openocd_cfg",
                               return_value={"interface": "if.cfg",
                                             "target": "tgt.cfg",
                                             "interface_source": "default"}):
            got = runtime_common.resolve_openocd_target(MACHINE, gcc_cfg={})
        self.assertEqual(got["exe"], "/xpack/openocd")
        self.assertEqual(got["cfg_list"], ["if.cfg", "tgt.cfg"])
        self.assertEqual(got["source"], "arm")

    def test_wch_returns_single_file(self):
        got = runtime_common.resolve_openocd_target(
            MACHINE, gcc_cfg={"toolchain": "wch"})
        self.assertEqual(got["exe"], "/wch/openocd")
        self.assertEqual(got["cfg_list"], ["/wch/wch-riscv.cfg"])
        self.assertEqual(got["source"], "wch")

    def test_wch_missing_exe_names_key(self):
        with self.assertRaises(runtime_common.OpenocdCfgError) as ctx:
            runtime_common.resolve_openocd_target(
                {"wch_openocd_cfg": "/c.cfg"}, gcc_cfg={"toolchain": "wch"})
        self.assertIn("wch_openocd_exe", str(ctx.exception))

    def test_wch_missing_cfg_names_key(self):
        with self.assertRaises(runtime_common.OpenocdCfgError) as ctx:
            runtime_common.resolve_openocd_target(
                {"wch_openocd_exe": "/e"}, gcc_cfg={"toolchain": "wch"})
        self.assertIn("wch_openocd_cfg", str(ctx.exception))

    def _ws_with_config(self, config: dict) -> str:
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        os.makedirs(os.path.join(td, ".workbench"))
        with open(os.path.join(td, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(config, f)
        return td

    def test_workspace_config_selects_wch(self):
        """gcc_cfg 未给时读 workspace 的 gcc 段 (工程侧 toolchain 生效)。"""
        ws = self._ws_with_config({"gcc": {"toolchain": "wch"}})
        got = runtime_common.resolve_openocd_target(MACHINE, workspace=ws)
        self.assertEqual(got["source"], "wch")
        self.assertEqual(got["cfg_list"], ["/wch/wch-riscv.cfg"])

    def test_workspace_openocd_section_reaches_resolver(self):
        """R2: arm 分支把 workspace 透传给 resolve_openocd_cfg —— 工程
        openocd 段必须生效 (若误把整份 config 当 project_config 传入,
        interface/target 会静默丢回默认值, 本钉转红)。"""
        ws = self._ws_with_config(
            {"openocd": {"target_cfg": "target/w.cfg"}})
        got = runtime_common.resolve_openocd_target(MACHINE, workspace=ws)
        self.assertEqual(got["cfg_list"][1], "target/w.cfg")


class SwdProbeCommandTests(unittest.TestCase):
    """判据走内容不变; 变的只是命令里有没有 transport select swd。"""

    def _cmd(self, cfg_list):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0,
                                         stdout="shutdown command invoked",
                                         stderr="")

        # F-184 钦定形态: 模块引用替换 (patch.object(openocd_runtime, "subprocess")),
        # 不穿到全局 subprocess 上打桩 (test_stub_ratchet 零新增)。
        fake_subprocess = types.SimpleNamespace(
            run=fake_run,
            TimeoutExpired=openocd_runtime.subprocess.TimeoutExpired)
        with mock.patch.object(openocd_runtime, "subprocess",
                               fake_subprocess):
            ok, _ = openocd_runtime.swd_probe("/oc", attempts=1,
                                              cfg_list=cfg_list)
        self.assertTrue(ok)   # 判据 (shutdown 行) 不走样
        return captured["cmd"]

    def test_two_cfg_files_select_swd(self):
        cmd = self._cmd(["if.cfg", "tgt.cfg"])
        self.assertIn("transport select swd", cmd)
        self.assertEqual(cmd.count("-f"), 2)

    def test_single_cfg_file_skips_transport(self):
        cmd = self._cmd(["/wch/wch-riscv.cfg"])
        self.assertNotIn("transport select swd", cmd)
        self.assertEqual(cmd.count("-f"), 1)


if __name__ == "__main__":
    unittest.main()
