r"""F-152 (总工单 v2 T8/D-1) workflow YAML 回归钉 (可选依赖: pyyaml)。

验收: workflow 语法本地 yaml.safe_load 校验; hw-smoke.yml 的门控契约
(workflow_dispatch + vars.HW_RUNNER_READY == 'true') 钉死 — 仓库无真机
runner 时该 workflow 永不运行, 主 CI 不受影响。

pyyaml 不在 CI 依赖面 (各 job 零第三方安装) — 本测试在无 pyyaml 环境
自动 skip, 属"本地校验可重复"而非 CI 门禁。
"""
import os
import unittest

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(HAVE_YAML, "pyyaml not installed")
class WorkflowYamlTests(unittest.TestCase):

    def _load(self, name):
        with open(os.path.join(_ROOT, ".github", "workflows", name),
                  encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_ci_and_hw_smoke_parse(self):
        for name in ("ci.yml", "hw-smoke.yml"):
            data = self._load(name)
            self.assertIsInstance(data, dict, name)
            self.assertIn("jobs", data, name)

    def test_hw_smoke_gated_by_runner_variable(self):
        # 门控契约: 手动触发 + HW_RUNNER_READY == 'true' 才可能运行
        data = self._load("hw-smoke.yml")
        # YAML 1.1 把 `on:` 解析成布尔 True — 正好钉住这个坑
        self.assertIn(True, data, "`on:` 键必须存在 (yaml 解析为 True)")
        self.assertEqual(data[True].get("workflow_dispatch"), None)
        job = data["jobs"]["hw-smoke"]
        self.assertIn("vars.HW_RUNNER_READY == 'true'", job.get("if", ""))

    def test_ci_still_has_core_jobs(self):
        # 主 CI 不受 hw-smoke 新增影响: 原有 job 清单完整
        data = self._load("ci.yml")
        jobs = data["jobs"]
        for expected in ("unittest", "coverage-gate", "lint", "coverage-lint",
                         "syntax-smoke", "sim-demo"):
            self.assertIn(expected, jobs)


if __name__ == "__main__":
    unittest.main()
