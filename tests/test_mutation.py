"""F-235: 变异枪原语 —— 改一处 → 必须红 → 还原 → 必须绿。

R1 补充: 往返必须字节级无损。本工作区存在 CR-only 行尾的工程件
(`ch32v307-hello/Ld/Link.ld`), 读写不加 newline="" 会把整份文件换行改掉。
R2 补充: run_verify 抛异常时 finally 仍须还原 (异常照常上抛)。
R3 补充: find 不唯一时错误里要带实际出现次数。

复审修正 (C/I): 真实 verify 信封的 per-id 行在 `steps.verify.results`
(verify.py:1464 → :1491), 不在顶层; legacy 工程压根没有 per-id 行, 必须
显式拒绝而不是报「未变红」。verify 自身崩 (status=error/internal_error/
interrupted) 也必须单独报, 不能伪装成负面结论。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import mutation  # noqa: E402


class MutationLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, ".workbench"))
        self.src = os.path.join(self.proj, "main.c")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write('printf("=== boot ===\\n");\n')

    def tearDown(self):
        self.tmp.cleanup()

    def _runner(self, red_ids, map_fn=None):
        calls = []

        def run_verify():
            with open(self.src, encoding="utf-8") as f:
                body = f.read()
            calls.append(body)
            ids = map_fn(body) if map_fn else red_ids
            return {"status": "fail" if ids else "ok",
                    "results": [{"id": i, "status": "fail"} for i in ids]}

        return run_verify, calls

    # 注: 替换串不能含 find 串 (brief 原样写的 "boot"→"bootX" 会让 boot 仍
    # 在文件里, 变异观察不到 —— 测试自身的缺陷, 已改为 "boot"→"MUT")。
    def test_bite_then_restore(self):
        run_verify, calls = self._runner(
            ["BOOT-01"], map_fn=lambda b: ["BOOT-01"] if "boot" not in b else [])
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertTrue(got["ok"], got)
        self.assertIn("boot", calls[-1])          # 已还原
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())

    def test_wrong_id_is_failure(self):
        run_verify, _ = self._runner(["OTHER-01"])
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertFalse(got["ok"])
        self.assertIn("BOOT-01", got["error"])

    def test_restore_failure_still_reports(self):
        run_verify, _ = self._runner([])          # 变异没咬住
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertFalse(got["ok"])
        self.assertIn("未变红", got["error"])
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())       # 仍然还原


class MutationStrictnessTests(unittest.TestCase):
    """R3: find 出现次数不为 1 时拒绝执行, 错误带实际次数。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.src = os.path.join(self.proj, "main.c")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("boot boot\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _no_call(self):
        def run_verify():
            raise AssertionError("find 不唯一时不应跑 verify")
        return run_verify

    def test_duplicate_find_rejected_with_count(self):
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "bootX", self._no_call(), 5)
        self.assertFalse(got["ok"])
        self.assertIn("2", got["error"])
        with open(self.src, encoding="utf-8") as f:
            self.assertEqual(f.read(), "boot boot\n")

    def test_missing_find_rejected_with_count(self):
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "led", "ledX", self._no_call(), 5)
        self.assertFalse(got["ok"])
        self.assertIn("0", got["error"])

    def test_missing_file_rejected(self):
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "nope.c",
                                      "boot", "bootX", self._no_call(), 5)
        self.assertFalse(got["ok"])
        self.assertIn("不存在", got["error"])


