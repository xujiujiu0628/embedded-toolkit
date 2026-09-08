"""F-019/F-020 回归: 写回型工具的损坏容错与原子写 (2026-08-30 代管 R2).

修复前的家族缺陷: load_json_file "损坏返回 {}" 被当作读改写基础 —
配置/状态文件损坏时, 一次构建/采集/缓存写入会把整个文件重写成只剩
本次写入的段 (config.json 的 verify/openocd/physical_gate 段无声蒸发,
session_fix_cache 待人审条目被清空)。另: save_json_file 非原子
truncate-write, 并发读方会看到半截 JSON, 正是"损坏→清空"链的源头。

F-029 后三 runtime (wb/openocd/serial) 走 runtime_common 共享层同一实现——单一
事实源, 同款同修收敛一处 (本地仅再导出/钩子薄壳); 全部纯 mock, 不触硬件。

2026-09-05 (F-067b/c): error_db_grow 随 Keil 退役区拆 archive, 本测试不再
import 它。error_db_grow 自身的 5 例 _cache_entry / grow / 损坏拒写回归已
留在 archive 副本上, 不在主仓验证范围 (主仓零 Keil 引用 = 验证目标)。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import wb_runtime  # noqa: E402
import openocd_runtime  # noqa: E402
import serial_runtime  # noqa: E402
import runtime_common  # noqa: E402  (F-029 T2 起 save_json_file 的 os.replace 住在这里)
import gcc_build  # noqa: E402
import wb_common  # noqa: E402

RUNTIMES = [wb_runtime, openocd_runtime, serial_runtime]
CORRUPT = "{ 不是 JSON"


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tmp_leftover_and_content_correct(self):
        for mod in RUNTIMES:
            with self.subTest(mod=mod.__name__):
                p = os.path.join(self.tmp, f"{mod.__name__}.json")
                mod.save_json_file(p, {"a": 1})
                with open(p, encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"a": 1})
                self.assertFalse(os.path.exists(p + ".tmp"),
                                 "原子写不得残留 .tmp 文件")


class SaveProjectConfigGuardTests(unittest.TestCase):
    """损坏 config.json: 拒绝写回且原文不动 (三份 runtime 同契约)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".workbench"))
        self.cfg = os.path.join(self.tmp, ".workbench", "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _corrupt_case(self, mod):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        ret = mod.save_project_config(self.tmp, {"port": "COM3"})
        with open(self.cfg, "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT,
                             "损坏 config.json 必须原样保留 (可手工恢复)")
        if mod is wb_runtime:
            self.assertIsNone(ret)

    def _healthy_case(self, mod, skill):
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"verify": {"expect": ["OK"]}, skill: {"project": "old"}},
                      f)
        if mod is wb_runtime:
            # wb_runtime 签名多一个 skill 段名参数 (默认 "wb" 是历史延续,
            # 原 "keil" 2026-08-28 中性化、2026-09-05 F-067a 退役区拆 archive
            # 后改 "wb"; 默认值仅兼容, 实际调用方均显式传 skill="gcc"/"openocd"/"serial")
            mod.save_project_config(self.tmp, {"port": 1}, skill=skill)
        else:
            mod.save_project_config(self.tmp, {"port": 1})
        with open(self.cfg, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["verify"], {"expect": ["OK"]},
                         "其他段必须原样保留")
        self.assertEqual(data[skill]["port"], 1)
        self.assertEqual(data[skill]["project"], "old")

    def test_wb_runtime(self):
        self._corrupt_case(wb_runtime)
        self._healthy_case(wb_runtime, "gcc")

    def test_openocd_runtime(self):
        self._corrupt_case(openocd_runtime)
        self._healthy_case(openocd_runtime, "openocd")

    def test_serial_runtime(self):
        self._corrupt_case(serial_runtime)
        self._healthy_case(serial_runtime, "serial")

    def test_missing_config_creates_fresh(self):
        # 默认路径: config.json 不存在 → 正常创建 (不是损坏场景)
        serial_runtime.save_project_config(self.tmp, {"port": 2})
        with open(self.cfg, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"serial": {"port": 2}})


