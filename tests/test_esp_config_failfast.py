"""GAP-F-19 (F-190/T3, WB-20260926-01) — ESP 混配 fail-fast 钉。

维护者裁定 (2026-09-25): builder=idf / flash.backend=esptool /
capture.backend=uart 三标记任一在场 (判定根 = esp_backend_mode OR, 不变)
时, builder、flash.backend、capture.backend 三键必须齐且取值在 ESP 合法集
(builder=idf, flash.backend=esptool, capture.backend∈{uart}); 否则 verify
在任何构建/烧录动作之前 ERROR→exit 1, 文案点名缺哪个键 + 当前值 + 正确配法。

钉四件:
  ① 单标记 + 缺其余键 → exit 1 + 文案含缺失键名 + build/flash 零调用
     (修前红: 混配会静默走缺省派发面);
  ② 三键齐 → 与修前逐字节同行为 (金比对: 修前实测结果剔除时变字段落
     GOLDEN 常量, 特征钉形态);
  ③ 全 STM32 缺省配置 → 不触发 (反向钉, 缺省路径是本仓命脉);
  ④ 撤销实验: 拆 verify 侧校验 → ① 精确红。

规则本体在 runtime_common.esp_backend_config_errors (单一事实源, 与
esp_backend_mode 同层); verify._prepare_context 消费。
四存量 ESP 工程 (esp32-hello / esp32s3-hello / s3-voice / cam-eye) 三键
全显式, 零存量破坏 (WB-20260926-01 盘点)。
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hw_lease  # noqa: E402
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


def _errors(config):
    """规则函数引用 (修前不存在 → AttributeError, 即钉的红态)。"""
    return runtime_common.esp_backend_config_errors(config)


class EspConfigErrorsUnitTests(unittest.TestCase):
    """规则本体: 标记→三键齐+合法; 无标记→空。"""

    def test_no_marker_no_error(self):
        # 反向钉 ③: STM32 缺省 / 空配置 / None 一律不触发
        for cfg in (STM32_CONFIG, {}, None,
                    {"toolkit_min_version": "0.1"},
                    {"capture": {"backend": "rtt"}}):
            self.assertEqual(_errors(cfg), [], cfg)

    def test_full_esp_config_no_error(self):
        self.assertEqual(_errors(ESP_CONFIG), [])

    def test_each_single_marker_names_missing_keys(self):
        # ①: 任一单标记在场 → 缺的两键逐条点名
        for marker, expect_missing in (
                ({"builder": "idf"}, ("flash.backend", "capture.backend")),
                ({"flash": {"backend": "esptool"}},
                 ("builder", "capture.backend")),
                ({"capture": {"backend": "uart"}}, ("builder", "flash.backend")),
        ):
            with self.subTest(marker=marker):
                errs = _errors(marker)
                self.assertEqual(len(errs), 2, errs)
                text = "\n".join(errs)
                for key in expect_missing:
                    self.assertIn(key, text)

    def test_wrong_values_named_with_current(self):
        errs = _errors({"builder": "gcc", "flash": {"backend": "esptool"},
                        "capture": {"backend": "uart"}})
        text = "\n".join(errs)
        self.assertIn("builder", text)
        self.assertIn("'gcc'", text)
        errs = _errors({"builder": "idf", "flash": {"backend": "openocd"},
                        "capture": {"backend": "uart"}})
        self.assertIn("flash.backend", "\n".join(errs))
        self.assertIn("'openocd'", "\n".join(errs))
        errs = _errors({"builder": "idf", "flash": {"backend": "esptool"},
                        "capture": {"backend": "rtt"}})
        self.assertIn("capture.backend", "\n".join(errs))
        self.assertIn("'rtt'", "\n".join(errs))

    def test_missing_keys_report_effective_default(self):
        # 文案给"当前值": 键缺席时报缺省派发值 (混配的实际去向)
        errs = _errors({"capture": {"backend": "uart"}})
        text = "\n".join(errs)
        self.assertIn("缺省 'gcc'", text)
        self.assertIn("缺省 'openocd'", text)


def _strip_volatile(node):
    """金比对归一: 剔时变字段 (时间戳/时长) 与本机路径, 留 wire 形态。"""
    if isinstance(node, dict):
        return {k: ("<WS>" if k == "workspace" else _strip_volatile(v))
                for k, v in node.items()
                if k not in ("elapsed_sec", "duration_sec", "started_at",
                             "finished_at", "timestamp", "ts")}
    if isinstance(node, list):
        return [_strip_volatile(x) for x in node]
    return node


class _MainFlowHarness(unittest.TestCase):
    """驱动 main() 的 mock 风格与 test_esp_backend_gate 同款 (F-164 教训:
    计时/睡眠类依赖一并隔离)。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "boot", "texts": ["[init] OK"]},
            ]}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run(self, config, capture_text="[init] OK"):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(config, f)
        argv = ["verify.py", "--project", self.ws, "--json"]
        out, err = io.StringIO(), io.StringIO()
        reset_mock = mock.Mock(return_value={"status": "ok"})
        sp_run = mock.Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="mock no device"))
        cap_uart = mock.Mock(return_value={"status": "ok", "method": "uart",
                                           "_text": capture_text})
        cap_semi = mock.Mock(return_value=(capture_text, ""))
        build_mock = mock.Mock(return_value={
            "status": "ok", "summary": "s",
            "metrics": {"errors": 0, "warnings": 0}, "details": {}})
        flash_mock = mock.Mock(return_value={
            "status": "ok", "stderr": "Verified", "stdout": ""})
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build", build_mock), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash", flash_mock), \
                mock.patch.object(verify, "run_semihosting_session", cap_semi), \
                mock.patch.object(verify.esp_runtime, "step_capture_uart",
                                  cap_uart), \
                mock.patch.object(verify, "reset_target", reset_mock), \
                mock.patch.object(verify.subprocess, "run", sp_run), \
                mock.patch.object(hw_lease, "DEVICE_LOCK_DIR",
                                  os.path.join(self.ws, "device-locks")), \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    verify.main()
                    code = 0
                except SystemExit as e:
                    code = e.code
        return {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue(),
                "build_mock": build_mock, "flash_mock": flash_mock}