class MutationNewlineTests(unittest.TestCase):
    """R1/R2: 往返字节无损 —— CRLF / CR 两种行尾, 成功与异常两条退出。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write_bytes(self, raw):
        path = os.path.join(self.proj, "main.c")
        with open(path, "wb") as f:
            f.write(raw)
        return path

    def _read_bytes(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_crlf_success_path_is_byte_exact(self):
        raw = b'printf("boot");\r\nint x = 1;\r\n'
        path = self._write_bytes(raw)
        seen = []

        def run_verify():
            seen.append(self._read_bytes(path))
            red = b"boot" not in seen[-1]
            return {"status": "fail" if red else "ok",
                    "results": [{"id": "BOOT-01", "status": "fail"}] if red else []}

        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertTrue(got["ok"], got)
        self.assertIn(b"MUT", seen[0])                    # 变异真的落盘过
        self.assertEqual(self._read_bytes(path), raw)     # 字节级还原

    def test_cr_only_failed_bite_is_byte_exact(self):
        raw = b'line1\rline2 boot\r'
        path = self._write_bytes(raw)

        def run_verify():
            return {"status": "ok", "results": []}         # 没咬住

        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "bootX", run_verify, 5)
        self.assertFalse(got["ok"])
        self.assertIn("未变红", got["error"])
        self.assertEqual(self._read_bytes(path), raw)

    def test_exception_path_still_restores_bytes(self):
        raw = b'a\r\nb boot\r\nc\r'
        path = self._write_bytes(raw)

        def run_verify():
            raise RuntimeError("verify 崩了")

        with self.assertRaises(RuntimeError):
            mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                    "boot", "bootX", run_verify, 5)
        self.assertEqual(self._read_bytes(path), raw)


class MutationEnvelopeTests(unittest.TestCase):
    """真实 verify 信封: per-id 结果行在 steps.verify.results, 不在顶层。

    顶层 results 只存在于注入式 runner (单测/外部调用方), 两种形状都要认。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.src = os.path.join(self.proj, "main.c")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write('printf("=== boot ===\\n");\n')

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, status, rows):
        """真实 verify.py --json 的 per-id 信封形状 (steps.verify.results)。"""
        return {"status": status,
                "steps": {"verify": {"status": status, "results": rows}}}

    def _no_call(self):
        def run_verify():
            raise AssertionError("不应跑到 verify")
        return run_verify

    def test_manifest_envelope_bite_detected(self):
        seen = []

        def run_verify():
            with open(self.src, encoding="utf-8") as f:
                body = f.read()
            seen.append(body)
            red = "boot" not in body
            return self._manifest(
                "fail" if red else "ok",
                [{"id": "BOOT-01", "status": "fail" if red else "pass"}])

        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertTrue(got["ok"], got)           # 顶层无 results 也要认得出
        self.assertEqual(len(seen), 2)            # 红跑 + 绿跑
        self.assertIn("boot", seen[-1])           # 绿跑时已还原

    def test_legacy_envelope_refused_explicitly(self):
        # legacy expect/expect_patterns 工程: 只有 matched/missing, 无 per-id 行
        legacy = {"status": "fail",
                  "steps": {"verify": {"status": "fail", "matched": [],
                                       "missing": ["boot"],
                                       "missing_patterns": [],
                                       "description": "legacy"}}}
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", lambda: legacy, 5)
        self.assertFalse(got["ok"])
        self.assertNotIn("未变红", got["error"])   # 不能伪装成负面结论
        self.assertIn("没有 id 级断言", got["error"])
        self.assertIn("BOOT-01", got["error"])
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())        # 仍须还原

    def test_early_fail_envelope_names_actual_status(self):
        # F-235 SHOULD-FIX: 构建/烧录/HardFault/物理门控失败时 verify 提前
        # 退出, steps.verify 压根不存在 —— 报「没有 id 级断言」会把运维引去
        # 查一个不存在的配置问题。必须点名实际 status 并带 error 原文。
        env = {"status": "build_failed", "error": "make: *** [all] Error 2"}
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", lambda: env, 5)
        self.assertFalse(got["ok"])
        self.assertIn("build_failed", got["error"])
        self.assertIn("make: ***", got["error"])       # 原文可引
        self.assertNotIn("没有 id 级断言", got["error"])
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())            # 仍须还原

    def test_xpass_counts_as_red(self):
        # F-235 SHOULD-FIX: xfail 条目意外通过 (xpass) 在四态判定里是严格
        # 红, verdict 同样不 ok; 只收 "fail" 会对 xfail 条目误报「未变红」。
        calls = []

        def run_verify():
            calls.append(1)
            if len(calls) == 1:
                return self._manifest("fail",
                                      [{"id": "BOOT-01", "status": "xpass"}])
            return self._manifest("ok", [])

        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", run_verify, 5)
        self.assertTrue(got["ok"], got)

    def test_verify_crash_on_red_run_is_reported_as_crash(self):
        crash = {"status": "internal_error", "steps": {},
                 "error": "Traceback ...\nKeyError: 'firmware'"}
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", lambda: crash, 5)
        self.assertFalse(got["ok"])
        self.assertNotIn("未变红", got["error"])   # 不是「没红」, 是「没判成」
        self.assertIn("verify 自身失败", got["error"])
        self.assertIn("KeyError", got["error"])    # 原文可引
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())

    def test_verify_crash_on_green_run_is_reported(self):
        def run_verify():
            return self._manifest("fail", [{"id": "BOOT-01", "status": "fail"}])

        def run_verify_second():
            # 第一次红跑正常, 第二次 (还原后) verify 自身崩
            return {"status": "error", "error": "ImportError: no pyserial",
                    "steps": {}}

        calls = []

        def dispatch():
            calls.append(1)
            return (run_verify() if len(calls) == 1
                    else run_verify_second())

        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "boot", "MUT", dispatch, 5)
        self.assertFalse(got["ok"])
        self.assertIn("verify 自身失败", got["error"])
        self.assertIn("ImportError: no pyserial", got["error"])
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("boot", f.read())

    def test_empty_find_rejected(self):
        with open(self.src, "rb") as f:
            before = f.read()
        got = mutation.mutate_and_run(self.proj, "BOOT-01", "main.c",
                                      "", "X", self._no_call(), 5)
        self.assertFalse(got["ok"])
        self.assertIn("为空", got["error"])
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), before)


class _FakeSubprocess:
    """subprocess 模块引用替换件 (F-184/GAP-F-9 形态: 桩落在 mutation 命名空间,
    不动全局 subprocess —— 全局打桩被 test_stub_ratchet 判违规)。"""

    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.proc


class RunVerifyCliTests(unittest.TestCase):
    """_run_verify_cli: verify.py 非 JSON 退出时须保留 stderr 尾巴与退出码。"""

    def test_non_json_stdout_keeps_stderr_tail(self):
        fake = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="",
            stderr="Traceback (most recent call last):\nKeyError: 'x'\n")
        stub = _FakeSubprocess(fake)
        with mock.patch.object(mutation, "subprocess", stub):
            got = mutation._run_verify_cli("proj", 5)()
        self.assertEqual(got["status"], "error")
        self.assertEqual(got["results"], [])
        self.assertIn("KeyError", got["error"])
        self.assertIn("2", got["error"])          # 退出码可查
        self.assertEqual(len(stub.calls), 1)      # 调用确实走到桩上


if __name__ == "__main__":
    unittest.main()