class UpdateStateEntryGuardTests(unittest.TestCase):
    """损坏 state.json: 隔离到 .corrupt 后按新条目重建 (缓存语义, F-019)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".workbench"))
        self.state = os.path.join(self.tmp, ".workbench", "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _corrupt_case(self, mod):
        with open(self.state, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        info = mod.update_state_entry("last_build",
                                      {"provider": "x", "action": "build"},
                                      self.tmp)
        self.assertEqual(info["updated_keys"], ["last_build"])
        with open(self.state, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["last_build"]["provider"], "x")
        with open(self.state + ".corrupt", "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT,
                             "损坏原文必须隔离保留")

    def _healthy_case(self, mod):
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"last_flash": {"hex": "old.hex"}}, f)
        mod.update_state_entry("last_build", {"provider": "x"}, self.tmp)
        with open(self.state, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["last_flash"], {"hex": "old.hex"},
                         "健康文件的其他条目必须保留")

    def test_wb_runtime(self):
        self._corrupt_case(wb_runtime)
        self._healthy_case(wb_runtime)

    def test_openocd_runtime(self):
        self._corrupt_case(openocd_runtime)
        self._healthy_case(openocd_runtime)

    def test_serial_runtime(self):
        self._corrupt_case(serial_runtime)
        self._healthy_case(serial_runtime)


class LoadStateForUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".workbench"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_quarantined_and_empty(self):
        for mod in RUNTIMES:
            with self.subTest(mod=mod.__name__):
                p = os.path.join(self.tmp, ".workbench", "state.json")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(CORRUPT)
                self.assertEqual(mod.load_workspace_state_for_update(self.tmp), {})
                with open(p + ".corrupt", "rb") as f:
                    self.assertEqual(f.read().decode("utf-8"), CORRUPT)

    def test_healthy_passthrough(self):
        p = os.path.join(self.tmp, ".workbench", "state.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"k": 1}, f)
        self.assertEqual(wb_runtime.load_workspace_state_for_update(self.tmp),
                         {"k": 1})
        self.assertFalse(os.path.exists(p + ".corrupt"))

    def test_readonly_loader_still_tolerant(self):
        # 只读消费方 (F-007 语义) 不受影响: 损坏当空, 不动文件
        p = os.path.join(self.tmp, ".workbench", "state.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        self.assertEqual(wb_runtime.load_workspace_state(self.tmp), {})
        self.assertFalse(os.path.exists(p + ".corrupt"))


class GccBuildWritebackTests(unittest.TestCase):
    """gcc_build 的 config.json 写回 (F-020 旗舰路径: 构建即写回)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".workbench"))
        self.cfg = os.path.join(self.tmp, ".workbench", "config.json")
        self.makefile = os.path.join(self.tmp, "gcc-pilot", "Makefile")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_config_refuses_writeback(self):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        with self.assertRaises(wb_runtime.JSONCorruptError):
            gcc_build.merge_gcc_config(self.cfg, self.makefile, "t1",
                                       os.path.join(self.tmp, ".workbench", "build"),
                                       self.tmp)
        with open(self.cfg, "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT)

    def test_healthy_writeback_preserves_other_sections(self):
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"verify": {"expect": ["OK"]}, "gcc": {"target": "old"}},
                      f)
        out = gcc_build.merge_gcc_config(
            self.cfg, self.makefile, "t1",
            os.path.join(self.tmp, ".workbench", "build"), self.tmp)
        self.assertEqual(out, {"status": "ok"})
        with open(self.cfg, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["verify"], {"expect": ["OK"]})
        self.assertEqual(data["gcc"]["target"], "t1")

    def test_missing_config_creates_gcc_section(self):
        out = gcc_build.merge_gcc_config(
            self.cfg, self.makefile, "",
            os.path.join(self.tmp, ".workbench", "build"), self.tmp)
        self.assertEqual(out, {"status": "ok"})
        with open(self.cfg, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("gcc", data)


class TmpNameProcessScopedTests(unittest.TestCase):
    """F-023: save_json_file 的 tmp 名须带 pid — 固定 <name>.tmp 在双进程
    并发写同一目标时会互相顶掉 (两个写者共用一个 tmp, 混掺半成品)

    F-029 T2 后 save_json_file 上提至 runtime_common (三 runtime 再导出同一
    函数对象), patch 目标随之改为 runtime_common.os — mod.os 虽同为 os 单例,
    openocd_runtime 已无 import os, 且"实现住哪就 patch 哪"才诚实。三 mod
    循环保留: 验证的是各 mod.X 再导出面确实可达同一实现。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tmp_carries_pid(self):
        for mod in RUNTIMES:
            with self.subTest(mod=mod.__name__):
                p = os.path.join(self.tmp, f"pid.{mod.__name__}.json")
                seen = {}
                real_replace = os.replace

                def fake(src, dst):
                    seen["tmp"] = str(src)
                    return real_replace(src, dst)

                with mock.patch.object(runtime_common.os, "replace", fake):
                    mod.save_json_file(p, {"a": 1})
                self.assertTrue(
                    seen["tmp"].endswith(".%d.tmp" % os.getpid()),
                    "tmp 名必须是 <file>.<pid>.tmp, 实得: " + seen["tmp"])
                self.assertFalse(os.path.exists(p + ".tmp"))
                with open(p, encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"a": 1})


class SharedAtomicWriteJsonTests(unittest.TestCase):
    """F-022: wb_common.atomic_write_json — release 等独立脚本
    共用的原子写工具 (2026-09-05 F-067b: 原 error_db_grow 已随 Keil 退役区
    拆 archive, 从消费方名单移除; 与 runtime 侧同口径: pid tmp + 强制 LF)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip_parent_mkdir_and_lf(self):
        p = os.path.join(self.tmp, "deep", "nested.json")  # 父目录不存在→自动建
        wb_common.atomic_write_json(p, {"k": "值"})
        with open(p, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r\n", raw, "行尾必须强制 LF (跨平台一致性)")
        self.assertEqual(json.loads(raw.decode("utf-8")), {"k": "值"})
        self.assertEqual(
            [fn for fn in os.listdir(os.path.dirname(p)) if fn.endswith(".tmp")],
            [], "不得残留 tmp")

    def test_no_bare_json_writes_in_standalone_scripts(self):
        # 静态判据: F-022 裸写 (release:201) 全部收口, 且防回潮 —
        # open('w') 后 3 行内出现 json.dump 即违例。
        # 2026-09-05 F-067b: error_db_grow.py 随 Keil 退役区拆 archive,
        # 从静态判据名单移除; release.py 是仓内唯一独立可执行脚本,
        # 仍由本判据盯防。
        pat_open = re.compile(r"open\(.*['\"]w[bt]?['\"]")
        offenders = []
        for fname in ("release.py",):
            with open(os.path.join(SCRIPTS_DIR, fname), encoding="utf-8") as f:
                lines = f.readlines()
            for i, ln in enumerate(lines):
                if pat_open.search(ln) and any(
                        "json.dump(" in w for w in lines[i + 1:i + 4]):
                    offenders.append(f"{fname}:{i + 1}")
        self.assertEqual([], offenders,
                         "裸 JSON 写须改用 wb_common.atomic_write_json")


class LocalConfigGuardTests(unittest.TestCase):
    """F-021: wb_runtime.save_local_config 是读改写族 — 损坏 config 必须拒绝
    写回返回 None 且原文不动 (与 save_project_config/F-020 同族契约;
    openocd/serial 侧同名函数是整写语义, 不在本族)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 2026-09-05 (F-067a): fixture 路径 keil.json → wb.json, 与
        # wb_runtime.save_local_config 的"一 skill 一文件"机制测本质无关,
        # 改中性化名以反映 Keil 退役区拆 archive 后的实际职责。
        self.cfg = os.path.join(self.tmp, "config", "wb.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patched(self):
        return mock.patch.object(wb_runtime, "default_config_path",
                                 lambda *a, **k: Path(self.cfg))

    def test_corrupt_refused_not_wiped(self):
        os.makedirs(os.path.dirname(self.cfg))
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        with self._patched():
            out = wb_runtime.save_local_config({"new_key": 1})
        self.assertIsNone(out)
        with open(self.cfg, "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT,
                             "损坏原文必须原样保留 (可手工恢复)")

    def test_healthy_merges_and_creates(self):
        with self._patched():
            out = wb_runtime.save_local_config({"port": "COM9"})
        self.assertEqual(str(out), self.cfg)
        with self._patched():
            wb_runtime.save_local_config({"x": 2})
        with open(self.cfg, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"port": "COM9", "x": 2})


if __name__ == "__main__":
    unittest.main()
