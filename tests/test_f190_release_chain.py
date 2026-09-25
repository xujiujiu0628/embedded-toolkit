"""F-190 (WB-20260926-01) — ESP 发布链收口钉: H-1 artifacts 键错配 + M-1 G0.5 无闸。

背景 (WB-20260925-01 报告 §一):
  H-1: esp_runtime._write_last_build 只写平铺键, release.build_record 只认
       嵌套 last_build.artifacts (release.py:167) → ESP 发布链 G0~G2 全绿后
       恒 sys.exit(1) ("缺 hex 哈希证据")。修向 = _write_last_build 改调
       runtime_common.update_state_entry, 与 gcc_build.py:265-281 双形态对齐
       (嵌套 artifacts + 平铺键, 平铺键供 verify.py:805 --no-build 回读)。
  M-1: release.run_gates 的 G0.5 swd_probe 无后端闸 (release.py:107) —
       OpenOCD/ST-Link 专属动作, ESP 工程语义失真 (无 ST-Link 拦死 /
       有 ST-Link 错误目标放行)。修向 = _esp_backend_mode 判据上收
       runtime_common 单一事实源 (verify 再导出, release 消费), ESP 模式
       G0.5 抑制 + 落可机检 skipped 痕 (status/reason, F-188 N-4 同构);
       同面 tools.gcc 对 ESP 记 "not_applicable(esp-idf project)"。

钉法 (合成 state 法, 零真机): 造 build/*.bin|*.elf fixture + mock run_idf;
release 主流程 mock 断到 "hex 在场放行" (dry-run, 不打真 tag)。
撤销实验: 拆 _write_last_build 的 artifacts 键 → 本文件 T1① 类精确红。
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import esp_runtime  # noqa: E402
import release  # noqa: E402
import runtime_common  # noqa: E402
import verify  # noqa: E402

ESP_CONFIG = {"toolkit_min_version": "0.1", "builder": "idf",
              "idf": {"build_timeout": 900},
              "flash": {"backend": "esptool", "port": "COM3"},
              "capture": {"backend": "uart", "port": "COM3",
                          "baudrate": 115200, "settle_sec": 0.0,
                          "duration_sec": 15}}
STM32_CONFIG = {"toolkit_min_version": "0.1", "builder": "gcc",
                "gcc": {"project": "Makefile", "target": "main",
                        "log_dir": ".workbench/build"}}

GREEN_VERIFY = {"status": "ok", "evidence": "hardware_validated",
                "steps": {"verify": {"results": [
                    {"id": "FR-A", "status": "pass"}]}}}


class _ArtifactFixture(unittest.TestCase):
    """build/*.bin|*.elf 产物 + .workbench 目录的合成 ESP 工程现场。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, "build"))
        os.makedirs(os.path.join(self.ws, ".workbench"))
        self.bin_bytes = b"F190-BIN-PAYLOAD"
        self.elf_bytes = b"F190-ELF-PAYLOAD"
        with open(os.path.join(self.ws, "build", "app.bin"), "wb") as f:
            f.write(self.bin_bytes)
        with open(os.path.join(self.ws, "build", "app.elf"), "wb") as f:
            f.write(self.elf_bytes)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _build(self):
        """mock run_idf 走真 step_build_idf → 真写 state.json last_build。"""
        r = esp_runtime.step_build_idf(
            {"idf": {}}, workspace=self.ws,
            _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                      "output": "Executing idf.py build\nDone\n"})
        self.assertEqual(r["status"], "ok")
        return r


class T1ArtifactsChainTests(_ArtifactFixture):
    """H-1: 发布记录链修通 — 嵌套 artifacts 在场 → hex 哈希证据在场。"""

    def test_build_record_carries_hex_sha256(self):
        """T1①: ESP 构建 fixture → _write_last_build → build_record 产物含
        {"hex": {"sha256": ...}} (哈希 = bin/elf 文件各自 sha256, 语义即
        release.py 既有现场, 不自创)。撤销实验: 拆 artifacts 键 → 本例红。"""
        self._build()
        rec = release.build_record(self.ws, "v9.9.9", [], [])
        self.assertEqual(rec["artifacts"]["hex"]["path"], "build/app.bin")
        self.assertEqual(rec["artifacts"]["hex"]["sha256"],
                         hashlib.sha256(self.bin_bytes).hexdigest())
        self.assertEqual(rec["artifacts"]["elf"]["sha256"],
                         hashlib.sha256(self.elf_bytes).hexdigest())

    def test_release_main_flow_hex_passes_to_dryrun(self):
        """T1① 主流程: hex 在场放行 — release main 走到 dry-run 输出
        artifacts=['hex', 'elf'], 不再因缺 hex 硬拒 (不打真 tag)。"""
        self._build()
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(ESP_CONFIG, f)
        probe = mock.Mock(return_value=(True, "ok"))
        out = io.StringIO()
        with mock.patch.object(release, "g0_checks", return_value=[]), \
                mock.patch.object(release, "gate1",
                                  mock.Mock(return_value=dict(GREEN_VERIFY))), \
                mock.patch.object(release, "swd_probe", probe), \
                mock.patch.object(sys, "argv",
                                  ["release.py", "--tag", "v9.9.9",
                                   "--project", self.ws, "--dry-run"]):
            with redirect_stdout(out):
                try:
                    release.main()
                    code = 0
                except SystemExit as e:
                    code = e.code
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("'hex'", out.getvalue())
        self.assertIn("'elf'", out.getvalue())

    def test_write_last_build_keeps_flat_keys(self):
        """T1② 平铺键红绿对的"绿"腿: verify --no-build 回读契约
        (verify.py:805 last_build.hex_file) 必须在改写 update_state_entry 后
        逐字节存活 — 平铺键名 hex_file/bin_file/elf_file 不变。"""
        esp_runtime._write_last_build(self.ws, "build/app.bin", "build/app.elf")
        with open(os.path.join(self.ws, ".workbench", "state.json"),
                  encoding="utf-8") as f:
            lb = json.load(f)["last_build"]
        self.assertEqual(lb["provider"], "idf")
        self.assertEqual(lb["hex_file"], "build/app.bin")
        self.assertEqual(lb["bin_file"], "build/app.bin")
        self.assertEqual(lb["elf_file"], "build/app.elf")

    def test_write_last_build_writes_nested_artifacts(self):
        """T1② 平铺键红绿对的"红"腿 (修前红): 嵌套 last_build.artifacts
        必须与平铺键同写 (gcc_build.py:278 双形态先例) — release 消费面。"""
        esp_runtime._write_last_build(self.ws, "build/app.bin", "build/app.elf")
        with open(os.path.join(self.ws, ".workbench", "state.json"),
                  encoding="utf-8") as f:
            lb = json.load(f)["last_build"]
        self.assertEqual(lb["artifacts"],
                         {"hex_file": "build/app.bin",
                          "bin_file": "build/app.bin",
                          "elf_file": "build/app.elf"})

    def test_state_write_survives_existing_state(self):
        """update_state_entry 读改写保底: 既有 state 键不被整体覆写蒸发
        (F-174a 收口面 — 旧实现损坏/覆写即丢全史)。"""
        state_p = os.path.join(self.ws, ".workbench", "state.json")
        with open(state_p, "w", encoding="utf-8") as f:
            json.dump({"other_key": {"keep": True}}, f)
        self._build()
        with open(state_p, encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["other_key"], {"keep": True})
        self.assertEqual(state["last_build"]["provider"], "idf")


class _GitWsFixture(unittest.TestCase):
    """真 git 仓 + 已提交 config.json 的工程现场 (G0 面走真判定)。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()

        def git(*a):
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"]
                           + list(a), cwd=self.ws, capture_output=True,
                           timeout=30, check=True)

        git("init", "-q")
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("x")
        git("add", "-A")
        git("commit", "-qm", "init")
        self.git = git

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _commit_config(self, config):
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb, exist_ok=True)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
        self.git("add", "-A")
        self.git("commit", "-qm", "cfg")


class T2G05GateTests(_GitWsFixture):
    """M-1: G0.5 swd_probe 入 ESP 后端闸 (双向钉)。

    ① ESP 模式 → swd_probe 零调用 + 放行 + ctx.g0_5 = {status: skipped,
       reason: ...} (可机检, F-188 N-4 形态); ② STM32 模式 → 探活照调一次,
       失败拦死文案逐字节不变。撤销实验: 拆闸 → ① 精确红。"""

    def test_esp_mode_skips_swd_probe_with_trace(self):
        self._commit_config(ESP_CONFIG)
        probe = mock.Mock(return_value=(True, "ok"))
        gate1 = mock.Mock(return_value=dict(GREEN_VERIFY))
        with mock.patch.object(release, "swd_probe", probe), \
                mock.patch.object(release, "gate1", gate1):
            ok, msg, ctx = release.run_gates(self.ws, "v1.0.0",
                                             allow_xfail=False, timeout=10,
                                             openocd_exe="openocd")
        self.assertTrue(ok, msg)
        probe.assert_not_called()
        gate1.assert_called_once()   # G0.5 抑制不波及 G1
        self.assertEqual(ctx["g0_5"]["status"], "skipped")
        self.assertIn("ESP", ctx["g0_5"]["reason"])

    def test_stm32_mode_still_probes(self):
        self._commit_config(STM32_CONFIG)
        probe = mock.Mock(return_value=(True, "ok"))
        with mock.patch.object(release, "swd_probe", probe), \
                mock.patch.object(release, "gate1",
                                  mock.Mock(return_value=dict(GREEN_VERIFY))):
            ok, msg, ctx = release.run_gates(self.ws, "v1.0.0",
                                             allow_xfail=False, timeout=10,
                                             openocd_exe="openocd")
        self.assertTrue(ok, msg)
        probe.assert_called_once_with("openocd")
        self.assertNotIn("g0_5", ctx)   # STM32 行为零新增

    def test_stm32_probe_failure_blocks_unchanged(self):
        self._commit_config(STM32_CONFIG)
        probe = mock.Mock(return_value=(False, "no connection"))
        with mock.patch.object(release, "swd_probe", probe):
            ok, msg, ctx = release.run_gates(self.ws, "v1.0.0",
                                             allow_xfail=False, timeout=10,
                                             openocd_exe="openocd")
        self.assertFalse(ok)
        self.assertIn("G0.5 SWD 预检失败 (环境未备?): no connection", msg)
        self.assertEqual(ctx, {})

    def test_missing_config_defaults_to_stm32_gate(self):
        # 无 config.json (既有 run_gates 测试现场) → STM32 缺省语义: 照探
        probe = mock.Mock(return_value=(True, "ok"))
        with mock.patch.object(release, "swd_probe", probe), \
                mock.patch.object(release, "gate1",
                                  mock.Mock(return_value=dict(GREEN_VERIFY))):
            ok, _, _ = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                         timeout=10, openocd_exe="openocd")
        self.assertTrue(ok)
        probe.assert_called_once()


class T2RecordTraceTests(_GitWsFixture):
    """M-1 同面: skipped 痕与 tools.gcc 分流落进发布记录 (可机检)。"""

    def test_esp_record_carries_g05_skipped_trace(self):
        self._commit_config(ESP_CONFIG)
        rec = release.build_record(self.ws, "v1.0.0", [], [])
        self.assertEqual(rec["g0_5"]["status"], "skipped")
        self.assertIn("ESP", rec["g0_5"]["reason"])

    def test_esp_record_tools_gcc_not_applicable(self):
        self._commit_config(ESP_CONFIG)
        rec = release.build_record(self.ws, "v1.0.0", [], [])
        self.assertEqual(rec["tools"]["gcc"], "not_applicable(esp-idf project)")

    def test_stm32_record_unchanged(self):
        # 双向钉: STM32 记录无 g0_5 键、tools.gcc 照走探测路径 (非 ESP 常量)
        self._commit_config(STM32_CONFIG)
        rec = release.build_record(self.ws, "v1.0.0", [], [])
        self.assertNotIn("g0_5", rec)
        self.assertNotEqual(rec["tools"]["gcc"],
                            "not_applicable(esp-idf project)")


class T2SingleSourceTests(unittest.TestCase):
    """M-1 前置: 三标记 OR 判据上收 runtime_common 单一事实源 —
    verify 侧只是再导出 (F-057 形态), 不得出现两份 OR 逻辑副本。"""

    def test_predicate_lives_in_runtime_common(self):
        self.assertTrue(hasattr(runtime_common, "esp_backend_mode"))
        self.assertIs(verify._esp_backend_mode, runtime_common.esp_backend_mode)

    def test_predicate_semantics_intact(self):
        # 上收只是搬家: 三标记 OR 语义原样 (既有 EspModePredicateTests 同面,
        # 此处钉 runtime_common 原件)
        f = runtime_common.esp_backend_mode
        self.assertFalse(f(None))
        self.assertFalse(f(STM32_CONFIG))
        for cfg in ({"builder": "idf"}, {"flash": {"backend": "esptool"}},
                    {"capture": {"backend": "uart"}}, ESP_CONFIG):
            self.assertTrue(f(cfg), cfg)


if __name__ == "__main__":
    unittest.main()
