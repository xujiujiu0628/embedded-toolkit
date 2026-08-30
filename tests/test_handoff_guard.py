# -*- coding: utf-8 -*-
"""handoff_guard 双向自测：该拦的拦（L1/L2 归属到 commit）、该放的放（allowlist/prose/降级）。

威胁模型：善意的陌生智能体犯糊涂——L2 对"基础版本已在同文件使用同一模式"的改动降级为
警告（内容导向，swd_probe 教训），只有新模式出现在新位置才阻断。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import handoff_guard  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]

BASE_TREE = {
    "machine.json": '{"gcc_path": "C:/gcc/bin"}',
    "hooks/block-malloc.sh": "#!/bin/sh\ngrep -q malloc \"$1\" && exit 2 || exit 0\n",
    "scripts/handoff_guard.py": "# guard stub (real one lives in the real repo)\n",
    "scripts/verify.py": "def run():\n    return 0\n",
    "scripts/release.py": "def gate():\n    return 0\n",
    "scripts/capture_oo.py": 'args = ["openocd", "-c", "target remote"]\n',
    "tests/test_something.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(1, 1)\n",
    "README.md": "# toolkit\n\nA workbench.\n",
}


def _git(repo, *args, check=True):
    r = subprocess.run(["git"] + GIT_ID + ["-C", repo] + list(args),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, r.stderr))
    return r.stdout


class GuardHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        for path, content in BASE_TREE.items():
            full = os.path.join(self.repo, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "branch", "-M", "master")
        _git(self.repo, "checkout", "-q", "-b", "handoff/t")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _commit(self, msg, changes):
        """changes: {relpath: new_content or None(删除)} → 返回 commit 短 sha"""
        for path, content in changes.items():
            full = os.path.join(self.repo, *path.split("/"))
            if content is None:
                os.remove(full)
            else:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", msg)
        return _git(self.repo, "rev-parse", "--short", "HEAD").strip()

    def _guard(self):
        return handoff_guard.guard(self.repo, "handoff/t", "master")

    # ---------- 该放的：纯修复 / allowlist / prose 豁免 ----------

    def test_clean_pure_fix(self):
        self._commit("fix: add helper", {"scripts/util.py": "def helper():\n    return 42\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertEqual(v["blocked"], [])

    def test_tests_dir_allowlist(self):
        # 负样例数据/测试夹具里出现硬件字样是合法（fixture 本身）
        self._commit("test: fixture mentions serial",
                     {"tests/test_hw_mock.py":
                      "SNIPPET = 'serial.Serial(COM3)'\nFLASH = 'flash write_image erase app.hex'\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertEqual(v["blocked"], [])

    def test_markdown_prose_exempt(self):
        self._commit("docs: list banned patterns",
                     {"HANDOFF-AGENT.md":
                      "# 禁：openocd -f board.cfg flash write_image\n端口 19021 不得访问\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertEqual(v["blocked"], [])

    def test_existing_hardware_file_downgraded_to_warning(self):
        # capture_oo.py 基础版本已用 openocd+remote 模式 → 同模式追加视为维护，警告不阻断
        self._commit("fix: openocd args reorder",
                     {"scripts/capture_oo.py":
                      'args = ["openocd", "-c", "target remote"]\nargs2 = ["openocd", "-f", "init.tcl"]\n'})
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertTrue(any(w["rule"] == "openocd_call" for w in v["warnings"]),
                        "同模式既有文件应降级为警告: %s" % json.dumps(v, ensure_ascii=False))

    # ---------- 该拦的：L1 文件禁线 ----------

    def test_L1_machine_json_blocked(self):
        sha1 = self._commit("fix: unrelated", {"scripts/util.py": "X = 1\n"})
        sha2 = self._commit("feat: new toolchain path",
                            {"machine.json": '{"gcc_path": "D:/other/bin"}'})
        v = self._guard()
        self.assertEqual(v["verdict"], "blocked")
        hits = [b for b in v["blocked"] if b["rule"] == "forbidden_file:machine.json"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["commit"][:len(sha2)], sha2)

    def test_L1_hooks_blocked(self):
        self._commit("feat: tweak hook",
                     {"hooks/block-malloc.sh": "#!/bin/sh\nexit 0\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "blocked")
        self.assertTrue(any(b["rule"].startswith("forbidden_file:hooks/") for b in v["blocked"]))

    # ---------- 该拦的：L2 新模式新位置 ----------

    def test_L2_new_serial_call_blocked(self):
        sha = self._commit("feat: serial helper",
                           {"scripts/port_opener.py":
                            "import serial\n\ndef openp():\n    return serial.Serial('COM3', 115200)\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "blocked")
        hits = [b for b in v["blocked"] if b["rule"] == "serial_open"]
        self.assertTrue(hits, v)
        self.assertEqual(hits[0]["commit"][:len(sha)], sha)
        self.assertEqual(hits[0]["file"].replace("\\", "/"), "scripts/port_opener.py")

    def test_L2_flash_command_and_rtt_port_blocked(self):
        sha = self._commit("feat: flash step",
                           {"scripts/build_flow.py":
                            "CMD = 'openocd -c \"flash write_image erase fw.hex\"'\nPORT = 19021\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "blocked")
        rules = {b["rule"] for b in v["blocked"]}
        self.assertIn("flash_cmd", rules)
        self.assertIn("rtt_port", rules)

    # ---------- L3：主流程改动无测试伴随（警告不阻断）----------

    def test_L3_main_flow_without_tests_warns(self):
        self._commit("fix: verify tweak", {"scripts/verify.py": "def run():\n    return 1\n"})
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertTrue(any(w["rule"].startswith("main_flow_no_test") for w in v["warnings"]), v)

    def test_L3_satisfied_with_test_change(self):
        self._commit("fix: verify tweak + test", {
            "scripts/verify.py": "def run():\n    return 1\n",
            "tests/test_verify_tweak.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n",
        })
        v = self._guard()
        self.assertEqual(v["verdict"], "clean")
        self.assertFalse(any(w["rule"].startswith("main_flow_no_test") for w in v["warnings"]), v)

    # ---------- 输出契约 ----------

    def test_clean_branch_reports_meta(self):
        self._commit("fix: doc only", {"README.md": "# toolkit\n\nUpdated.\n"})
        v = self._guard()
        for key in ("verdict", "blocked", "warnings", "base", "branch", "commits_scanned"):
            self.assertIn(key, v)
        self.assertEqual(v["base"], "master")
        self.assertEqual(v["branch"], "handoff/t")
        self.assertEqual(v["commits_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