class MixedConfigFailFastTests(_MainFlowHarness):
    """① 主流程: 混配在任何构建/烧录动作之前 exit 1 (修前红)。"""

    def test_single_marker_fails_fast_before_any_action(self):
        # 夹具即 F-188 时代的三种单标记混配 — 裁定后正是 fail-fast 对象
        for marker in ({"builder": "idf"},
                       {"flash": {"backend": "esptool", "port": "COM3"}},
                       {"capture": {"backend": "uart", "port": "COM3"}}):
            cfg = dict(marker, toolkit_min_version="0.1",
                       physical_gate={"enable": True})
            with self.subTest(marker=marker):
                r = self._run(cfg)
                self.assertEqual(r["code"], 1, r["stderr"])
                self.assertEqual(r["stdout"], "")   # 未进管线, 无 JSON
                r["build_mock"].assert_not_called()
                r["flash_mock"].assert_not_called()
                text = r["stderr"]
                self.assertIn("GAP-F-19", text)
                self.assertIn("builder", text)
                self.assertIn("flash.backend", text)
                self.assertIn("capture.backend", text)
                self.assertIn("正确配法", text)

    def test_builder_conflict_fails_fast(self):
        # 显式 builder=gcc + esptool 标记 → 点名 builder 当前值
        cfg = dict(ESP_CONFIG, builder="gcc")
        r = self._run(cfg)
        self.assertEqual(r["code"], 1, r["stderr"])
        self.assertIn("'gcc'", r["stderr"])
        r["build_mock"].assert_not_called()


