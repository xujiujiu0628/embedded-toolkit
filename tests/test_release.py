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

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_blocks_unflipped_xfail(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok",
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
            "steps": {"verify": {"results": [{"id": "FR-B", "status": "xfail"}]}},
        }
        ok, _, ctx = release.run_gates(self.ws, "v1.0.0", allow_xfail=True,
                                       timeout=10, openocd_exe="openocd")
        self.assertTrue(ok)
        self.assertEqual(ctx["waived"], ["FR-B"])

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
