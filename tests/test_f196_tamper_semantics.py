# -*- coding: utf-8 -*-
r"""F-196 防篡改与语义面钉 (WB-20260927-04, WB-05 M-6/L-2/L-7/L-8/L-9/L-10/L-11 + N-3)。

语义件红线: claim 与实现对齐工程, 两头双向钉——
  · fail-open → fail-loud: 每病先钉"坏输入必响" (修前红);
  · 误伤存量: 每修一格带"合法路径不误伤"金比对 (修前就绿, 修后仍绿)。
  T1 命门: 历史发布记录零翻动——新判据对真实存量零冲突 (四条真档全部
  无 evidence 字段, 走 R8 warn 分支, 不进 production_approved 面)。
打桩纪律: 本文件仅用模块引用替换式 (patch.object 首参 = 仓内模块名),
全局对象零置桩 — 棘轮快照零新增。
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import doctor  # noqa: E402
import fsd_coverage  # noqa: E402
import handoff_guard  # noqa: E402
import phase_minus_one  # noqa: E402
import release  # noqa: E402
import release_audit  # noqa: E402
import serial_send  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(repo, *args, check=True, cwd=None):
    r = subprocess.run(["git"] + GIT_ID + list(args), cwd=cwd or repo,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, r.stderr))
    return r.stdout


# ═══════════════════ T1 (M-6): release_audit R8 手工填戳 + R6 工作树脏 ═══════════════════

class R8R6TamperSemanticsTests(unittest.TestCase):
    """R8: 批准戳须有留痕链 (fidelity_boundaries 批准注记) 或 git 在场证据
    (入库版本含同戳); R6: 已跟踪记录的未提交变更须 WARN 显形。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="f196r8_")
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        self.git = lambda *a: _git(self.ws, *a)
        self.git("init", "-q")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.f_data = b"x"
        with open(os.path.join(self.ws, "f.txt"), "wb") as f:
            f.write(self.f_data)
        self.exp_data = b'{"expectations": [{"id": "FR-A", "desc": "boot", "texts": ["OK"]}]}'
        self.cfg_data = b'{"builder": "gcc"}'
        os.makedirs(os.path.join(self.ws, ".workbench"), exist_ok=True)
        with open(os.path.join(self.ws, ".workbench", "expectations.json"), "wb") as f:
            f.write(self.exp_data)
        with open(os.path.join(self.ws, ".workbench", "config.json"), "wb") as f:
            f.write(self.cfg_data)
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        _, self.head, _ = release_audit._git(["rev-parse", "HEAD"], self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _record(self, tag="v1.1.0", evidence="hardware_validated"):
        rec = {
            "tag": tag, "git_head": self.head, "branch": "master",
            "timestamp": "2026-09-27T12:00:00+08:00",
            "build_mode": "clean_rebuild",
            "artifacts": {"hex": {"path": "f.txt",
                                  "sha256": hashlib.sha256(self.f_data).hexdigest()}},
            "results": [{"id": "FR-A", "status": "pass"}],
            "xfail_waived": [],
            "evidence": evidence,
            "tools": {"toolkit": "0.6", "python": "3.x", "gcc": "gnu"},
            "contracts": {"expectations_sha256": hashlib.sha256(self.exp_data).hexdigest(),
                          "config_sha256": hashlib.sha256(self.cfg_data).hexdigest()},
        }
        return rec

    def _write(self, rec, tag="v1.1.0", commit=True, tag_it=True):
        rel = os.path.join(".workbench", "releases", f"{tag}.json")
        with open(os.path.join(self.ws, rel), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        if tag_it:
            self.git("tag", "-a", tag, "-m", "release")
        if commit:
            self.git("add", rel.replace(os.sep, "/"))
            self.git("commit", "-qm", "release record")
        return rel

    def _r8(self, out):
        return [c for c in out["checks"] if c["id"] == "R8"][0]

    def _r6(self, out):
        return [c for c in out["checks"] if c["id"] == "R6"][0]

    # ---- R8 该响的: 手工填戳无链 (修前红) ----

    def test_r8_handstamp_uncommitted_no_chain_fails(self):
        # 无留痕链 + 未入库: 手填批准戳无任何在场证据 → 篡改显形
        rec = self._record(evidence="production_approved")
        rec["production_approved_at"] = "2026-09-27T09:00:00+08:00"
        self._write(rec, commit=False, tag_it=False)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "fail", out["checks"])
        self.assertIn("留痕", self._r8(out)["detail"])

    def test_r8_worktree_handstamp_tamper_fails(self):
        # 入库的是 hardware_validated, 工作树手改成 production_approved+戳
        # (未提交): 入库版本无同戳 → 篡改显形 (旧判据只看戳非空 = 放行)
        rec = self._record()
        self._write(rec)
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "r", encoding="utf-8") as f:
            tampered = json.load(f)
        tampered["evidence"] = "production_approved"
        tampered["production_approved_at"] = "2026-09-27T09:00:00+08:00"
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "w", encoding="utf-8") as f:
            json.dump(tampered, f, ensure_ascii=False, indent=2)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "fail", out["checks"])

    def test_r8_handstamp_altered_committed_stamp_fails(self):
        # 入库带戳, 工作树把戳改成别的值 (未提交): 与入库版本不一致 → fail
        rec = self._record(evidence="production_approved")
        rec["production_approved_at"] = "2026-09-27T09:00:00+08:00"
        self._write(rec)
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "r", encoding="utf-8") as f:
            tampered = json.load(f)
        tampered["production_approved_at"] = "2020-01-01T00:00:00+08:00"
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "w", encoding="utf-8") as f:
            json.dump(tampered, f, ensure_ascii=False, indent=2)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "fail", out["checks"])

    # ---- R8 合法路径不误伤 (修前就绿, 金比对) ----

    def test_r8_committed_stamp_still_passes(self):
        # 历史形态金比对: 入库记录自带批准戳 ( approve→commit 正常收尾)
        # → git 在场证据 → pass (对位既有 test_r8_production_approved_with_stamp_passes)
        rec = self._record(evidence="production_approved")
        rec["production_approved_at"] = "2026-09-27T09:00:00+08:00"
        self._write(rec)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "pass", out["checks"])

    def test_r8_chain_passes_in_precommit_window(self):
        # --approve 刚回填、尚未 git 提交的窗口: fidelity_boundaries 批准
        # 注记在场 (approve_record 既有字段链) → pass, 合法工作流不误伤
        rec = self._record(evidence="production_approved")
        rec["production_approved_at"] = "2026-09-27T09:00:00+08:00"
        rec["fidelity_boundaries"] = [
            "production_approved: 经 release_audit --approve 人工批准投产; "
            "底层证据仍以 hardware_validated 运行为准"]
        self._write(rec, commit=False, tag_it=False)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "pass", out["checks"])

    def test_r8_legacy_record_without_evidence_still_warns(self):
        # 真实存量形态 (四条真档全部如此): 无 evidence 字段 → warn 分支,
        # 新判据不接触 (历史语义零翻动)
        rec = self._record()
        del rec["evidence"]
        self._write(rec)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r8(out)["status"], "warn", out["checks"])

    # ---- R6 该响的: 已跟踪记录未提交变更 (修前红) ----

    def test_r6_dirty_worktree_warns(self):
        rec = self._record()
        self._write(rec)
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "r", encoding="utf-8") as f:
            edited = json.load(f)
        edited["branch"] = "tampered"   # 无害字段改动 = 工作树脏
        with open(os.path.join(self.ws, ".workbench", "releases",
                               "v1.1.0.json"), "w", encoding="utf-8") as f:
            json.dump(edited, f, ensure_ascii=False, indent=2)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r6(out)["status"], "warn", out["checks"])
        self.assertIn("未提交", self._r6(out)["detail"])
        self.assertEqual(out["verdict"], "warned", "R6 脏=警告级, 不拦发布")

    def test_r6_clean_worktree_still_passes(self):
        rec = self._record()
        self._write(rec)
        out = release_audit.audit_record(
            self.ws, "v1.1.0", os.path.join(".workbench", "releases", "v1.1.0.json"))
        self.assertEqual(self._r6(out)["status"], "pass", out["checks"])


