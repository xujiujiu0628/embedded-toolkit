"""verify.py F-174 派发钉 — 新分支被正确路由 + 缺省路径回归 (builder/flash/capture 三处)。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime  # noqa: E402
import verify  # noqa: E402


class StepBuildDispatchTests(unittest.TestCase):
    def test_idf_routes_to_esp_runtime(self):
        with mock.patch.object(esp_runtime, "step_build_idf",
                               return_value={"status": "ok"}) as m:
            r = verify.step_build({"builder": "idf"}, builder="idf",
                                  rebuild=True)
        m.assert_called_once()                       # rebuild 旗标也放行到 idf (fullclean)
        self.assertEqual(r["status"], "ok")

    def test_gcc_default_untouched(self):
        # 缺省回归钉: gcc 路径仍走 run_py(GCC_BUILD)
        with mock.patch.object(verify, "run_py",
                               return_value={"status": "ok"}) as m:
            verify.step_build({"gcc": {"project": "p/Makefile"}}, builder="gcc")
        self.assertIn("gcc_build.py", m.call_args[0][0])

    def test_analyze_idf_passthrough_metrics(self):
        r = verify.step_analyze("x.log", builder="idf",
                                build_metrics={"errors": 0, "warnings": 3})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["summary"]["warnings"], 3)


if __name__ == "__main__":
    unittest.main()
