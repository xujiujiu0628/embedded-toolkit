"""F-235: 变异枪原语 —— 改一处 → 必须红 → 还原 → 必须绿。

R1 补充: 往返必须字节级无损。本工作区存在 CR-only 行尾的工程件
(`ch32v307-hello/Ld/Link.ld`), 读写不加 newline="" 会把整份文件换行改掉。
R2 补充: run_verify 抛异常时 finally 仍须还原 (异常照常上抛)。
R3 补充: find 不唯一时错误里要带实际出现次数。
"""
import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
