"""F-174/I-1 + 合入前置票: ESP 模式 OpenOCD 动作后端闸 + port/chip 白名单。

背景 (终审#2 findings): post_reset (F-129) 与 hardfault 层 2 (F-115) 都是
占 ST-Link 跑 OpenOCD 的 Cortex-M 专属动作; F-174 引入 esptool/uart 后端后
未按后端设闸——09-16 esp32s3-hello 双 PASS 属"ST-Link 失联碰巧无害"。
ESP 侧复位职责归 capture 起点 (esptool chip_id --after hard_reset), panic
归因归 capture 的 esp_panic 文本标记 + AI 判定, 层 2 永不该参与。

契约钉 (双向):
  1. _esp_backend_mode: builder=idf / flash.backend=esptool /
     capture.backend=uart 任一命中 → True; STM32 缺省配置 → False;
  2. ESP 运行: reset_target 不调, post_reset=="skipped";
  3. ESP 运行: 空捕获或含 HARDFAULT 字样均不拉层 2 (双向抑制——后者若真出现,
     跨读另一台 Cortex 的 live 寄存器比不诊断更危险);
  4. STM32 缺省行为不变 (空捕获 → 层 2 照调; flash ok → 复位照调);
  5. port/chip 白名单: port 注入 PowerShell 命令串 (run_idf), 只收
     COMn / /dev/ttyUSB* / /dev/ttyACM* / /dev/cu.*; chip 有限白名单
     (大小写归一); 校验不过不启动 run_idf。
  6. F-188/N-4: physical_gate 步骤入 _esp_backend_mode 闸 (I-1 同构
     第三处): ESP 三标记任一在场 + enable=true → 步骤不执行 (Popen 零
     调用), steps.physical_gate = {status: "skipped", reason: ...};
     STM32 配置 + enable=true → 原调用路径不变 (mock 调用断言)。
  7. F-188/N-3: 空捕获兜底文案按后端分流 (manifest/legacy 两处都钉) —
     ESP 提示含"串口"且不出现"HardFault"; STM32 原文案逐字节不变。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import esp_runtime  # noqa: E402
import hw_lease  # noqa: E402
import physical_gate  # noqa: E402
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


class EspModePredicateTests(unittest.TestCase):
    def test_default_is_not_esp(self):
        self.assertFalse(verify._esp_backend_mode(STM32_CONFIG))
        self.assertFalse(verify._esp_backend_mode({}))
        self.assertFalse(verify._esp_backend_mode(None))

    def test_each_marker_counts(self):
        for cfg in ({"builder": "idf"},
                    {"flash": {"backend": "esptool"}},
                    {"capture": {"backend": "uart"}},
                    ESP_CONFIG):
            self.assertTrue(verify._esp_backend_mode(cfg), cfg)


class _MainFlowHarness(unittest.TestCase):
    """驱动 main() 的 mock 风格与 test_verify_post_reset 同款 (F-164 教训:
    计时/睡眠类依赖一并隔离)"""

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
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run(self, config, capture_text="[init] OK"):
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(config, f)
        argv = ["verify.py", "--project", self.ws, "--json"]
        out, err = io.StringIO(), io.StringIO()
        reset_mock = mock.Mock(return_value={"status": "ok"})
        # 层 2 诊断桩: rc=1 (视为诊断失败但调用留痕可查), 防真实连硬件
        sp_run = mock.Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="mock no device"))
        cap_uart = mock.Mock(return_value={"status": "ok", "method": "uart",
                                           "_text": capture_text})
        cap_semi = mock.Mock(return_value=(capture_text, ""))
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": "s",
                                      "metrics": {"errors": 0, "warnings": 0},
                                      "details": {}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash",
                                  mock.Mock(return_value={
                                      "status": "ok", "stderr": "Verified",
                                      "stdout": ""})), \
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
                except SystemExit:
                    pass
        result = json.loads(out.getvalue())
        hf_calls = [c for c in sp_run.call_args_list
                    if len(c.args) and len(c.args[0]) > 1
                    and str(c.args[0][1]).endswith("hardfault.py")]
        return result, reset_mock, hf_calls


class PostResetGateTests(_MainFlowHarness):
    def test_esp_run_skips_reset(self):
        result, reset_mock, _ = self._run(ESP_CONFIG)
        reset_mock.assert_not_called()
        self.assertEqual(result["post_reset"], "skipped")

    def test_stm32_run_still_resets(self):
        result, reset_mock, hf = self._run(STM32_CONFIG)
        reset_mock.assert_called_once()
        self.assertEqual(result["post_reset"], "ok")


class HardfaultGateTests(_MainFlowHarness):
    def test_esp_empty_capture_no_layer2(self):
        result, _, hf_calls = self._run(ESP_CONFIG, capture_text="")
        self.assertEqual(hf_calls, [])
        self.assertNotIn("hardfault", result.get("steps", {}))

    def test_esp_hardfault_text_still_gated(self):
        # ESP 正文出现 HARDFAULT 字样 → 也不得拉 OpenOCD 层 2 (跨设备误读)
        result, _, hf_calls = self._run(
            ESP_CONFIG, capture_text="=== HARDFAULT === weird")
        self.assertEqual(hf_calls, [])

    def test_stm32_empty_capture_still_triggers_layer2(self):
        # 回归钉: 原 empty_fallback 行为不变
        result, _, hf_calls = self._run(STM32_CONFIG, capture_text="noise")
        self.assertEqual(hf_calls, [])  # 有输出无标记 → 本就不触发
        result, _, hf_calls = self._run(STM32_CONFIG, capture_text="")
        self.assertEqual(len(hf_calls), 1)


class PhysicalGateEspGateTests(_MainFlowHarness):
    """F-188/N-4: physical_gate 入 _esp_backend_mode 闸 (I-1 同构第三处)。

    双向钉: ① ESP 三标记任一在场 + enable=true → step_physical_gate 不
    执行 (Popen 零调用), steps.physical_gate = {status: "skipped",
    reason: ...}; ② STM32 配置 + enable=true → 原调用路径不变 (mock
    调用断言)。撤销实验: 拆闸 → ① 必红。"""

    def _run_with_popen_guard(self, config):
        with mock.patch.object(physical_gate.subprocess, "Popen") as popen:
            result, reset_mock, hf_calls = self._run(config)
        return result, popen

    def test_esp_run_skips_physical_gate(self):
        # F-190/T3 随动: 本类原用 capture_only/builder_only/flash_only 三种
        # 单标记混配夹具驱动主流程——GAP-F-19 裁定混配 = fail-fast 对象
        # (在 _prepare_context 即 exit 1, 夹具不再可达管线), 该保护面已由
        # test_esp_config_failfast.MixedConfigFailFastTests 钉死 (更强:
        # 任何动作之前退 1)。此处改用三键齐的合法 ESP 变体, 断言实质
        # (ESP 运行 + enable=true → Popen 零调用 + skipped+reason) 原样保留。
        esp_full = dict(ESP_CONFIG, physical_gate={"enable": True})
        esp_min = {"toolkit_min_version": "0.1",
                   "builder": "idf", "idf": {"build_timeout": 900},
                   "flash": {"backend": "esptool", "port": "COM9"},
                   "capture": {"backend": "uart", "port": "COM9",
                               "settle_sec": 0.0, "duration_sec": 15},
                   "physical_gate": {"enable": True}}
        esp_no_baud = {"toolkit_min_version": "0.1",
                       "builder": "idf",
                       "flash": {"backend": "esptool", "port": "COM5"},
                       "capture": {"backend": "uart", "port": "COM5",
                                   "duration_sec": 15},
                       "physical_gate": {"enable": True}}
        for cfg in (esp_full, esp_min, esp_no_baud):
            with self.subTest(cfg=cfg):
                result, popen = self._run_with_popen_guard(cfg)
                pg = result["steps"]["physical_gate"]
                self.assertEqual(pg["status"], "skipped", cfg)
                self.assertIn("ESP", pg["reason"], cfg)
                popen.assert_not_called()

    def test_stm32_run_keeps_physical_gate_call(self):
        cfg = dict(STM32_CONFIG, physical_gate={"enable": True})
        pg_mock = mock.Mock(return_value={"status": "skipped",
                                          "reason": "mock"})
        with mock.patch.object(verify, "step_physical_gate", pg_mock):
            result, _, _ = self._run(cfg)
        pg_mock.assert_called_once()
        args, kwargs = pg_mock.call_args
        self.assertEqual(args[0], {"enable": True})
        self.assertEqual(set(kwargs), {"timeout", "workspace"})
        self.assertEqual(result["steps"]["physical_gate"],
                         {"status": "skipped", "reason": "mock"})


class EmptyCaptureNoteTests(_MainFlowHarness):
    """F-188/N-3: 空捕获兜底提示语按后端分流 (manifest/legacy 两处都钉)。

    ESP: 提示含"串口"且不出现"HardFault"——HardFault 是 Cortex-M 概念,
    ESP 空捕获归因串口/波特率/复位窗 (F-174/I-1 口径); STM32: 原文案
    逐字节不变 (前缀等值断言)。"""

    NOTE_STM32 = "程序无输出（无 HardFault 迹象）: "

    def _desc(self, config, capture_text="", manifest=True):
        if not manifest:
            os.remove(os.path.join(self.ws, ".workbench",
                                   "expectations.json"))
        result, _, _ = self._run(config, capture_text=capture_text)
        return result["steps"]["verify"]["description"]

    def test_esp_manifest_note_points_to_uart(self):
        desc = self._desc(ESP_CONFIG, capture_text="")
        self.assertIn("串口", desc)
        self.assertIn("波特率", desc)
        self.assertIn("复位窗", desc)
        self.assertNotIn("HardFault", desc)

    def test_stm32_manifest_note_unchanged(self):
        desc = self._desc(STM32_CONFIG, capture_text="")
        self.assertTrue(desc.startswith(self.NOTE_STM32), desc)

    def test_esp_legacy_note_points_to_uart(self):
        desc = self._desc(ESP_CONFIG, capture_text="", manifest=False)
        self.assertIn("串口", desc)
        self.assertNotIn("HardFault", desc)

    def test_stm32_legacy_note_unchanged(self):
        desc = self._desc(STM32_CONFIG, capture_text="", manifest=False)
        self.assertTrue(desc.startswith(self.NOTE_STM32), desc)


class PortChipWhitelistTests(unittest.TestCase):
    def _flash(self, port):
        rec = mock.Mock(return_value={"status": "ok", "output": "done"})
        r = esp_runtime.step_flash_esptool(
            {"backend": "esptool", "port": port}, _run_idf=rec)
        return r, rec

    def test_flash_rejects_injection_forms(self):
        for bad in ("COM3; Invoke-Expression evil", 'COM3 "&x',
                    "COM 3", "-p evil", "COM3|out", "$(evil)"):
            r, rec = self._flash(bad)
            self.assertEqual(r["status"], "error", bad)
            self.assertIn("port", r["message"])
            rec.assert_not_called()

    def test_flash_accepts_canonical_ports(self):
        # 复审 N-2①: COM 大小写放宽 (esptool/pyserial 均收小写形态;
        # (?i:COM) 只放行字母大小写, 元字符禁令零损失, 实测 "com3"→接受)
        for ok in ("COM3", "com3", "CoM12", "COM128", "/dev/ttyUSB0",
                   "/dev/ttyACM5", "/dev/cu.usbmodem1401"):
            r, rec = self._flash(ok)
            self.assertEqual(r["status"], "ok", ok)
            self.assertIn(f"-p {ok}", rec.call_args[0][0][0])

    def test_capture_rejects_bad_chip_or_port(self):
        rec = mock.Mock(return_value={"status": "ok"})
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3", "chip": "esp999", "settle_sec": 0},
            _run_idf=rec)
        self.assertEqual(r["status"], "error")
        self.assertIn("chip", r["error"])
        rec.assert_not_called()
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3 && calc", "settle_sec": 0}, _run_idf=rec)
        self.assertEqual(r["status"], "error")
        rec.assert_not_called()

    def test_capture_default_chip_passes_validation(self):
        # 校验通过的证明: 复位桩给 error → 报"复位失败"而非白名单拒绝,
        # 且命令串带下划线复位集与默认 chip
        rec = mock.Mock(return_value={"status": "error",
                                      "message": "mock reset fail"})
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3", "settle_sec": 0}, _run_idf=rec)
        self.assertIn("复位失败", r["error"])
        cmd = rec.call_args[0][0][0]
        self.assertIn("--chip esp32s3", cmd)
        self.assertIn("hard_reset chip_id", cmd)

    def test_chip_case_normalized(self):
        rec = mock.Mock(return_value={"status": "error", "message": "x"})
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3", "chip": "ESP32-S3", "settle_sec": 0},
            _run_idf=rec)
        # esp32-s3 连字符形态 → 归一下划线后在白名单; 命令里保持归一值
        self.assertIn("复位失败", r["error"])
        self.assertIn("--chip esp32s3", rec.call_args[0][0][0])


class DocstringHygieneTests(unittest.TestCase):
    """I-2/minor: 文档-行为一致性钉 (09-15 平面同步教训的移植)"""

    def test_esp_runtime_no_dash_hard_reset_form(self):
        src = open(os.path.abspath(esp_runtime.__file__),
                   encoding="utf-8").read()
        # 钉"命令参数形态"而非字面全局: b678fca 注释里引 esptool 报错原文
        # ("invalid choice: 'hard-reset'") 是下划线决策的证据, 保留合法。
        self.assertNotIn("--after hard-reset", src)

    def test_rebuild_help_covers_idf(self):
        # verify.py --help 装配处直接 grep 源码 (main 内联 parser, 行为面靠
        # --rebuild 仅 gcc|idf 判据已钉于既有测试)
        src = open(os.path.abspath(verify.__file__),
                   encoding="utf-8").read()
        self.assertIn("--rebuild 仅支持 builder=gcc|idf", src)
        self.assertIn('help="编译前先 clean (builder=gcc|idf', src)


if __name__ == "__main__":
    unittest.main()
