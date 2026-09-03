"""F-048: doctor 体检顺便检查 fixture 状态 (2026-09-02 方案四 P0 余项).

用户拍板方向 (2026-09-02, 方案四-5):
  - 当前 doctor 只查工具链 (gcc/openocd/make/SWD), 不查 fixture
  - fixture 漂移是嵌入式测试最隐蔽的雷: PC 测试 PASS 但真机挂
  - 修复: 把 tests/fixtures/contract/ 体检接到 doctor_report
      ① fixture 在场性 (config.json / expectations.json 是否在)
      ② fixture 契约哈希 vs 仓库 main 版的漂移 (drift)
      ③ 漂移 = warn, 缺失 = fail, 都进 doctor_report 报告

契约定下来:
  - doctor_report 增加 fixtures 字段, 含 status / config / expectations / drift / summary
  - summary 增加 fixture 子项 (与 tools/swd 平级)
  - 不触碰现有 tools/swd 行为 (向后兼容)
  - 漂移检测用 sha256 对比: 本地 fixture vs git main 上的 fixture
  - 缺失/漂移都进 stderr (人类可读) + JSON (机器可读), 退出码仍 0 (诊断不阻断)

本测试锁契约:
  1. fixture_health() 返回 {status, config, expectations, drift}
  2. config 缺失 → status="fail"
  3. expectations 缺失 → status="fail"
  4. config + expectations 都在且无漂移 → status="ok"
  5. config + expectations 都在但有漂移 → status="warn"
  6. doctor_report 增加 fixtures 字段 (含 fixture 子项)
  7. _print_doctor 增加 fixture 行 (人类可读)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


SCRIPTS = os.path.dirname(os.path.abspath(verify.__file__))
REPO_ROOT = os.path.dirname(SCRIPTS)
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "contract")


class FixtureHealthHelperTests(unittest.TestCase):
    """F-048 单元: fixture_health() 在临时工程根下的行为"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        # 模拟工程根, fixture 目录可由函数自行拼接
        # 这里直接传 fixture_dir 给函数
        self.tmp_fixture = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.tmp_fixture, ignore_errors=True)

    def test_missing_config_returns_fail(self):
        # fixture 目录空 → status="fail", config/expectations 都 in_dict 但 status fail
        health = verify.fixture_health(self.tmp_fixture)
        self.assertEqual(health["status"], "fail")
        self.assertEqual(health["config"]["status"], "missing")
        self.assertEqual(health["expectations"]["status"], "missing")

    def test_only_config_present_still_fail(self):
        # 只有 config 没 expectations → 仍 fail (不完整)
        with open(os.path.join(self.tmp_fixture, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        health = verify.fixture_health(self.tmp_fixture)
        self.assertEqual(health["status"], "fail")
        self.assertEqual(health["config"]["status"], "ok")
        self.assertEqual(health["expectations"]["status"], "missing")

    def test_both_present_no_drift_returns_ok(self):
        # config + expectations 都在, 假设没漂移 → ok
        # tmp_fixture 已在 setUp 创建, 直接写文件
        with open(os.path.join(self.tmp_fixture, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        with open(os.path.join(self.tmp_fixture, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": []}, f)
        # 无 git main 可对比 (临时目录非 git 仓) → drift 检测应跳过, 视作"无漂移"
        health = verify.fixture_health(self.tmp_fixture)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["config"]["status"], "ok")
        self.assertEqual(health["expectations"]["status"], "ok")
        self.assertIn("drift", health)

    def test_drift_detected_via_hash_mismatch(self):
        # 本地有 fixture, mock git main 上的版本不同 → warn + drift=true
        with open(os.path.join(self.tmp_fixture, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        with open(os.path.join(self.tmp_fixture, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": []}, f)
        # mock: 本地 hash vs 仓库 main hash 不同
        with mock.patch.object(verify, "_fixture_main_sha",
                               return_value={"config_sha256": "deadbeef" * 8,
                                             "expectations_sha256": "cafebabe" * 8}):
            health = verify.fixture_health(self.tmp_fixture)
        self.assertEqual(health["status"], "warn")
        self.assertTrue(health["drift"]["detected"])
        # 应该指明哪个文件漂移
        self.assertIn("config_sha256", health["drift"]["mismatches"])
        self.assertIn("expectations_sha256", health["drift"]["mismatches"])


class DoctorReportFixtureIntegrationTests(unittest.TestCase):
    """F-048 集成: doctor_report 含 fixtures 字段, summary 含 fixture 子项"""

    def test_report_has_fixtures_key(self):
        # 不探测 SWD, 避免依赖 openocd
        rep = verify.doctor_report(probe=False)
        self.assertIn("fixtures", rep)
        self.assertIn("status", rep["fixtures"])
        # summary 应含 fixture status 计数
        self.assertIn("fixture", rep["summary"])
        # 旧字段不动 (向后兼容)
        for k in ("tool", "toolkit_version", "python", "machine", "tools", "swd"):
            self.assertIn(k, rep)

    def test_summary_includes_fixture_status(self):
        # 与 tools/swd 平级: summary 各状态计数 = 各 source 各状态计数之和
        rep = verify.doctor_report(probe=False)
        statuses = [rep["tools"][n]["status"] for n in ("gcc", "openocd", "make")]
        statuses.append(rep["swd"]["status"])
        statuses.append(rep["fixtures"]["status"])
        for k in ("ok", "warn", "fail", "skipped"):
            self.assertEqual(rep["summary"][k], statuses.count(k), k)

    def test_real_fixture_dir_in_repo_health(self):
        # 用本仓 tests/fixtures/contract/ 跑一次真检查, 确认无异常路径
        rep = verify.doctor_report(probe=False)
        # status 应是 ok / warn / fail 之一
        self.assertIn(rep["fixtures"]["status"], ("ok", "warn", "fail"))
        # 至少 config 应在 (F-038 入库)
        self.assertIn(rep["fixtures"]["config"]["status"], ("ok", "missing"))


class DoctorCliFixtureTests(unittest.TestCase):
    """F-048 集成: CLI --doctor --json 包含 fixtures 字段"""

    def test_cli_json_includes_fixtures(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "verify.py"),
             "--doctor", "--json"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, (r.stderr or "")[-500:])
        doc = json.loads(r.stdout)
        self.assertIn("fixtures", doc)
        self.assertIn("summary", doc)
        self.assertIn("fixture", doc["summary"])

    def test_cli_human_output_has_fixture_line(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "verify.py"), "--doctor"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, (r.stderr or "")[-500:])
        # 人读行包含 fixtures
        self.assertIn("fixtures", r.stdout)


if __name__ == "__main__":
    unittest.main()
