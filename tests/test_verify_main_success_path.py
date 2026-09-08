r"""verify.py 成功路径台账集成测试 (F-085) — 本仓首个驱动 main() 走通
"build 成功线" 的端到端用例 (WB-20260908-03)。

缺陷背景 (审计 WB-A1): verify.py 正常出口的 record_checkpoint(...) 只传 6 个
关键字参数, 漏 `gate_run` 与 `step_durations`; 早退路径两者都传。契约后果
(checkpoint_ledger.py:68-70 原文):
  - gate_run=True 应跳过 jsonl append、state.json 标 status="gate_skip" —
    漏传导致成功路径的门禁重跑照常写入台账, 污染 release audit 的
    "上次 PASS" 语义;
  - step_durations 不传则留空 dict — F-050 时长画像只收到失败样本。

测试形态: 临时 workspace + mock 四个步骤函数 (build/analyze/flash/capture,
各 sleep ~60ms 保证 duration_sec > 0), 真实走 main() 全流程 — 台账断言
针对真实 checkpoint_ledger 落盘, 不 mock 台账本身。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402

CAPTURED_TEXT = "=== adc-oled boot ===\n[init] CLK OK\nADC raw=3961 mv=3192\n"


def _slow_mock(result, seconds=0.06):
    """返回带真实耗时的步骤 mock — duration_sec = round(elapsed,1) 须 > 0"""
    def _call(*args, **kwargs):
        time.sleep(seconds)
        return result
    return _call


class VerifyMainSuccessPathTests(unittest.TestCase):
    """驱动 main() 走通 build 成功线, 断言台账双写契约"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({
                "toolkit_min_version": "0.1",
                "builder": "gcc",
                "gcc": {"project": "Makefile", "target": "main",
                        "log_dir": ".workbench/build"},
            }, f)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "启动横幅",
                 "texts": ["[init] CLK OK"]},
            ]}, f)
        self.jsonl = os.path.join(self.ws, ".workbench", "state",
                                  "checkpoints.jsonl")
        self.state_path = os.path.join(self.ws, ".workbench", "state.json")
        self._patch_steps()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _patch_steps(self):
        """四个步骤函数打桩: 全部 ok + 真实耗时 (时长画像需要 >0 样本)"""
        patchers = [
            mock.patch.object(
                verify, "step_build",
                _slow_mock({"status": "ok", "summary": "0 errors, 0 warnings",
                            "metrics": {"errors": 0, "warnings": 0},
                            "details": {"log_file": "build.log",
                                        "hex_file": "firmware.hex"}})),
            mock.patch.object(
                verify, "step_analyze",
                _slow_mock({"status": "ok",
                            "summary": {"errors": 0, "warnings": 0,
                                        "matched": 0, "unmatched": 0}})),
            mock.patch.object(
                verify, "step_flash",
                _slow_mock({"status": "ok", "stderr": "** Verified OK **",
                            "stdout": ""})),
            mock.patch.object(
                verify, "run_semihosting_session",
                _slow_mock((CAPTURED_TEXT, ""))),
        ]
        for p in patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patchers])

    def _run_main(self, extra_args):
        argv = ["verify.py", "--project", self.ws, "--json"] + extra_args
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv):
            with redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    verify.main()
        return ctx.exception.code, buf.getvalue()

    def _state(self):
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    def test_gate_run_success_skips_jsonl_and_marks_gate_skip(self):
        """验收 ②: --gate-run 成功运行 → jsonl 不追加、state 标 gate_skip"""
        code, stdout = self._run_main(
            ["--gate-run", "--task-origin", "schedule",
             "--require-schedule-origin"])
        self.assertEqual(code, 0, f"成功线未走通: {stdout[:600]}")
        result = json.loads(stdout)
        self.assertEqual(result["status"], "ok")
        # 修复前: gate_run 漏传 → 照常 append, 本断言红
        self.assertFalse(
            os.path.exists(self.jsonl),
            f"gate_run 成功运行不得写 checkpoints.jsonl, 实际存在: "
            f"{open(self.jsonl, encoding='utf-8').read()[:300] if os.path.exists(self.jsonl) else ''}")
        state = self._state()
        self.assertEqual(state["last_checkpoint"]["status"], "gate_skip",
                         f"state.json 应标 gate_skip, 实际: "
                         f"{state['last_checkpoint']['status']}")

    def test_normal_success_writes_step_durations(self):
        """验收 ③: 成功路径 step_durations 落台账 (非空, 键为实际 step)"""
        code, stdout = self._run_main([])
        self.assertEqual(code, 0, f"成功线未走通: {stdout[:600]}")
        # 修复前: step_durations 漏传 → 台账留空 dict, 本断言红
        with open(self.jsonl, encoding="utf-8") as f:
            entries = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["status"], "ok")
        self.assertTrue(
            entry.get("step_durations"),
            f"成功路径 step_durations 不得为空 (F-050 时长画像需要成功样本), "
            f"实际: {entry.get('step_durations')}")
        legal_steps = {"build", "analyze", "flash", "capture",
                       "physical_gate", "verify", "hardfault"}
        for key, value in entry["step_durations"].items():
            self.assertIn(key, legal_steps)
            self.assertGreater(value, 0)
        # state.json last_checkpoint 与 jsonl 末行同步
        state = self._state()
        self.assertEqual(state["last_checkpoint"]["status"], "ok")
        self.assertTrue(state["last_checkpoint"].get("step_durations"))

    def test_normal_success_appends_exactly_one_entry(self):
        """防重复: 同一 workspace 第二次运行应追加第二行 (append-only 语义)"""
        self._run_main([])
        self._run_main([])
        with open(self.jsonl, encoding="utf-8") as f:
            entries = [l for l in f if l.strip()]
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
