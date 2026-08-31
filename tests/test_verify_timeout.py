# -*- coding: utf-8 -*-
"""F-016 回归: 采集窗超时可进契约 (2026-08-30 插板终判当日三轮空采实锤)。

优先级: CLI --timeout > config capture.duration_sec > 默认 10。
真人按键类期望需要更长的协商窗口, 10s 硬编码无法表达。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class ResolveCaptureTimeoutTests(unittest.TestCase):
    def test_cli_beats_contract(self):
        self.assertEqual(verify.resolve_capture_timeout(30, {"duration_sec": 90}), 30)

    def test_contract_used_when_cli_absent(self):
        self.assertEqual(verify.resolve_capture_timeout(None, {"duration_sec": 90}), 90)

    def test_default_10_when_nothing(self):
        self.assertEqual(verify.resolve_capture_timeout(None, {}), 10)
        self.assertEqual(verify.resolve_capture_timeout(None, None), 10)

    def test_invalid_contract_values_fall_back(self):
        for bad in (0, -5, "90", 1.5, True):
            self.assertEqual(verify.resolve_capture_timeout(None, {"duration_sec": bad}), 10,
                             msg="非法值应回落默认: %r" % (bad,))


if __name__ == "__main__":
    unittest.main()
