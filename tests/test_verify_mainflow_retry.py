r"""verify.py 主流程编排集成测试补强 (F-088, WB-20260909-02)。

背景 (审计 WB-B6 / P1-12): P0-1 (F-085 台账漏参) 能潜伏的根因是 verify.py
主流程「build 成功线」零覆盖——所有 main() 用例都把 step_build mock 成
error 走早退。F-085 已补成功线 happy path (test_verify_main_success_path);
本文件扩面到**失败与重试分支**:

  S1 flash 重试耗尽 → status=flash_failed + last_failure.json 落盘
  S2 flash 第 N 次重试成功 → 重试后走通后续 (capture/verify 正常)
  S3 build 重试耗尽 → status=build_failed (对照 S1, build 侧重试链)
  S4 analyze 报 error (build ok 但有编译错误) → status=build_has_errors
  S5 rtt capture 失败 → status=capture_failed
  S6 HIL origin 守卫在 flash 步 (require-schedule-origin + manual) → exit 2

测试形态与 F-085 一致: 临时 workspace + mock 步骤函数 + 真实走 main(),
台账/失败现场断言针对真实落盘。scripts/ 零改动 (纯补测试)。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402

CAPTURED_TEXT = "=== boot ===\n[init] CLK OK\nADC raw=2000 mv=1600\n"
HEX_FILE = "build/firmware.hex"


def _slow(result, seconds=0.06):
    """注意: 不能用 time.sleep —— mock.patch("verify.time.sleep") 换的是
    全局 time 模块的 sleep (verify.time IS time), 会把本函数的 sleep 一起
    吞掉 → duration_sec 全 0 (F-088 施工实录)。这里用 time.perf_counter
    自旋等待, 不受 sleep mock 影响。"""
    def _call(*a, **k):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            pass
        return result
    return _call


class VerifyMainflowRetryTests(unittest.TestCase):
    """S1~S6: 失败/重试分支的真实编排断言"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(os.path.join(wb, "build"))
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({
                "toolkit_min_version": "0.1",
                "builder": "gcc",
                "gcc": {"project": "Makefile", "target": "main",
                        "log_dir": ".workbench/build"},
                "capture": {"backend": "rtt", "port": 19021,
                            "sram_base": "0x20000000", "sram_size": 2048,
                            "id": "SEGGER RTT", "boot_delay_ms": 300},
            }, f)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "启动横幅",
                 "texts": ["[init] CLK OK"]},
            ]}, f)
        # 产物文件真实存在 (step_flash 的 os.path.exists 前置检查)
        self.hex_path = os.path.join(self.ws, HEX_FILE.replace("/", os.sep))
        os.makedirs(os.path.dirname(self.hex_path), exist_ok=True)
        with open(self.hex_path, "w") as f:
            f.write(":00000001FF\n")
        self.state_path = os.path.join(self.ws, ".workbench", "state.json")
        self.jsonl = os.path.join(self.ws, ".workbench", "state",
                                  "checkpoints.jsonl")

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    # ---- 打桩工具 ----

    def _patch_common(self, flash_results, capture_side=None, analyze_error=False):
        """build/analyze 恒 ok; flash 按脚本逐次返回; capture 可注入结果"""
        build_result = {
            "status": "ok", "summary": "0 errors, 0 warnings",
            "metrics": {"errors": 0, "warnings": 0},
            "details": {"log_file": "build.log", "hex_file": HEX_FILE},
        }
        analyze_result = {
            "status": "ok",
            "summary": {"errors": 0, "warnings": 0, "matched": 0,
                        "unmatched": 0},
        }
        flash_iter = iter(flash_results)

        def _flash(*a, **k):
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 0.11:
                pass   # round(x,1) 后须 >0 (F-050); 不能用 sleep, 见 _slow 注释
            r = next(flash_iter)
            return r() if callable(r) else r
        # 注意: 不能写 _slow(_flash) —— _slow 的 result 参数会拿到函数对象
        # 本身, main() 里 flash.get 即 AttributeError (F-088 施工实录)。

        def _analyze_result(log_file, builder="gcc", build_metrics=None):
            # S4 需要 analyze 返回 error: 用 build_metrics.errors>0 触发真实
            # gcc 后端的 error 语义（避免 mock 掉被测编排分支——analyze 的
            # error 判定发生在 main() 内, 不在 step_analyze 内）
            if analyze_error:
                return {"status": "error",
                        "summary": {"errors": 1, "warnings": 0,
                                    "matched": 0, "unmatched": 1}}
            return {"status": "ok",
                    "summary": {"errors": 0, "warnings": 0,
                                "matched": 0, "unmatched": 0}}

        patchers = [
            mock.patch.object(verify, "step_build", _slow(build_result)),
            mock.patch.object(verify, "step_analyze", _analyze_result),
            mock.patch.object(verify, "step_flash", _flash),
            mock.patch("verify.time.sleep", lambda s: None),
        ]
        if capture_side is None:
            patchers.append(mock.patch.object(
                verify, "_step_capture_rtt",
                _slow({"status": "ok", "method": "rtt", "lines": 3,
                       "_text": CAPTURED_TEXT})))
        else:
            patchers.append(mock.patch.object(
                verify, "_step_capture_rtt",
                _slow(capture_side)))
        for p in patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patchers])

    def _run(self, extra_args=None):
        argv = ["verify.py", "--project", self.ws, "--json"] + (extra_args or [])
        buf, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv):
            with redirect_stdout(buf), redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    verify.main()
        return ctx.exception.code, buf.getvalue(), err.getvalue()

    def _state(self):
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    # ---- S1: flash 重试耗尽 ----

    def test_s1_flash_retries_exhausted_marks_flash_failed(self):
        self._patch_common([
            {"status": "error", "stderr": "swd connect fail"},
        ] * 10)  # 足够多的失败, 覆盖任意 max_retries 默认值
        code, out, err = self._run(["--retry", "2"])
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "flash_failed")
        self.assertEqual(result["steps"]["flash"]["retry_count"], 2)
        self.assertEqual(len(result["steps"]["flash"]["attempts"]), 3)
        # 失败现场落盘 (F-003/F-004 纪律)
        lf = os.path.join(self.ws, ".workbench", "build",
                          "last_failure.json")
        self.assertTrue(os.path.exists(lf), "flash 失败必须落 last_failure.json")
        # 早退路径落台账 (F-047 Finding 2)
        self.assertEqual(self._state()["last_checkpoint"]["status"],
                         "flash_failed")

    # ---- S2: flash 第 N 次重试成功 ----

    def test_s2_flash_succeeds_on_third_attempt(self):
        self._patch_common([
            {"status": "error", "stderr": "fail 1"},
            {"status": "error", "stderr": "fail 2"},
            {"status": "ok", "stderr": "** Verified OK **"},
            {"status": "error", "stderr": "unused"},
        ])
        # 默认 --retry 0 只尝试一次 → 必须显式给 2 次重试预算
        code, out, err = self._run(["--retry", "2"])
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["steps"]["flash"]["retry_count"], 2)
        self.assertEqual(result["steps"]["flash"]["attempts"][-1]["status"],
                         "ok")
        # 台账 ok 且 step_durations 含 flash (F-050/F-085 链路)
        with open(self.jsonl, encoding="utf-8") as f:
            entry = json.loads(f.readline())
        self.assertEqual(entry["status"], "ok")
        self.assertIn("flash", entry["step_durations"])

    # ---- S3: build 重试耗尽 ----

    def test_s3_build_failure_retry_exhausted(self):
        build_fail = {"status": "error", "summary": "2 errors",
                      "metrics": {"errors": 2, "warnings": 0},
                      "details": {"log_file": "build.log"}}
        with mock.patch.object(verify, "step_build", _slow(build_fail)), \
             mock.patch.object(verify, "step_analyze", _slow(
                 {"status": "error",
                  "summary": {"errors": 2, "warnings": 0,
                              "matched": 0, "unmatched": 0}})), \
             mock.patch("verify.time.sleep", lambda s: None):
            code, out, err = self._run(["--retry", "1"])
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "build_failed")
        self.assertEqual(result["steps"]["build"]["retry_count"], 1)
        self.assertEqual(self._state()["last_checkpoint"]["status"],
                         "build_failed")

    # ---- S4: build ok 但 analyze 有错 → **登记为不可达分支发现（不修复）** ----
    #
    # F-088 施工发现（超出原审计清单的新 finding）: analyze 恒 error 时
    # build_ok 永不置 True → 循环耗尽后走 build_failed 早退（verify.py:543-556），
    # **永远到不了** verify.py:583 的 build_has_errors 分支。可达性分析：
    #   - gcc 后端: step_analyze 的 gcc 分支由 build_metrics 驱动恒可返回
    #     error，但返回 error 只会让循环重试 → build_failed；
    #   - keil 桥: analyze=None（log_file 空且非 gcc）时 573 行兜底
    #     {"status":"error"} → 同样先撞 build_failed。
    # → build_has_errors 是**死分支**（gcc/keil 两后端均不可达）。
    # 按本任务禁线"发现新缺陷只登记不修复"处理，交维护者拍板：
    #   选项1 删除死分支；选项2 analyze error 时 break 出循环改判
    #   build_has_errors（保留区分"编译产物存在但有错"的语义）。
    def test_s4_analyze_error_falls_into_build_failed_not_has_errors(self):
        """S4(修订): analyze error → 重试耗尽 → build_failed。
        build_has_errors 分支当前不可达（见类 docstring F-088 发现登记）,
        本测试钉住**现实行为**, 修复死分支时翻转本测试。"""
        self._patch_common(
            [{"status": "ok", "stderr": "** Verified OK **"}],
            analyze_error=True)
        code, out, err = self._run(["--retry", "1"])
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "build_failed")
        self.assertEqual(self._state()["last_checkpoint"]["status"],
                         "build_failed")

    # ---- S5: rtt capture 失败 ----

    def test_s5_rtt_capture_failure_marks_capture_failed(self):
        self._patch_common(
            [{"status": "ok", "stderr": "** Verified OK **"}],
            capture_side={"status": "error",
                          "error": "OpenOCD 卡死 (F-003)"})
        code, out, err = self._run()
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "capture_failed")
        self.assertIn("卡死", result["error"])
        lf = os.path.join(self.ws, ".workbench", "build",
                          "last_failure.json")
        self.assertTrue(os.path.exists(lf))
        self.assertEqual(self._state()["last_checkpoint"]["status"],
                         "capture_failed")

    # ---- S6: HIL origin 守卫在 flash 步 (exit 2) ----

    def test_s6_require_schedule_origin_rejects_manual_at_flash(self):
        self._patch_common([{"status": "ok"}])
        code, out, err = self._run(
            ["--require-schedule-origin", "--task-origin", "manual"])
        self.assertEqual(code, 2)
        self.assertIn("schedule", err)


if __name__ == "__main__":
    unittest.main()
