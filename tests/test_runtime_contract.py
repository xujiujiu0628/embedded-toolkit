"""F-029 前置特征钉: 三 runtime 的 wire 契约与再导出面在去重全程必须字节不变。

侦察结论 (2026-09-01) + 实施期订正 (2026-09-02 逐行核实):
- serial make_result 入参 success:bool / 输出仍 status 族 —— 签名冻结、输出可并轨,
  但"空 details 省略 + error/details 原样透传(不 compact)"是与 wb/ocd 规范版的真实
  行为差, 适配器落地前以本文件锁定;
- parameter_context / make_timing 同名异物 (入参/返回均不同形), 各钉各位;
- 订正计划分桶表: save_workspace_state / update_state_entry **不是**纯 docstring 差 —
  wb==serial 落盘前跑 _serialize_state_value (绝对路径→workspace 相对 POSIX),
  ocd 原样存。真 wire 语义分叉, 特征钉按现实锁形, 上提时以 hook 参数保行为;
- normalize_path 三形态: wb/ocd 恒 resolve; serial 可带 base 且相对输入不 resolve。
再导出面 (mod.X 可解析) 是 test_writeback_guards RUNTIMES 参数化的前提, 一并钉。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import wb_runtime, openocd_runtime, serial_runtime  # noqa: E402

RUNTIMES = [wb_runtime, openocd_runtime, serial_runtime]
WB_SER = "wb/serial"

# 去重后仍必须可从每个 mod 解析到的公共名 (再导出义务)
REEXPORT_NAMES = [
    "is_missing", "now_iso", "workspace_root", "load_json_file",
    "load_json_strict", "save_json_file", "JSONCorruptError",
    "load_workspace_state", "save_workspace_state",
    "load_workspace_state_for_update", "update_state_entry",
    "output_json", "normalize_path",
    "load_local_config", "save_local_config",
    "load_project_config", "save_project_config",
    "make_result", "make_timing", "parameter_context",
]


def wire_shape(obj):
    """递归取 JSON 结构形状: dict→{key: shape}, list→[shape], 标量→type name"""
    if isinstance(obj, dict):
        return {k: wire_shape(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [wire_shape(x) for x in obj[:1]]
    return type(obj).__name__


class WorkspaceTmpMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ReexportSurfaceTests(unittest.TestCase):
    def test_all_public_names_resolvable(self):
        for mod in RUNTIMES:
            for name in REEXPORT_NAMES:
                with self.subTest(mod=mod.__name__, name=name):
                    self.assertTrue(callable(getattr(mod, name, None))
                                    or isinstance(getattr(mod, name, None), type),
                                    f"{mod.__name__}.{name} 必须保持可解析")


class WireContractTests(unittest.TestCase):
    def test_serial_make_result_input_frozen_output_status_family(self):
        # 实测 (2026-09-01): serial 版入参 success:bool, 输出 status 族且空键省略
        r = serial_runtime.make_result(success=True, action="scan", summary="ok")
        self.assertEqual(r, {"status": "ok", "action": "scan", "summary": "ok"})
        self.assertNotIn("details", r, "空 details 必须省略 (wb 规范版恒带, 适配器差异点)")
        e = serial_runtime.make_result(success=False, action="a", summary="s",
                                       error={"code": "x"})
        self.assertEqual(e["status"], "error")
        self.assertEqual(set(e), {"status", "action", "summary", "error"})

    def test_serial_make_result_passthrough_no_compact(self):
        # 实测: serial 对 details/error 原样透传 (wb 规范版会 compact_dict 剔空值)
        r = serial_runtime.make_result(
            action="a", summary="s",
            details={"x": 1, "empty": ""}, error={"code": "E", "note": ""})
        self.assertEqual(r["details"], {"x": 1, "empty": ""})
        self.assertEqual(r["error"], {"code": "E", "note": ""})

    def test_wb_ocd_make_result_status_str_details_always_present(self):
        for mod in (wb_runtime, openocd_runtime):
            with self.subTest(mod=mod.__name__):
                r = mod.make_result(status="ok", action="run", summary="s")
                self.assertEqual(r["status"], "ok")
                self.assertNotIn("success", r)
                self.assertIn("details", r, "wb/ocd 规范版 details 键恒在")
                self.assertEqual(r["details"], {})
                self.assertEqual(list(r)[:4],
                                 ["status", "action", "summary", "details"])
                c = mod.make_result(status="ok", action="a", summary="s",
                                    details={"x": 1, "empty": ""})
                self.assertEqual(c["details"], {"x": 1}, "wb/ocd details 走 compact")

    def test_serial_parameter_context_is_name_value_source(self):
        d = serial_runtime.parameter_context("port", "COM3", "cli")
        self.assertEqual(sorted(d), ["name", "source", "value"])

    def test_wb_ocd_parameter_context_is_provider_shape(self):
        for mod in (wb_runtime, openocd_runtime):
            with self.subTest(mod=mod.__name__):
                d = mod.parameter_context(provider="p", workspace=None)
                self.assertIn("provider", d)
                self.assertIn("workspace", d)
                self.assertNotIn("name", d)

    def test_make_timing_is_name_collision_not_dup(self):
        # 实测: ser.make_timing(start_time) 现算耗时; wb.make_timing(started_at,
        # elapsed_ms) 做格式化 —— 同名异物, 各自的钉分别锁形状
        # 注: start_time 用近期真实时间戳 —— epoch 秒 1000 在 Windows 上
        # astimezone() 直接 OSError (pre-epoch 边界, 计划编写时实测撞出)
        t_ser = serial_runtime.make_timing(start_time=time.time() - 1.0)
        self.assertEqual(set(t_ser), {"started_at", "finished_at", "elapsed_ms"})
        self.assertGreaterEqual(t_ser["elapsed_ms"], 1000)
        t_wb = wb_runtime.make_timing("2026-09-01T00:00:00+08:00", 123)
        self.assertEqual(t_wb["started_at"], "2026-09-01T00:00:00+08:00",
                         "wb 版 started_at 逐字透传 (ser 版是换算出来的)")
        self.assertEqual(t_wb["elapsed_ms"], 123)


class StateWireShapeTests(WorkspaceTmpMixin, unittest.TestCase):
    """订正分桶表: state 落盘形态是 wb==serial 序列化 / ocd 原样的真语义分叉。"""

    def _abs_hex(self):
        return str(Path(self.tmp) / "firmware.hex")

    def test_save_workspace_state_serialization_split(self):
        hexpath = self._abs_hex()
        state = {"last_flash": {"hex": hexpath, "n": 1}}
        for mod in (wb_runtime, serial_runtime):
            with self.subTest(mod=mod.__name__):
                p = mod.save_workspace_state(dict(state), self.tmp)
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data["last_flash"]["hex"], "firmware.hex",
                                 "wb/serial 绝对路径须落盘为 workspace 相对 POSIX")
        p = openocd_runtime.save_workspace_state(dict(state), self.tmp)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["last_flash"]["hex"], hexpath,
                         "ocd 原样存 (无序列化, 勿'统一'掉)")

    def test_update_state_entry_serialization_split(self):
        hexpath = self._abs_hex()
        for mod in (wb_runtime, serial_runtime):
            with self.subTest(mod=mod.__name__):
                info = mod.update_state_entry("last_build", {"elf": hexpath},
                                              self.tmp)
                self.assertEqual(info["last_build"]["elf"], "firmware.hex")
                with open(os.path.join(self.tmp, ".workbench", "state.json"),
                          encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data["last_build"]["elf"], "firmware.hex")
        info = openocd_runtime.update_state_entry("last_build", {"elf": hexpath},
                                                  self.tmp)
        self.assertEqual(info["last_build"]["elf"], hexpath)


class NormalizePathContractTests(WorkspaceTmpMixin, unittest.TestCase):
    """T3 Step 2 裁决前置: 两版行为对照, 不许凭行数猜。"""

    def test_wb_ocd_always_resolve(self):
        for mod in (wb_runtime, openocd_runtime):
            with self.subTest(mod=mod.__name__):
                self.assertEqual(mod.normalize_path("sub/file.txt"),
                                 str(Path("sub/file.txt").expanduser().resolve()),
                                 "相对输入必须被 resolve 成绝对")
                self.assertEqual(mod.normalize_path(""), "")
                self.assertEqual(mod.normalize_path(None), "")

    def test_serial_keeps_relative_and_supports_base(self):
        self.assertEqual(serial_runtime.normalize_path("sub/file.txt"),
                         str(Path("sub/file.txt")),
                         "serial 版相对输入不 resolve —— 与 wb 版语义不等价, 非超集")
        got = serial_runtime.normalize_path("log.txt", self.tmp)
        self.assertEqual(got, str((Path(self.tmp) / "log.txt").resolve()))
        self.assertEqual(serial_runtime.normalize_path(None), "")


class SaveProjectConfigNoneValuesTests(WorkspaceTmpMixin, unittest.TestCase):
    """T5 收口前置: values=None 三态各不同 (serial 直接 no-op, wb/ocd 建空段)。"""

    def _cfg(self):
        return os.path.join(self.tmp, ".workbench", "config.json")

    def test_serial_none_values_noop(self):
        serial_runtime.save_project_config(self.tmp, None)
        self.assertFalse(os.path.exists(self._cfg()),
                         "serial 现状: values=None 不建文件 (薄壳不得吞掉这个早退)")

    def test_wb_none_values_creates_section(self):
        wb_runtime.save_project_config(self.tmp, None, skill="gcc")
        with open(self._cfg(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"gcc": {}})

    def test_ocd_none_values_creates_section(self):
        openocd_runtime.save_project_config(self.tmp, None)
        with open(self._cfg(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"openocd": {}})


if __name__ == "__main__":
    unittest.main()
