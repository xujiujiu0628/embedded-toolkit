"""F-016/F-017 回归: 写回型工具的损坏容错与原子写 (2026-08-30 代管 R2).

修复前的家族缺陷: load_json_file "损坏返回 {}" 被当作读改写基础 —
配置/状态文件损坏时, 一次构建/采集/缓存写入会把整个文件重写成只剩
本次写入的段 (config.json 的 verify/openocd/physical_gate 段无声蒸发,
session_fix_cache 待人审条目被清空)。另: save_json_file 非原子
truncate-write, 并发读方会看到半截 JSON, 正是"损坏→清空"链的源头。

三份 runtime 拷贝 (wb/openocd/serial) 同款同修; 全部纯 mock, 不触硬件。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import wb_runtime  # noqa: E402
import openocd_runtime  # noqa: E402
import serial_runtime  # noqa: E402
import gcc_build  # noqa: E402
import error_db_grow  # noqa: E402

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
            # wb_runtime 签名多一个 skill 段名参数 (默认 "keil")
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
    """损坏 state.json: 隔离到 .corrupt 后按新条目重建 (缓存语义, F-016)"""

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
    """gcc_build 的 config.json 写回 (F-017 旗舰路径: 构建即写回)"""

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


class ErrorDbGrowGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_session_cache_quarantined(self):
        cache_path = os.path.join(self.tmp, "session_fix_cache.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        with mock.patch.object(error_db_grow, "_feedback_dir",
                               return_value=self.tmp):
            out = error_db_grow._cache_entry(
                "ev1", {"code": "E001", "meaning": "m"}, 0.5, ["hit"])
        self.assertEqual(out["status"], "cached")
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        self.assertEqual(len(cache["entries"]), 1)
        with open(cache_path + ".corrupt", "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT)

    def test_healthy_session_cache_appends_no_dup(self):
        cache_path = os.path.join(self.tmp, "session_fix_cache.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"_meta": {}, "entries": [{"code": "E000"}]}, f)
        with mock.patch.object(error_db_grow, "_feedback_dir",
                               return_value=self.tmp):
            error_db_grow._cache_entry(
                "ev1", {"code": "E001", "meaning": "m"}, 0.5, [])
            dup = error_db_grow._cache_entry(
                "ev2", {"code": "E001", "meaning": "m"}, 0.5, [])
        self.assertEqual(dup["status"], "already_cached")
        with open(cache_path, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["entries"]), 2)

    def test_corrupt_error_db_refused_not_wiped(self):
        db_path = os.path.join(self.tmp, "keil-error-db.json")
        with open(db_path, "w", encoding="utf-8") as f:
            f.write(CORRUPT)
        with mock.patch.object(error_db_grow, "check_gates",
                               return_value={"all_passed": True, "gates": []}), \
             mock.patch.object(error_db_grow, "load_event", return_value={}), \
             mock.patch.object(error_db_grow, "ERROR_DB_PATH", db_path):
            out = error_db_grow.grow(
                "ev1", {"code": "E001", "type": "error"},
                {"meaning": "plain words only", "causes": [], "fixes": [],
                 "severity": "warn", "category": "unknown"})
        self.assertEqual(out["status"], "error")
        self.assertIn("拒绝写入", out["message"])
        with open(db_path, "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), CORRUPT,
                             "知识库损坏必须原样保留")


if __name__ == "__main__":
    unittest.main()
