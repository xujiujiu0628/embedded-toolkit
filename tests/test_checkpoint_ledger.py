"""F-047: verify.py 每次跑出可重放证据 — 进度台账 + last_checkpoint 同步.

用户拍板方向 (2026-09-02, 方案四-2):
  - 当前 verify.py 跑出结果只落 feedback_db (校准用), 不存 commit 锚点
  - 事后无法回答 "v1.1.0 tag 之前最后一次 PASS 是哪天哪个 commit"
  - 修复: 双写 —
      ① .workbench/state/checkpoints.jsonl  (追加, append-only, 审计链)
      ② state.json last_checkpoint  (覆盖, 给 release audit / 工具读 "上次状态")

契约定下来:
  - checkpoints.jsonl 每行: ts/git_head/git_branch/status/duration_sec/
    origin/step_keys/contract_hashes (8 字段, ts ISO8601)
  - last_checkpoint 与 checkpoints.jsonl 末行同步, 字段全集, 便于单读
  - 落盘失败不阻断主流程 (与 F-046 audit.jsonl 同款审计非门禁纪律)
  - main() 在 _log_feedback_event 之后 _output 之前调一次 record_checkpoint

本测试锁契约:
  1. record_checkpoint() 写 jsonl + 同步 last_checkpoint
  2. ts 是 ISO8601, 8 字段全集, status ∈ {ok, fail, timing_fail, hardfault, ...}
  3. last_checkpoint 与 jsonl 末行一致 (同步性)
  4. 落盘失败 (OSError mock) 不抛, 走 stderr 告警
  5. main() 集成: verify 跑完一定调 record_checkpoint (mock 验证)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class RecordCheckpointTests(unittest.TestCase):
    """F-047 单元: 写 jsonl + 同步 last_checkpoint"""

    REQUIRED_KEYS = {"ts", "git_head", "git_branch", "status", "duration_sec",
                     "origin", "step_keys", "contract_hashes"}

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_writes_jsonl_with_eight_required_keys(self):
        # mock 阻断 git 调用, 验证字段集完整
        with mock.patch.object(verify, "_git_head", return_value=("abc1234", "main")):
            verify.record_checkpoint(
                workspace=self.ws, status="ok", duration_sec=12.3,
                origin="schedule", step_keys=["build", "flash", "capture", "verify"],
                contract_hashes={"config_sha256": "deadbeef"})
        jsonl_path = os.path.join(self.ws, ".workbench", "state", "checkpoints.jsonl")
        self.assertTrue(os.path.isfile(jsonl_path))
        with open(jsonl_path, encoding="utf-8") as f:
            entry = json.loads(f.readline().strip())
        self.assertEqual(set(entry.keys()), self.REQUIRED_KEYS)
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["git_head"], "abc1234")
        self.assertEqual(entry["git_branch"], "main")
        self.assertEqual(entry["origin"], "schedule")
        self.assertIn("ts", entry)
        self.assertRegex(entry["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_appends_multiple_entries_in_order(self):
        # 同工程跑两次, jsonl 应有两行, 顺序按调用顺序
        with mock.patch.object(verify, "_git_head", return_value=("h1", "main")):
            verify.record_checkpoint(self.ws, "ok", 1.0, "manual", ["build"], {})
            verify.record_checkpoint(self.ws, "fail", 2.0, "schedule", ["build"], {})
        jsonl_path = os.path.join(self.ws, ".workbench", "state", "checkpoints.jsonl")
        with open(jsonl_path, encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        entries = [json.loads(ln) for ln in lines]
        self.assertEqual(entries[0]["status"], "ok")
        self.assertEqual(entries[1]["status"], "fail")

    def test_last_checkpoint_synced_with_last_jsonl_line(self):
        # 关键契约: 读 last_checkpoint 必须等于 jsonl 末行
        with mock.patch.object(verify, "_git_head", return_value=("xyz", "feat/x")):
            verify.record_checkpoint(self.ws, "ok", 5.0, "dispatch",
                                     ["flash", "capture"], {"config_sha256": "x"})
        state_path = os.path.join(self.ws, ".workbench", "state.json")
        self.assertTrue(os.path.isfile(state_path))
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
        self.assertIn("last_checkpoint", state)
        # 字段全集, 与 jsonl 末行一致
        jsonl_path = os.path.join(self.ws, ".workbench", "state", "checkpoints.jsonl")
        with open(jsonl_path, encoding="utf-8") as f:
            last_line = json.loads(f.readlines()[-1])
        # last_checkpoint 是 state.json 的 category 值, 不含 ts 之外的元字段
        self.assertEqual(state["last_checkpoint"]["status"], last_line["status"])
        self.assertEqual(state["last_checkpoint"]["git_head"], last_line["git_head"])
        self.assertEqual(state["last_checkpoint"]["origin"], last_line["origin"])

    def test_disk_failure_does_not_raise(self):
        # 审计非门禁: OSError mock, 不抛, 走 stderr 告警
        with mock.patch.object(verify, "_git_head", return_value=("h", "main")), \
             mock.patch("builtins.open", side_effect=OSError("disk full")):
            # 不应抛
            try:
                verify.record_checkpoint(self.ws, "ok", 1.0, "manual", ["build"], {})
            except OSError:
                self.fail("record_checkpoint 在 OSError 时不应抛")

    def test_invalid_status_rejected(self):
        # 白名单外 status 抛 ValueError, 防止 typo 静默落到台账
        with mock.patch.object(verify, "_git_head", return_value=("h", "main")):
            with self.assertRaises(ValueError) as ctx:
                verify.record_checkpoint(self.ws, "weird_status", 1.0, "manual",
                                        ["build"], {})
        self.assertIn("status", str(ctx.exception).lower())


class GitHeadHelperTests(unittest.TestCase):
    """F-047 _git_head: 隔离调用 git, 失败时给空值而非抛"""

    def test_returns_commit_and_branch(self):
        # 在 git 仓内跑 (worktree 本身就是 git 仓)
        commit, branch = verify._git_head("D:/claude/embedded-toolkit")
        self.assertTrue(commit)  # 非空
        self.assertTrue(branch)  # 非空

    def test_non_git_dir_returns_empty_strings(self):
        commit, branch = verify._git_head(tempfile.gettempdir())
        # 非 git 目录: git 失败, 不抛, 返回 ("", "")
        self.assertEqual(commit, "")
        self.assertEqual(branch, "")


class MainFlowCheckpointTests(unittest.TestCase):
    """F-047 集成: main() 跑完一定调 record_checkpoint"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"))
        with open(os.path.join(self.ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            # capture.backend=rtt 走 mock 路径 (避免 semihosting 分支真起 OpenOCD)
            json.dump({"builder": "gcc", "verify": {"expect": []},
                       "capture": {"backend": "rtt"}}, f)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run_main_with(self, argv_extra):
        """调 main() 一次, mock 阻断外部子工具 + git."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        old_cwd = os.getcwd()
        os.chdir(self.ws)
        try:
            with mock.patch.object(sys, "argv",
                                   ["verify.py"] + list(argv_extra)), \
                 mock.patch.object(verify, "step_build",
                                   return_value={"status": "error"}), \
                 mock.patch.object(verify, "step_flash",
                                   return_value={"status": "ok",
                                                 "stderr": "mocked"}), \
                 mock.patch.object(verify, "_step_capture_rtt",
                                   return_value={"status": "ok", "method": "rtt",
                                                 "lines": 0, "duration_sec": 0.0,
                                                 "raw_length": 0}), \
                 mock.patch.object(verify, "_git_head",
                                   return_value=("test_commit", "test_branch")), \
                 redirect_stdout(io.StringIO()), \
                 redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    verify.main()
        finally:
            os.chdir(old_cwd)

    def test_main_calls_record_checkpoint(self):
        # 关键: verify 跑完一定落 checkpoint, 不论 PASS / FAIL
        with mock.patch.object(verify, "record_checkpoint") as rc_mock:
            self._run_main_with(["--no-build", "--task-origin", "schedule"])
        # record_checkpoint 至少被调一次
        rc_mock.assert_called()
        # 传了 workspace/status/duration_sec/origin/step_keys/contract_hashes
        call_kwargs = rc_mock.call_args.kwargs
        self.assertIn("status", call_kwargs)
        self.assertIn("duration_sec", call_kwargs)
        self.assertIn("origin", call_kwargs)
        self.assertIn("step_keys", call_kwargs)
        self.assertIn("contract_hashes", call_kwargs)
        self.assertEqual(call_kwargs["origin"], "schedule")


if __name__ == "__main__":
    unittest.main()
