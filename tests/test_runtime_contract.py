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
from unittest import mock

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


class ResolveParamContractTests(WorkspaceTmpMixin, unittest.TestCase):
    """T5 终判证据: 三份 resolve_param 是三个独立契约——参数名、来源层级、
    源标签 (会进 wire 的 parameter_sources)、normalize 锚定、异常策略全不同,
    强行参数化=为去重率造回调框架 (计划明令禁止)。裁决: 各留本地。"""

    def test_cli_wins_all_three(self):
        self.assertEqual(wb_runtime.resolve_param("x", "v"), ("v", "cli"))
        self.assertEqual(openocd_runtime.resolve_param("x", "v"), ("v", "cli"))
        self.assertEqual(serial_runtime.resolve_param("x", "v"), ("v", "cli"))

    def test_source_labels_diverge_on_the_wire(self):
        # parameter_sources 值直接进工具 JSON 输出 —— 标签不同即契约不同
        r_wb = wb_runtime.resolve_param("p", None, config={"k": "cv"}, config_keys=["k"])
        self.assertEqual(r_wb, ("cv", "config:k"))
        r_ocd = openocd_runtime.resolve_param("p", None, config={"k": "cv"}, config_keys=["k"])
        self.assertEqual(r_ocd, ("cv", "config:k"))
        r_loc = serial_runtime.resolve_param("p", None, local_config={"k": "lv"}, local_keys=["k"])
        self.assertEqual(r_loc, ("lv", "local:k"), "serial 有 local 层且标签为 local:")
        r_proj = serial_runtime.resolve_param("p", None, project_config={"k": "pv"}, project_keys=["k"])
        self.assertEqual(r_proj, ("pv", "project:k"), "serial 有 project 层且标签为 project:")
        # 层级顺序证据: serial local 先于 project
        both = serial_runtime.resolve_param(
            "p", None, local_config={"k": "L"}, local_keys=["k"],
            project_config={"k": "P"}, project_keys=["k"])
        self.assertEqual(both, ("L", "local:k"))

    def test_default_and_required_policies(self):
        self.assertEqual(serial_runtime.resolve_param("p", None, default=42), (42, "default"))
        self.assertEqual(serial_runtime.resolve_param("p", None), (None, ""),
                         "serial 全 miss 返回 (None,'') 不抛")
        with self.assertRaises(ValueError):
            wb_runtime.resolve_param("p", None, required=True)
        with self.assertRaises(ValueError):
            openocd_runtime.resolve_param("p", None, required=True)
        with self.assertRaises(TypeError):  # serial 无 required 参数
            serial_runtime.resolve_param("p", None, required=True)

    def test_normalize_anchoring_is_semantically_different(self):
        rel = "firmware.elf"
        v_wb, _ = wb_runtime.resolve_param("file", rel, normalize_as_path=True,
                                           workspace=self.tmp)
        self.assertEqual(v_wb, str((Path(self.tmp) / rel).expanduser().resolve()),
                         "wb 版按 workspace 锚定 (normalize_path_with_base)")
        v_ocd, _ = openocd_runtime.resolve_param("file", rel, normalize_as_path=True)
        self.assertEqual(v_ocd, str(Path(rel).expanduser().resolve()),
                         "ocd 版按 cwd 锚定 —— 与 wb 相对路径结果不同")
        self.assertNotEqual(v_wb, v_ocd, "tmp 必不等于 cwd: 锚定差是可测的真分叉")
        with self.assertRaises(TypeError):
            serial_runtime.resolve_param("file", rel, normalize_as_path=True)

    def test_special_tiers_are_machine_name_coupled(self):
        # wb: name=="uv4" 触发 machine:uv4_exe/auto:uv4; ocd: name=="exe" 触发
        # machine:openocd_exe/path/default 兜底 —— 特判钩子各绑各的工具
        _, s_wb = wb_runtime.resolve_param("uv4", None)
        self.assertIn(s_wb, ("", "machine:uv4_exe", "auto:uv4"))
        v_ocd, s_ocd = openocd_runtime.resolve_param("exe", None)
        self.assertIn(s_ocd, ("machine:openocd_exe", "path", "default"))
        self.assertTrue(v_ocd, "ocd exe 恒有兜底值 'openocd' 起步")
        self.assertEqual(wb_runtime.resolve_param("other", None)[1], "",
                         "wb 非 uv4 名无特判")


class LocalConfigContractTests(WorkspaceTmpMixin, unittest.TestCase):
    """T5 裁决证据: 环境级配置是"一 skill 一文件"——wb save_local 是读改写
    merge (故有 F-021 守卫), ocd/serial 是整写 (不读旧文件, 不存在"损坏清空
    其他段"风险, 无守卫系正当设计而非遗漏)。计划原稿"缺失者本次一并补齐守卫"
    经实测撤销: 无缺口可补。裁决: 本族路径+机制均留本地, 只上提 project 族。"""

    def test_wb_save_local_merges_top_level(self):
        cfg_dir = Path(self.tmp) / "config"
        cfg_dir.mkdir()
        cfg = cfg_dir / "keil.json"
        cfg.write_text(json.dumps({"keep": 1, "port": "COM1"}), encoding="utf-8")
        with mock.patch.object(wb_runtime, "default_config_path",
                               lambda *a, **k: cfg):
            out = wb_runtime.save_local_config({"port": "COM9"})
        self.assertEqual(out, cfg)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")),
                         {"keep": 1, "port": "COM9"})

    def test_ocd_save_local_whole_write_replaces(self):
        cfg_dir = Path(self.tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "openocd.json").write_text(json.dumps({"keep": 1}), encoding="utf-8")
        fake_script = Path(self.tmp) / "scripts" / "tool.py"
        fake_script.parent.mkdir()
        fake_script.touch()
        openocd_runtime.save_local_config({"new": 2}, str(fake_script))
        self.assertEqual(
            json.loads((cfg_dir / "openocd.json").read_text(encoding="utf-8")),
            {"new": 2}, "ocd 整写契约: 未给键消失 (与 wb merge 相反, 现状即如此)")

    def test_ocd_serial_save_local_overwrite_corrupt_without_guard(self):
        # 损坏文件 + 整写 = 直接以新内容覆盖 —— 守卫缺位是安全设计 (整写不读旧档)
        cfg_dir = Path(self.tmp) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "serial.json").write_text("{ 坏 JSON", encoding="utf-8")
        with mock.patch.object(serial_runtime, "SKILL_DIR", Path(self.tmp)):
            serial_runtime.save_local_config({"fresh": 1})
        self.assertEqual(
            json.loads((cfg_dir / "serial.json").read_text(encoding="utf-8")),
            {"fresh": 1})

    def test_local_paths_all_resolve_under_toolkit_config(self):
        # 路径策略三写法虽异, 今天的落点同一 (TOOLKIT/config/<skill>.json) —— 钉住落点
        wb_p = wb_runtime.default_config_path(skill="gcc")
        fake_script = Path(__file__).resolve()  # parents[1] = repo root = TOOLKIT_ROOT
        ocd_p = openocd_runtime.default_config_path(str(fake_script))
        ser_p = serial_runtime.SKILL_DIR / "config" / "serial.json"
        for got, name in ((wb_p, "gcc"), (ocd_p, "openocd"), (ser_p, "serial")):
            with self.subTest(skill=name):
                self.assertEqual(got.parents[1], Path(wb_p).parents[1],
                                 "三份环境级配置的 config 目录锚一致")


if __name__ == "__main__":
    unittest.main()