# ═══════════════════ T2 (L-2): phase_minus_one fixed_pins 三态 + 退出码 ═══════════════════

class FixedPinsTriStateTests(unittest.TestCase):
    """三态: 缺失=None 文案照旧 / 损坏=CORRUPT 显态 BLOCKED / 合法=照常。
    旧病: 损坏与缺失同 return None 且 detail 谎报"没有占用表" (fail-open)。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="f196pins_")
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"builder": "gcc"}')

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _pins_file(self, content_bytes):
        p = os.path.join(self.ws, ".workbench", "fixed_pins.json")
        with open(p, "wb") as f:
            f.write(content_bytes)
        return p

    def test_corrupt_json_returns_corrupt_sentinel(self):
        self._pins_file(b"{corrupt")
        sent = phase_minus_one.load_fixed_pins(self.ws)
        self.assertIsInstance(sent, phase_minus_one.FixedPinsCorrupt,
                              "损坏占用表不得冒充缺失 (None), 修前它返回 None")

    def test_non_dict_json_is_corrupt_too(self):
        # 合法 JSON 但类型错 ([] / "x") 同样是损坏 — pin in fixed_pins 会静默走偏
        self._pins_file(b"[]")
        self.assertIsInstance(phase_minus_one.load_fixed_pins(self.ws),
                              phase_minus_one.FixedPinsCorrupt)

    def test_corrupt_pins_block_verdict_with_named_state(self):
        self._pins_file(b"{corrupt")
        out = phase_minus_one.run_check("I2C1", ["PB6", "PB7"],
                                        workspace=self.ws)
        pc = out["checks"]["pin_conflict"]
        self.assertEqual(pc["status"], "CORRUPT", out["checks"])
        self.assertIn("fixed_pins.json", pc["detail"])
        self.assertNotIn("No fixed-pins map", pc["detail"],
                         "损坏不得谎报为缺失文案")
        self.assertEqual(out["verdict"], "BLOCKED", out["verdict"])

    def test_compute_verdict_corrupt_is_blocked(self):
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "OK"}, "b": {"status": "CORRUPT"}}), "BLOCKED")

    def test_missing_pins_behavior_byte_identical(self):
        # 缺失态逐字节不变 (合法路径金比对): 文案与状态原样
        self.assertIsNone(phase_minus_one.load_fixed_pins(self.ws))
        out = phase_minus_one.run_check("I2C1", ["PB6", "PB7"],
                                        workspace=self.ws)
        pc = out["checks"]["pin_conflict"]
        self.assertEqual(
            pc["detail"],
            "No fixed-pins map (.workbench/fixed_pins.json) — conflict check skipped")
        self.assertEqual(pc["status"], "OK")

    def test_valid_pins_unchanged(self):
        self._pins_file(
            '{"PC13": "LED heartbeat (GPIO Output)"}'.encode("utf-8"))
        out = phase_minus_one.check_pin_conflicts(
            ["PC13"], "USART1", phase_minus_one.load_fixed_pins(self.ws))
        self.assertEqual(out["status"], "CONFLICT")
        self.assertIn("used by LED heartbeat", out["detail"])

    def test_main_blocked_exit_code_one(self):
        # BLOCKED → rc=1 (旧病: main 无 sys.exit, BLOCKED 也 rc=0)
        self._pins_file(b"{corrupt")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        r = subprocess.run(
            [sys.executable, "-X", "utf8",
             os.path.join(REPO_ROOT, "scripts", "phase_minus_one.py"),
             "--peripheral", "I2C1", "--pins", "PB6,PB7", "--json"],
            cwd=self.ws, env=env, capture_output=True, timeout=120)
        self.assertEqual(
            r.returncode, 1,
            "BLOCKED 退出码须非零; stdout=%s stderr=%s"
            % (r.stdout[-200:], r.stderr[-200:]))


# ═══════════════════ T3 (L-10): handoff_guard L2 豁免锚定收窄 ═══════════════════

class L2AllowlistAnchorTests(unittest.TestCase):
    """豁免收窄为仓根相对路径段前缀 (^tests/ 或 ^tests$; fixtures 同)。
    旧病: any(p in L2_ALLOW_DIRS for p in parts[:-1]) — 任意深度名为
    tests/fixtures 的目录全豁免, docs/tests/x.py 穿透。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f196guard_")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        with open(os.path.join(self.repo, "README.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("# t\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        _git(self.repo, "branch", "-M", "master")
        _git(self.repo, "checkout", "-q", "-b", "handoff/t")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _commit(self, relpath, content):
        full = os.path.join(self.repo, *relpath.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "probe")
        return relpath

    def _guard(self):
        return handoff_guard.guard(self.repo, "handoff/t", "master")

    def test_nested_tests_dir_no_longer_exempt(self):
        self._commit("docs/tests/probe.py",
                     "import serial\nser = serial.Serial('COM3', 115200)\n")
        v = self._guard()
        hits = [b for b in v["blocked"] if b["rule"] == "serial_open"
                and b["file"].replace("\\", "/") == "docs/tests/probe.py"]
        self.assertTrue(
            hits, "嵌套 tests 名目录须参与 L2 扫描 (修前被全豁免): %s" % v)

    def test_nested_fixtures_dir_no_longer_exempt(self):
        self._commit("docs/fixtures/hw.json",
                     '{"cmd": "openocd -c \\"flash write_image erase fw.hex\\""}\n')
        v = self._guard()
        hits = [b for b in v["blocked"] if b["rule"] == "flash_cmd"]
        self.assertTrue(hits, "嵌套 fixtures 名目录须参与 L2 扫描: %s" % v)

    def test_root_tests_still_exempt(self):
        self._commit("tests/test_probe.py",
                     "SNIPPET = 'serial.Serial(COM3)'\n")
        v = self._guard()
        self.assertEqual(v["blocked"], [], "仓根 tests/ 豁免不得误伤: %s" % v)

    def test_root_fixtures_still_exempt(self):
        self._commit("fixtures/probe.json", '{"port": 19021}\n')
        v = self._guard()
        self.assertEqual(v["blocked"], [], "仓根 fixtures/ 豁免不得误伤: %s" % v)

    def test_tests_under_tests_still_exempt(self):
        self._commit("tests/fixtures/x.py", "PORT = 19021\n")
        v = self._guard()
        self.assertEqual(v["blocked"], [], "tests/fixtures 前缀豁免维持: %s" % v)


# ═══════════════════ T4 (L-7): release.py _gcc_version 跨平台 ═══════════════════

class GccVersionCrossPlatformTests(unittest.TestCase):
    """F-164 同款平台化: shutil.which 优先 (nt 试 PATHEXT, POSIX 无后缀),
    配了 gcc_path 不再硬拼 .exe; 探不到仍 unknown 但原因入输出。
    ESP not_applicable 面 (F-190) 由 test_f190_release_chain 既有钉守护。"""

    def _patched(self, machine, which_fn, run_fn):
        stub_shutil = types.SimpleNamespace(which=which_fn)
        stub_sub = types.SimpleNamespace(run=run_fn)
        return (mock.patch.object(release, "load_machine",
                                  return_value=machine),
                mock.patch.object(release, "shutil", stub_shutil),
                mock.patch.object(release, "subprocess", stub_sub))

    def test_which_hit_resolves_real_binary(self):
        # POSIX 发布机形态: gcc_path 配置在册, which 探到无后缀二进制
        calls = {}

        def fake_run(cmd, **kw):
            calls["exe"] = cmd[0]
            return types.SimpleNamespace(
                returncode=0, stdout="arm-none-eabi-gcc (GNU) 10.3.1\n")

        def which_fn(cmd, path=None):
            return "/usr/bin/arm-none-eabi-gcc" if cmd == "arm-none-eabi-gcc" else None

        p1, p2, p3 = self._patched({"gcc_path": "/opt/gcc/bin"},
                                   which_fn, fake_run)
        with p1, p2, p3:
            out = release._gcc_version()
        self.assertEqual(calls["exe"], "/usr/bin/arm-none-eabi-gcc",
                         "探测须走 which 解析, 不得硬拼 .exe (修前病)")
        self.assertEqual(out, "arm-none-eabi-gcc (GNU) 10.3.1")

    def test_which_miss_reports_reason(self):
        def must_not_run(cmd, **kw):
            raise AssertionError("探不到还跑 subprocess: %r" % (cmd,))

        def which_fn(cmd, path=None):
            return None

        p1, p2, p3 = self._patched({"gcc_path": "/opt/gcc/bin"},
                                   which_fn, must_not_run)
        with p1, p2, p3:
            out = release._gcc_version()
        self.assertTrue(out.startswith("unknown"), out)
        self.assertIn("gcc_path", out, "原因须入输出 (修前裸 unknown)")
        self.assertIn("PATH", out)

    def test_no_gcc_path_falls_back_to_path_via_which(self):
        # 未配 gcc_path → PATH 探测语义维持, 且经 which 解析 (修前裸名直跑)
        calls = {}

        def fake_run(cmd, **kw):
            calls["exe"] = cmd[0]
            return types.SimpleNamespace(returncode=0, stdout="gcc 10.3.1\n")

        def which_fn(cmd, path=None):
            return "/usr/bin/arm-none-eabi-gcc"

        p1, p2, p3 = self._patched({"gcc_path": ""}, which_fn, fake_run)
        with p1, p2, p3:
            out = release._gcc_version()
        self.assertEqual(calls["exe"], "/usr/bin/arm-none-eabi-gcc")
        self.assertEqual(out, "gcc 10.3.1")


# ═══════════════════ T5 (L-9): doctor fixture 哈希对原始字节 ═══════════════════

class FixtureShaRawBytesTests(unittest.TestCase):
    """漂移哈希必须对 git blob 原始字节算 (release_audit._git_bytes 同纪律)。
    旧病: git show 经 encoding/replace 解码再 encode — 非 UTF-8 字节变
    U+FFFD, 漂移误报偏红。oracle = 测试内独立 git show 字节哈希。"""

    def _make_repo(self, config_bytes):
        tmp = tempfile.mkdtemp(prefix="f196sha_")
        repo = os.path.join(tmp, "tkroot")
        fdir = os.path.join(repo, "proj", ".workbench", "fixtures")
        os.makedirs(fdir)
        with open(os.path.join(fdir, "config.json"), "wb") as f:
            f.write(config_bytes)
        with open(os.path.join(fdir, "expectations.json"), "wb") as f:
            f.write(b'{"expectations": []}')
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _git(repo, "branch", "-M", "master")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return repo, fdir

    def _oracle(self, repo, rel):
        r = subprocess.run(["git", "show", self._base_ref(repo) + ":" + rel],
                           cwd=repo, capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return hashlib.sha256(r.stdout).hexdigest()

    @staticmethod
    def _base_ref(repo):
        """基准分支名: master 优先, 否则用当前 HEAD。

        F-214 修 CI 假绿: 原实现硬编码 "master:", 而 CI 的 actions/checkout
        在 PR 上只检出 PR 分支 (本地无 master), `git show master:<path>` 直接
        报 "invalid object name 'master'" → 该金值比对在 CI 上从未真正执行,
        是长期假绿。本地/分支检出形态不一, 故按可用性择基准分支。
        """
        head = subprocess.run(["git", "rev-parse", "--verify", "master"],
                              cwd=repo, capture_output=True, timeout=30)
        if head.returncode == 0:
            return "master"
        return "HEAD"

    def test_non_utf8_bytes_hashed_raw(self):
        # 含非法 UTF-8 字节 (GBK 双字节) 的 fixture — 修前: U+FFFD 往返
        # → 哈希 ≠ oracle (漂移误报); 修后: 字节直传 → 与 oracle 一致
        payload = b'{"note": "gbk:\xb4\xea"}'
        repo, fdir = self._make_repo(payload)
        with mock.patch.object(doctor, "TOOLKIT_ROOT", repo):
            out = doctor._fixture_main_sha(fdir)
        expect = self._oracle(repo, "proj/.workbench/fixtures/config.json")
        self.assertEqual(out.get("config_sha256"), expect, out)

    def test_normal_json_hash_unchanged(self):
        # 合法 UTF-8 JSON: 解码-再编码本为恒等 → 修前修后同值 (历史档案零翻动)
        payload = '{"builder": "gcc", "note": "中文"}'.encode("utf-8")
        repo, fdir = self._make_repo(payload)
        with mock.patch.object(doctor, "TOOLKIT_ROOT", repo):
            out = doctor._fixture_main_sha(fdir)
        expect = self._oracle(repo, "proj/.workbench/fixtures/config.json")
        self.assertEqual(out.get("config_sha256"), expect, out)
        self.assertEqual(out.get("config_sha256"),
                         hashlib.sha256(payload).hexdigest())

    def test_real_repo_contract_fixtures_stable(self):
        # 真仓 master 的 contract fixtures 金值: 修前修后必须同值
        # (变了就是错 — 历史漂移档案口径零翻动)
        fdir = os.path.join(REPO_ROOT, "tests", "fixtures", "contract")
        out = doctor._fixture_main_sha(fdir)
        for name, key in (("config.json", "config_sha256"),
                          ("expectations.json", "expectations_sha256")):
            expect = self._oracle(REPO_ROOT, "tests/fixtures/contract/" + name)
            self.assertEqual(out.get(key), expect, key)


# ═══════════════════ T6 (L-11): fsd_coverage 损坏回退响亮化 ═══════════════════

_FSD_MIN = "## FR-A-01: boot banner\n### FR-B-02: key scan\n"
_EXP_MIN = {"expectations": [
    {"id": "FR-A-01", "desc": "boot", "texts": ["OK"]},
    {"id": "FR-B-02", "desc": "keys", "texts": ["K1"]},
]}


class FsdCorruptConfigWarnTests(unittest.TestCase):
    """config 损坏 → 人读输出必须带醒目 WARN 行 (回退事实+路径);
    退出码语义不动 (覆盖面判定照常出); 正常 cfg 人读输出逐字节不变。"""

    def _project(self, config_content):
        ws = tempfile.mkdtemp(prefix="f196fsd_")
        os.makedirs(os.path.join(ws, "docs"))
        os.makedirs(os.path.join(ws, ".workbench"))
        with open(os.path.join(ws, "docs", "FSD.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(_FSD_MIN)
        with open(os.path.join(ws, ".workbench", "expectations.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(_EXP_MIN, f)
        with open(os.path.join(ws, ".workbench", "config.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(config_content)
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        return ws

    def test_corrupt_config_fallback_warns_loudly(self):
        ws = self._project("{oops")
        res = fsd_coverage.run_coverage(ws)
        self.assertTrue(
            any("config.json 不可读" in n for n in res["notes"]),
            res["notes"])
        # 覆盖面判定照常出 (退出码语义不动): 对账面完整 → verdict 照 reconcile
        self.assertEqual(res["verdict"], "clean", res["verdict"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            fsd_coverage._print_human(res)
        out = buf.getvalue()
        self.assertIn("[W]", out, "人读输出须含 WARN 行 (修前 notes 仅 JSON 可见)")
        self.assertIn("config.json 不可读", out)
        self.assertIn("fsd_path", out)

    def test_normal_config_human_output_byte_identical(self):
        # 正常 cfg: 人读输出逐字节不变 (金比对, PROJ 路径占位)
        ws = self._project('{"builder": "gcc"}')
        res = fsd_coverage.run_coverage(ws)
        buf = io.StringIO()
        with redirect_stdout(buf):
            fsd_coverage._print_human(res)
        out = buf.getvalue().replace(ws, "@@PROJ@@")
        self.assertEqual(out, T6_NORMAL_GOLDEN)


T6_NORMAL_GOLDEN = (
    'fsd_coverage: @@PROJ@@  ->  CLEAN\n'
    '  FSD 需求 2 | 断言 2 | 豁免 0\n'
    '  --- 对照表 (漂移审读面: 一眼扫语义) ---\n'
    '  [✓断言] FR-A-01          FSD: boot banner  ⇐ 断言: boot\n'
    '  [✓断言] FR-B-02          FSD: key scan  ⇐ 断言: keys\n'
    '  对账全绿\n'
)


# ═══════════════════ T7 (N-3): serial_send hex token 级解析 ═══════════════════

class HexTokenParseTests(unittest.TestCase):
    r"""token 级解析: 按 [\s,]+ 切分后逐 token 去 0[xX] 前缀, 段内非法字符
    → bad_hex 显式拒; 不做全文子串删除 (A0xB 类不再静默损坏)。"""

    def test_a0xb_explicitly_rejected(self):
        # 旧病: replace("0x","") 把 A0xB 剥成 AB → b'\xab' 静默损坏
        self.assertIsNone(serial_send.build_payload("A0xB", True, "none"))

    def test_uppercase_0x_prefix_accepted(self):
        # 旧病: 0X 大写不剥 → 不对称 None; 现与 0x 同权
        self.assertEqual(serial_send.build_payload("0XAB", True, "none"),
                         b"\xab")
        self.assertEqual(serial_send.build_payload("0XDE,0XAD", True, "none"),
                         b"\xde\xad")

    def test_mid_token_0x_not_stripped(self):
        # 0x 只在 token 头剥: "D0xE" 是非法 token, 不再全文删除出假字节
        self.assertIsNone(serial_send.build_payload("D0xE", True, "none"))

    def test_existing_legal_cases_golden(self):
        # 既有合法用例金比对 (对位 test_serial_send_payload 既有钉)
        self.assertEqual(serial_send.build_payload("DE AD", True, "none"),
                         b"\xde\xad")
        self.assertEqual(serial_send.build_payload("0xDE,0xAD", True, "none"),
                         b"\xde\xad")
        self.assertEqual(serial_send.build_payload("0xab", True, "none"),
                         b"\xab")
        self.assertEqual(serial_send.build_payload("AB", True, "none"),
                         b"\xab")
        self.assertIsNone(serial_send.build_payload("ZZ", True, "none"))
        self.assertEqual(serial_send.build_payload("", True, "none"), b"")
        self.assertIsNone(serial_send.build_payload("D", True, "none"))

    def test_text_mode_untouched(self):
        self.assertEqual(serial_send.build_payload("hi", False, "lf"),
                         b"hi\n")
        self.assertEqual(serial_send.build_payload("hi", False, "crlf"),
                         b"hi\r\n")


if __name__ == "__main__":
    unittest.main()
