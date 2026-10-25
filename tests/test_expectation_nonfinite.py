"""运行时数值断言的有限性回归。

配置侧 min/max 已拒绝 NaN, 但 capture_group 从固件输出提取的值也必须
是有限数。NaN 与任何边界比较均为 False, 旧实现因此恒 PASS。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import expectations  # noqa: E402


class NonFiniteCaptureValueTests(unittest.TestCase):
    def _evaluate(self, value, **bounds):
        item = {"id": "ADC", "patterns": [r"mv=(\S+)"],
                "capture_group": 1, **bounds}
        return expectations.evaluate_expectations(f"mv={value}\n", [item])

    def test_nan_capture_value_fails(self):
        ev = self._evaluate("nan", min=3000, max=3400)
        self.assertEqual(ev["verdict"], "fail")
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertIn("非有限", ev["results"][0]["detail"])

    def test_positive_infinity_fails_min_only(self):
        # 只有下限时 +inf 与 min 的比较为真, 旧实现因此恒 PASS。
        self.assertEqual(self._evaluate("inf", min=3000)["verdict"], "fail")

    def test_negative_infinity_fails_max_only(self):
        # 只有上限时 -inf 与 max 的比较为真, 旧实现因此恒 PASS。
        self.assertEqual(self._evaluate("-inf", max=3400)["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