class GoldenBehaviorTests(_MainFlowHarness):
    """② 金比对: 三键齐 (与全 STM32 缺省) 行为与修前逐字节同。

    GOLDEN = 修前 (afe6bf0) 实测结果剔除时变字段; 撤销实验不红本类
    (行为保持钉), 由 MixedConfigFailFastTests 承担红态。"""

    GOLDEN = json.loads(r"""{
 "esp_full": {
  "captured_output": "[init] OK",
  "contract_hashes": {
   "config_sha256": "07f5b6da0f19cb86a0537340ccb7654748cb44428b7e23d9e72071335789323a",
   "expectations_sha256": "18f8f7c28e99a8c46ea6a70444429a8d7e2cfa2b3050d807320b19c883e1f0f7"
  },
  "description": "",
  "evidence": "hardware_validated",
  "expect": [],
  "expect_mode": "manifest",
  "feedback": {"error": "mock no device", "logged": false},
  "pipeline": "build → analyze → flash → capture → verify",
  "post_reset": "skipped",
  "records": [],
  "retry_config": {"max_retries": 0, "retry_delay": 2},
  "status": "ok",
  "steps": {
   "analyze": {"errors": 0, "matched": 0, "status": "ok", "unmatched": 0, "warnings": 0},
   "build": {
    "attempts": [{"attempt": 1, "errors": 0, "status": "ok", "warnings": 0}],
    "errors": 0, "hex_file": "", "log_file": "", "retry_count": 0,
    "status": "ok", "summary": "s", "warnings": 0
   },
   "capture": {"method": "uart", "origin": "manual", "status": "ok"},
   "flash": {
    "attempts": [{"attempt": 1, "message": "Verified", "status": "ok"}],
    "message": "Verified", "origin": "manual", "retry_count": 0, "status": "ok"
   },
   "physical_gate": {
    "reason": "F-188/N-4 ESP 后端: physical_gate 经 OpenOCD 采 GPIO, OpenOCD/ST-Link 不在 ESP 链路, 步骤抑制",
    "status": "skipped"
   },
   "verify": {
    "all_expected_found": true, "description": "",
    "matched": ["FR-SYS-01"], "missing": [], "needs_ai_judgement": true,
    "results": [{"id": "FR-SYS-01", "status": "pass"}],
    "status": "ok", "xpass_ids": []
   }
  },
  "toolkit_version": "0.6",
  "workspace": "<WS>"
 },
 "stm32_default": {
  "captured_output": "[init] OK",
  "contract_hashes": {
   "config_sha256": "4b0003530c52d6da23b7733c882bc3d6d7673a954c9389bc5818888160832404",
   "expectations_sha256": "18f8f7c28e99a8c46ea6a70444429a8d7e2cfa2b3050d807320b19c883e1f0f7"
  },
  "description": "",
  "evidence": "hardware_validated",
  "expect": [],
  "expect_mode": "manifest",
  "feedback": {"error": "mock no device", "logged": false},
  "pipeline": "build → analyze → flash → capture → verify",
  "post_reset": "ok",
  "records": [],
  "retry_config": {"max_retries": 0, "retry_delay": 2},
  "status": "ok",
  "steps": {
   "analyze": {"errors": 0, "matched": 0, "status": "ok", "unmatched": 0, "warnings": 0},
   "build": {
    "attempts": [{"attempt": 1, "errors": 0, "status": "ok", "warnings": 0}],
    "errors": 0, "hex_file": "", "log_file": "", "retry_count": 0,
    "status": "ok", "summary": "s", "warnings": 0
   },
   "capture": {"lines": 1, "method": "semihosting", "origin": "manual",
               "raw_length": 9, "status": "ok", "timeout_sec": 10},
   "flash": {
    "attempts": [{"attempt": 1, "message": "Verified", "status": "ok"}],
    "message": "Verified", "origin": "manual", "retry_count": 0, "status": "ok"
   },
   "physical_gate": {"status": "skipped"},
   "verify": {
    "all_expected_found": true, "description": "",
    "matched": ["FR-SYS-01"], "missing": [], "needs_ai_judgement": true,
    "results": [{"id": "FR-SYS-01", "status": "pass"}],
    "status": "ok", "xpass_ids": []
   }
  },
  "toolkit_version": "0.6",
  "workspace": "<WS>"
 }
}""")

    def _golden(self, config, key):
        r = self._run(config)
        self.assertEqual(r["code"], 0, r["stderr"])
        self.assertEqual(_strip_volatile(json.loads(r["stdout"])),
                         self.GOLDEN[key])

    def test_full_esp_config_golden_unchanged(self):
        self._golden(ESP_CONFIG, "esp_full")

    def test_stm32_default_golden_unchanged(self):
        # 反向钉 ③ 的主流程面: 缺省路径逐字节不动
        self._golden(STM32_CONFIG, "stm32_default")


if __name__ == "__main__":
    unittest.main()
