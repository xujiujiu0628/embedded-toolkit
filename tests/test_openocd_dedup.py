r"""openocd 家族同源符号收敛的特征钉 (F-091, 先钉后拆纪律)。

拆前取证 (2026-09-09): resolve_openocd_params 在 gdb/run/telnet 三份
逐字节相同 (sha1 9bd9af729c), itm 为 +27 行扩展变体; start_openocd_server
在 gdb/itm 两份逐字节相同 (bbe8f0aad8), telnet 多一行 docstring (d28eff49bd)。

本文件钉两件事:
  1. 身份钉: 三个消费方的符号 IS openocd_runtime 的同一对象 (再导出非拷贝);
  2. 行为钉: canonical 实现的优先级语义 (CLI > project_config > state)。
itm 变体按 F-029 裁决**不强行统一**——扩展字段是 ITM 特有需求, 强并会
迫使 runtime 携带 ITM 专属知识 (分层违例)。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import openocd_gdb  # noqa: E402
import openocd_run  # noqa: E402
import openocd_runtime  # noqa: E402
import openocd_telnet  # noqa: E402


class ReExportIdentityTests(unittest.TestCase):
    """身份钉: 消费方符号必须是 runtime 的同一对象 (F-029 再导出纪律)"""

    def test_resolve_params_identity_across_consumers(self):
        for mod in (openocd_gdb, openocd_run, openocd_telnet):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.resolve_openocd_params,
                              openocd_runtime.resolve_openocd_params)

    def test_start_server_identity_across_consumers(self):
        # F-123: itm 本地副本删除后补入钉名单 (工单 P0-7 验收)
        import openocd_itm
        for mod in (openocd_gdb, openocd_telnet, openocd_itm):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.start_openocd_server,
                              openocd_runtime.start_openocd_server)

    def test_startup_trio_identity_across_consumers(self):
        """F-123 (工单 P0-7): build_openocd_cmd / wait / cleanup 收编身份钉。
        itm 的 build_openocd_cmd 是真分叉 (tpiu/trace 扩展, F-029 裁决保留),
        只钉 wait/cleanup; gdb/telnet 三件套全钉。"""
        import openocd_itm
        for mod in (openocd_gdb, openocd_telnet):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.build_openocd_cmd,
                              openocd_runtime.build_openocd_cmd)
                self.assertIs(mod.wait_server_ready,
                              openocd_runtime.wait_server_ready)
                self.assertIs(mod.cleanup if mod is openocd_gdb else mod.cleanup_proc,
                              openocd_runtime.cleanup)
        self.assertIs(openocd_itm.cleanup, openocd_runtime.cleanup)
        self.assertIs(openocd_itm.wait_itm_ready, openocd_runtime.wait_itm_ready)
        self.assertIsNot(openocd_itm.build_openocd_cmd,
                         openocd_runtime.build_openocd_cmd)

    def test_itm_variant_not_unified(self):
        """itm 的扩展变体保留 (F-029 真分叉裁决): 有独立参数但主五参同源"""
        import openocd_itm
        # itm 的 resolve 返回 dict 应包含扩展键
        args = mock.Mock(board=None, interface=None, target=None,
                         adapter_speed=None, transport=None,
                         tpiu_name="x", traceclk=None, pin_freq=None)
        out = openocd_itm.resolve_openocd_params(args, {}, {})
        for key in ("tpiu_name", "traceclk", "pin_freq"):
            self.assertIn(key, out)
        # 主五参仍在 (扩展变体是超集)
        for key in ("board", "interface", "target", "adapter_speed",
                    "transport"):
            self.assertIn(key, out)


    def test_state_lookup_identity_across_consumers(self):
        """F-156 (P2-1): 四入口 last_* 状态映射收编 openocd_runtime 超集"""
        import openocd_itm
        for mod in (openocd_gdb, openocd_run, openocd_telnet, openocd_itm):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod._state_lookup,
                              openocd_runtime.state_lookup)


class ResolveParamsSemanticsTests(unittest.TestCase):
    """行为钉: canonical 实现的三级优先语义"""

    def _args(self, **kw):
        defaults = dict(board=None, interface=None, target=None,
                        adapter_speed=None, transport=None)
        defaults.update(kw)
        return mock.Mock(**defaults)

    def test_cli_wins_over_config_and_state(self):
        out = openocd_runtime.resolve_openocd_params(
            self._args(board="interface/stlink.cfg"),
            {"board": "x.cfg"}, {"board": "y.cfg"})
        self.assertEqual(out["board"], "interface/stlink.cfg")
        self.assertEqual(out["board_source"], "cli")

    def test_config_beats_state(self):
        out = openocd_runtime.resolve_openocd_params(
            self._args(), {"board": "from_config.cfg"},
            {"board": "from_state.cfg"})
        self.assertEqual(out["board"], "from_config.cfg")
        self.assertEqual(out["board_source"], "project_config")

    def test_state_is_final_fallback(self):
        out = openocd_runtime.resolve_openocd_params(
            self._args(), {}, {"board": "from_state.cfg"})
        self.assertEqual(out["board"], "from_state.cfg")
        self.assertEqual(out["board_source"], "state")

    def test_all_missing_returns_none_with_state_source(self):
        out = openocd_runtime.resolve_openocd_params(self._args(), {}, {})
        for key in ("board", "interface", "target", "adapter_speed",
                    "transport"):
            self.assertIsNone(out[key])
            self.assertEqual(out[f"{key}_source"], "state")


if __name__ == "__main__":
    unittest.main()
