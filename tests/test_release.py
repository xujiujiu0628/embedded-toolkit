import contextlib
import io
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

import release  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

        def git(*a):
            subprocess.run(["git"] + GIT_ID + list(a), cwd=self.ws,
                           capture_output=True, timeout=30, check=True)
        git("init", "-q")
        # annotated tag 需要 tagger 身份; 本机无全局身份, 显式配 repo 级
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("x")
        git("add", "-A")
        git("commit", "-qm", "init")
        self.git = git

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_g0_dirty_tree_fails(self):
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("y")
        errs = release.g0_checks(self.ws, "v9.9.9")
        self.assertTrue(any("不干净" in e for e in errs))

    def test_g0_existing_tag_fails(self):
        self.git("tag", "v1.0.0")
        errs = release.g0_checks(self.ws, "v1.0.0")
        self.assertTrue(any("已存在" in e for e in errs))

    def test_g0_same_head_record_rejected(self):
        # 审计 L5: 同 HEAD 既有记录的拒绝键此前无测试
        _, head, _ = release._git(["rev-parse", "HEAD"], self.ws)
        rec_dir = os.path.join(self.ws, ".workbench", "releases")
        os.makedirs(rec_dir, exist_ok=True)
        with open(os.path.join(rec_dir, "v2.0.0.json"), "w") as f:
            json.dump({"tag": "v2.0.0", "git_head": head}, f)
        errs = release.g0_checks(self.ws, "v2.0.0")
        self.assertTrue(any("同 HEAD" in e for e in errs))

    def test_finalize_rolls_back_on_tag_failure(self):
        # 审计 L5: spec §10 点名的 tag 创建失败回滚路径
        _, head, _ = release._git(["rev-parse", "HEAD"], self.ws)
        rec = {"tag": "v1.0.0", "git_head": head, "branch": "master"}
        real_run = release.subprocess.run

        def fake_run(cmd, *a, **k):
            if cmd[:3] == ["git", "tag", "-a"]:
                return subprocess.CompletedProcess(cmd, 128, "", "mock tag failure")
            return real_run(cmd, *a, **k)

        with mock.patch.object(release.subprocess, "run", side_effect=fake_run):
            self.assertFalse(release.finalize(self.ws, "v1.0.0", rec))
        self.assertFalse(os.path.exists(os.path.join(
            self.ws, ".workbench", "releases", "v1.0.0.json")))

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_blocks_unflipped_xfail(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok",
            "evidence": "hardware_validated",   # F-128: 证据门与 xfail 门独立
            "steps": {"verify": {"results": [
                {"id": "FR-A", "status": "pass"},
                {"id": "FR-B", "status": "xfail"},
            ]}},
        }
        ok, msg, _ = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                       timeout=10, openocd_exe="openocd")
        self.assertFalse(ok)
        self.assertIn("FR-B", msg)

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_allow_xfail_waives(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok",
            "evidence": "hardware_validated",
            "steps": {"verify": {"results": [{"id": "FR-B", "status": "xfail"}]}},
        }
        ok, _, ctx = release.run_gates(self.ws, "v1.0.0", allow_xfail=True,
                                       timeout=10, openocd_exe="openocd")
        self.assertTrue(ok)
        self.assertEqual(ctx["waived"], ["FR-B"])
        self.assertEqual(ctx["evidence"], "hardware_validated")
        self.assertFalse(ctx["evidence_waiver"])

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_blocks_sim_evidence(self, m_gate1, _probe):
        # F-128 (工单二 A-1): 仿真证据永不升级为发布证据
        m_gate1.return_value = {
            "status": "ok", "evidence": "simulation_validated",
            "steps": {"verify": {"results": [{"id": "FR-A", "status": "pass"}]}},
        }
        ok, msg, _ = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                       timeout=10, openocd_exe="openocd")
        self.assertFalse(ok)
        self.assertIn("simulation_validated", msg)
        self.assertIn("hardware_validated", msg)

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_blocks_missing_evidence_as_static(self, m_gate1, _probe):
        # 旧版 verify 无 evidence 键 → 按 static 拦 (升 toolkit 后重发)
        m_gate1.return_value = {
            "status": "ok",
            "steps": {"verify": {"results": [{"id": "FR-A", "status": "pass"}]}},
        }
        ok, msg, _ = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                       timeout=10, openocd_exe="openocd")
        self.assertFalse(ok)
        self.assertIn("static", msg)

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_non_hw_evidence_requires_explicit_flag(self, m_gate1, _probe):
        # 新旗标显式豁免: 放行但 evidence_waiver 留痕 (审计 R8 可见)
        m_gate1.return_value = {
            "status": "ok", "evidence": "simulation_validated",
            "steps": {"verify": {"results": [{"id": "FR-A", "status": "pass"}]}},
        }
        ok, _, ctx = release.run_gates(
            self.ws, "v1.0.0", allow_xfail=False, timeout=10,
            openocd_exe="openocd", allow_non_hw_evidence=True)
        self.assertTrue(ok)
        self.assertEqual(ctx["evidence"], "simulation_validated")
        self.assertTrue(ctx["evidence_waiver"])

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_real_hw_evidence_passes(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok", "evidence": "hardware_validated",
            "steps": {"verify": {"results": [{"id": "FR-A", "status": "pass"}]}},
        }
        ok, _, ctx = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                       timeout=10, openocd_exe="openocd")
        self.assertTrue(ok)
        self.assertEqual(ctx["evidence"], "hardware_validated")
        self.assertFalse(ctx["evidence_waiver"])

    def test_gate1_passes_f046_origin_flags(self):
        # F-046 触发链补完: G1 重跑 verify 时必须传 task-origin=schedule
        # + --require-schedule-origin, 防止有人绕过发布门禁走 manual 通道
        # 或改回 --task-origin=manual 破防 schedule 通道承诺
        import release
        with mock.patch.object(release.subprocess, "run") as m_run:
            m_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"status":"ok"}', stderr="")
            release.gate1(self.ws, timeout=10)
        # gate1 走 subprocess.run 的第一次调用就是 verify 调用
        self.assertTrue(m_run.called, "gate1 应至少调用一次 subprocess.run")
        cmd = m_run.call_args[0][0]
        # 必须包含 F-046 的两个旗标, 且值必须是 schedule
        self.assertIn("--task-origin", cmd, "F-046: 缺 --task-origin 旗标")
        i = cmd.index("--task-origin")
        self.assertEqual(cmd[i + 1], "schedule",
                         f"F-046: task-origin 必须是 schedule, 实际 {cmd[i+1]!r}")
        self.assertIn("--require-schedule-origin", cmd,
                      "F-046: 缺 --require-schedule-origin 硬卡旗标")

    def test_finalize_success_tags_and_keeps_record(self):
        _, head, _ = release._git(["rev-parse", "HEAD"], self.ws)
        rec = {"tag": "v1.0.0", "git_head": head, "branch": "master"}
        self.assertTrue(release.finalize(self.ws, "v1.0.0", rec))
        _, out, _ = release._git(["tag", "-l", "v1.0.0"], self.ws)
        self.assertEqual(out, "v1.0.0")
        self.assertTrue(os.path.exists(os.path.join(
            self.ws, ".workbench", "releases", "v1.0.0.json")))

    def test_finalize_rolls_back_on_head_change(self):
        rec = {"tag": "v1.0.0", "git_head": "deadbeef", "branch": "master"}
        self.assertFalse(release.finalize(self.ws, "v1.0.0", rec))
        self.assertFalse(os.path.exists(os.path.join(
            self.ws, ".workbench", "releases", "v1.0.0.json")))

    def test_build_record_carries_contract_hashes(self):
        # F-018: 判绿锚点 — G1 verify 的 contract_hashes 必须抄进发布记录
        _, head, _ = release._git(["rev-parse", "HEAD"], self.ws)
        rec = release.build_record(
            self.ws, "v2.0.0", [{"id": "A", "status": "pass"}], [],
            contracts={"expectations_sha256": "ab" * 32,
                       "config_sha256": "cd" * 32})
        self.assertEqual(rec["git_head"], head)
        self.assertEqual(rec["build_mode"], "clean_rebuild")
        self.assertEqual(rec["contracts"], {"expectations_sha256": "ab" * 32,
                                            "config_sha256": "cd" * 32})

    def test_build_record_without_contracts_stays_empty(self):
        # 旧版 verify 无 contract_hashes 键 → 空字典, R7 走警告路径
        rec = release.build_record(self.ws, "v2.0.0", [], [])
        self.assertEqual(rec["contracts"], {})

    def test_build_record_carries_evidence(self):
        # F-128: G1 verify 的 evidence 透传进发布记录; 无豁免时不留痕
        rec = release.build_record(
            self.ws, "v2.0.0", [{"id": "A", "status": "pass"}], [],
            evidence="hardware_validated")
        self.assertEqual(rec["evidence"], "hardware_validated")
        self.assertNotIn("evidence_waiver", rec)

    def test_build_record_evidence_waiver_leaves_trace(self):
        # 豁免留痕: evidence_waiver=True 仅在显式旗标下出现, R8 据此降级警告
        rec = release.build_record(
            self.ws, "v2.0.0", [{"id": "A", "status": "pass"}], [],
            evidence="simulation_validated", evidence_waiver=True)
        self.assertEqual(rec["evidence"], "simulation_validated")
        self.assertTrue(rec["evidence_waiver"])

    def test_build_record_default_evidence_static(self):
        # 缺省 (旧调用方) 落 static — 与 R8 的"宁低勿高"口径一致
        rec = release.build_record(self.ws, "v2.0.0", [], [])
        self.assertEqual(rec["evidence"], "static")

    def test_build_record_carries_fidelity_contract(self):
        # F-146: 发布记录自带 fidelity 契约 — 边界声明按证据等级落档,
        # limitations 缺省不虚报 (空列表), signature 留空占位
        rec = release.build_record(self.ws, "v2.0.0", [], [],
                                   evidence="hardware_validated")
        self.assertEqual(
            rec["fidelity_boundaries"],
            ["真机 capture 输出匹配判定; 不构成产品级/认证级/长期可靠性声明"])
        self.assertEqual(rec["limitations"], [])
        self.assertEqual(rec["signature"], "")

    def test_build_record_fidelity_sim_boundary_and_custom(self):
        # 仿真证据的边界声明必须写明"不升级为硬件等价"; 显式传入胜出
        rec = release.build_record(self.ws, "v2.0.0", [], [],
                                   evidence="simulation_validated")
        self.assertIn("不升级为硬件等价声明", rec["fidelity_boundaries"][0])
        rec2 = release.build_record(self.ws, "v2.0.0", [], [],
                                    fidelity_boundaries=["自定义边界"],
                                    limitations=["单板单次采样"])
        self.assertEqual(rec2["fidelity_boundaries"], ["自定义边界"])
        self.assertEqual(rec2["limitations"], ["单板单次采样"])

    # ── F-190/P-1 (WB-20260926-03 T3): main() 对 machine.json
    #    openocd_exe 键的读取面双向钉 ──
    # 病灶: main() 无条件 load_machine()["openocd_exe"] — 纯 ESP 机器缺键
    # 裸 KeyError (G0.5 已入后端闸但键读取未分流, 01 报告 §八-1)。
    # 修法: ESP 模式不读该键; STM32 模式缺键 → 友好 ERROR (点名键名) +
    # exit 1。不真发布、不触真机 (gate1 mock / --dry-run / swd_probe boom)。

    def _write_config(self, cfg):
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb, exist_ok=True)
        with open(os.path.join(wb, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(cfg, f)

    def _write_state_with_artifacts(self):
        """state.json + 真实产物文件 — build_record 过 hex 哈希门所需。"""
        build = os.path.join(self.ws, "build")
        os.makedirs(build, exist_ok=True)
        for name in ("fw.bin", "fw.elf"):
            with open(os.path.join(build, name), "wb") as f:
                f.write(b"\x00FW")
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb, exist_ok=True)
        with open(os.path.join(wb, "state.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"last_build": {"artifacts": {
                "hex_file": "build/fw.bin", "elf_file": "build/fw.elf"}}}, f)

    @mock.patch.object(release, "swd_probe",
                       side_effect=AssertionError(
                           "ESP 模式不得触 swd_probe (F-190/M-1 闸)"))
    @mock.patch.object(release, "gate1")
    @mock.patch.object(release, "load_machine", return_value={})
    def test_esp_mode_missing_openocd_key_does_not_crash(
            self, _m_machine, m_gate1, _m_probe):
        """双向钉·ESP 面: machine 无 openocd_exe 键 → 不在读键面裸崩,
        流程走通到 G0.5 skipped 痕 (dry-run rc=0)。"""
        self._write_config({"builder": "idf"})
        self._write_state_with_artifacts()
        # G0 要求干净树 — 钉夹具 (config/state/build) 先行入库
        self.git("add", "-A")
        self.git("commit", "-qm", "artifacts")
        m_gate1.return_value = {"status": "ok",
                                "steps": {"verify": {"results": []}},
                                "evidence": "hardware_validated",
                                "contract_hashes": {}}
        buf = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["release.py", "--tag", "v9.9.9",
                                "--project", self.ws, "--dry-run"]), \
                contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                release.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("g0_5=skipped", buf.getvalue())

    @mock.patch.object(release, "load_machine", return_value={})
    def test_stm32_mode_missing_openocd_key_friendly_error(self, _m_machine):
        """双向钉·STM32 面: 缺键 → 友好 ERROR (文案点名 machine.json 键名
        openocd_exe) + exit 1, 不再裸 KeyError traceback。"""
        self._write_config({})   # 非 ESP → STM32 缺省语义
        err = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["release.py", "--tag", "v9.9.9",
                                "--project", self.ws]), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                release.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("openocd_exe", err.getvalue())

    @mock.patch.object(release, "run_gates",
                       return_value=(False, "G0 失败:\n  x", {}))
    @mock.patch.object(release, "load_machine",
                       return_value={"openocd_exe": "fake-openocd.exe"})
    def test_stm32_mode_with_key_passthrough_regression(
            self, _m_machine, m_gates):
        """回归面: STM32+有键 → openocd_exe 原值透传 run_gates
        (run_gates 第 5 位参数), 缺键分流不得误伤有键路径。"""
        self._write_config({})
        with mock.patch.object(sys, "argv",
                               ["release.py", "--tag", "v9.9.9",
                                "--project", self.ws]):
            with self.assertRaises(SystemExit) as cm:
                release.main()
        self.assertEqual(cm.exception.code, 1)   # run_gates 返回 False
        self.assertEqual(m_gates.call_args[0][4], "fake-openocd.exe")
