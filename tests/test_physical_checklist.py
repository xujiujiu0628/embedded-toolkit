"""F-250: 物理检查清单闸 — 判据、失效路径、放行口都要有钉。

这层闸的价值全在"什么时候拦住"：确认过就放、清单改了就不认、过期了要重来、
没配清单的工程不拦但要留痕。每一条都是会被人（或下一个我）绕过的口子。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import physical_checklist as pc  # noqa: E402
import verify  # noqa: E402


def _now():
    return datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)


class _Base(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.proj, ".workbench"))
        self.addCleanup(shutil.rmtree, self.proj, True)

    def write_checklist(self, items=None):
        payload = {"version": 1, "attest_ttl_hours": 12,
                   "items": items or [
                       {"id": "PWR-1", "cat": "供电", "text": "3V3 实测 3.3V"},
                       {"id": "I2C-1", "cat": "极性", "text": "SCL=PB8 / SDA=PB9",
                        "source": "User/MyI2C.c:16-19"}]}
        path = pc.checklist_path(self.proj)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path


class EvaluateTests(_Base):
    def test_not_configured_is_skipped_not_blocked(self):
        ev = pc.evaluate(self.proj, now=_now())
        self.assertEqual(ev["status"], "not_configured")
        step = pc.step_physical_checklist(self.proj, now=_now())
        self.assertEqual(step["status"], "skipped")
        self.assertIn(".workbench/physical-checklist.json", step["reason"])
        self.assertNotIn("\\", step["reason"])  # 金比对钉住: 不带平台分隔符

    def test_configured_without_attest_blocked(self):
        self.write_checklist()
        ev = pc.evaluate(self.proj, now=_now())
        self.assertEqual(ev["status"], "missing")
        step = pc.step_physical_checklist(self.proj, now=_now())
        self.assertEqual(step["status"], "blocked")
        self.assertEqual([i["id"] for i in step["items"]], ["PWR-1", "I2C-1"])

    def test_attested_ok_and_reports_items(self):
        self.write_checklist()
        pc.attest(self.proj, "板已按 FSD 接好", now=_now())
        step = pc.step_physical_checklist(self.proj, now=_now() + timedelta(hours=1))
        self.assertEqual(step["status"], "ok")
        self.assertEqual(step["items"], 2)
        self.assertEqual(step["by"], "user")
        json.dumps(step)  # 必须能进 verify 的 JSON 输出

    def test_checklist_edit_invalidates_attestation(self):
        path = self.write_checklist()
        pc.attest(self.proj, "接好", now=_now())
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["items"].append({"id": "KEY-1", "cat": "极性", "text": "PA0 按下为高"})
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.assertEqual(pc.evaluate(self.proj, now=_now())["status"], "changed")
        self.assertEqual(pc.step_physical_checklist(self.proj, now=_now())["status"],
                         "blocked")

    def test_reformatting_alone_does_not_invalidate(self):
        # 哈希按规范化 JSON 算: 只改缩进/键序不该让确认作废
        path = self.write_checklist()
        pc.attest(self.proj, "接好", now=_now())
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(dict(reversed(list(data.items()))), f, ensure_ascii=False)
        self.assertEqual(pc.evaluate(self.proj, now=_now())["status"], "ok")

    def test_expired_attestation_blocked(self):
        self.write_checklist()
        pc.attest(self.proj, "接好", now=_now())
        late = _now() + timedelta(hours=13)
        self.assertEqual(pc.evaluate(self.proj, now=late)["status"], "expired")
        self.assertEqual(pc.step_physical_checklist(self.proj, now=late)["status"],
                         "blocked")
        # 边界内仍放行
        self.assertEqual(pc.evaluate(self.proj, now=_now() + timedelta(hours=11))["status"], "ok")

    def test_attest_requires_note(self):
        self.write_checklist()
        with self.assertRaises(ValueError):
            pc.attest(self.proj, "   ")
        self.assertFalse(os.path.isfile(pc.attest_path(self.proj)))

    def test_attest_without_checklist_rejected(self):
        with self.assertRaises(ValueError):
            pc.attest(self.proj, "接好")

    def test_invalid_checklist_is_blocked(self):
        path = pc.checklist_path(self.proj)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f)
        self.assertEqual(pc.evaluate(self.proj, now=_now())["status"], "invalid")
        self.assertEqual(pc.step_physical_checklist(self.proj, now=_now())["status"],
                         "blocked")


class PassThroughTests(_Base):
    def test_skip_flag_is_recorded_not_silent(self):
        self.write_checklist()
        step = pc.step_physical_checklist(self.proj, skip=True, now=_now())
        self.assertEqual(step["status"], "skipped")
        self.assertTrue(step["skipped_by_flag"])
        self.assertIn("--skip-physical", step["reason"])

    def test_sim_backend_not_applicable(self):
        self.write_checklist()
        step = pc.step_physical_checklist(self.proj, hardware_expected=False, now=_now())
        self.assertEqual(step["status"], "skipped")
        self.assertIn("sim", step["reason"])

    def test_gate_never_raises(self):
        self.write_checklist()
        original = pc.evaluate
        pc.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            step = pc.step_physical_checklist(self.proj, now=_now())
        finally:
            pc.evaluate = original
        self.assertEqual(step["status"], "skipped")
        self.assertIn("boom", step["reason"])

    def test_scaffold_writes_generic_items_and_refuses_overwrite(self):
        path = pc.scaffold(self.proj)
        data = json.load(open(path, encoding="utf-8"))
        self.assertGreaterEqual(len(data["items"]), 4)
        self.assertTrue(all("cat" in i and "text" in i for i in data["items"]))
        with self.assertRaises(ValueError):
            pc.scaffold(self.proj)
        pc.scaffold(self.proj, force=True)  # 显式覆盖才允许


class VerifyWiringTests(unittest.TestCase):
    def test_cli_flag_defaults_off(self):
        args = verify._parse_args(["--project", "."])
        self.assertFalse(args.skip_physical)

    def test_cli_flag_parses(self):
        args = verify._parse_args(["--project", ".", "--skip-physical"])
        self.assertTrue(args.skip_physical)

    def test_pipeline_calls_gate_before_build(self):
        # 顺序钉: 闸必须在 _run_build_step 之前被调用 (否则先花构建时间)
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "verify.py"), encoding="utf-8").read()
        gate = src.index("step_physical_checklist(")
        build = src.index("_run_build_step(", src.index("def _run_pipeline"))
        self.assertLess(gate, build)


if __name__ == "__main__":
    unittest.main()
