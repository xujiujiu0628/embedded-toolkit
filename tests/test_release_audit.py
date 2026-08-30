"""release_audit 回归 (M-3, 2026-08-30 代管 Day 3).

发布记录与 annotated tag 是本地 git 操作, 无签名 — 本工具补"事后复核"。
测试用真实 git 临时仓构造 各类篡改/缺失 场景, 全程不触硬件。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import release_audit  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench", "releases"))
        os.makedirs(os.path.join(self.ws, "build"))

        def git(*a):
            subprocess.run(["git"] + GIT_ID + list(a), cwd=self.ws,
                           capture_output=True, timeout=30, check=True)
        git("init", "-q")
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("x")
        # R7 契约文件: 发布时工作树 clean → 契约内容 == git_head 处内容
        self.exp_data = '{"expectations": [{"id": "FR-A", "desc": "boot", "texts": ["OK"]}]}'.encode()
        self.cfg_data = b'{"builder": "gcc"}'
        with open(os.path.join(self.ws, ".workbench", "expectations.json"), "wb") as f:
            f.write(self.exp_data)
        with open(os.path.join(self.ws, ".workbench", "config.json"), "wb") as f:
            f.write(self.cfg_data)
        git("add", "-A")
        git("commit", "-qm", "init")
        self.git = git
        _, head, _ = release_audit._git(["rev-parse", "HEAD"], self.ws)
        self.head = head
        self.hex_rel = "build/adc.hex"
        self.hex_data = b":020000040800F2\n"
        with open(os.path.join(self.ws, self.hex_rel), "wb") as f:
            f.write(self.hex_data)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _record(self, tag="v1.1.0", results=None, waived=None, git_head=None,
                contracts=None):
        return {
            "tag": tag, "git_head": git_head if git_head is not None else self.head,
            "branch": "master", "timestamp": "2026-08-30T12:00:00+08:00",
            "build_mode": "clean_rebuild",
            "artifacts": {"hex": {"path": self.hex_rel, "sha256": _sha(self.hex_data)}},
            "results": results if results is not None else [{"id": "FR-A", "status": "pass"}],
            "xfail_waived": waived if waived is not None else [],
            "tools": {"toolkit": "0.1", "python": "3.x", "gcc": "gnu-13"},
            "contracts": contracts if contracts is not None else {
                "expectations_sha256": _sha(self.exp_data),
                "config_sha256": _sha(self.cfg_data),
            },
        }

    def _write(self, record, tag="v1.1.0", commit_record=True, make_tag=True):
        rel = os.path.join(".workbench", "releases", f"{tag}.json")
        with open(os.path.join(self.ws, rel), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        if make_tag:
            self.git("tag", "-a", tag, "-m", "release")
        if commit_record:
            self.git("add", rel)
            self.git("commit", "-qm", "release record")
        return rel

    def test_valid_record_clean(self):
        rel = self._write(self._record())
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "clean", out["checks"])
        self.assertEqual([c["id"] for c in out["checks"]],
                         ["R1", "R2", "R3", "R4", "R5", "R6", "R7"])

    def test_old_record_without_contracts_warns(self):
        # F-015: R7 之前的旧记录 (如 adc-oled v1.1.0) 缺绑定 → 警告不阻断
        rec = self._record()
        del rec["contracts"]
        rel = self._write(rec)
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "warned")
        r7 = [c for c in out["checks"] if c["id"] == "R7"][0]
        self.assertEqual(r7["status"], "warn")

    def test_tampered_contract_hash_fails(self):
        # F-015 核心场景: 记录声称按 A 清单判绿, tag 处实际是 B 清单 → 现形
        rec = self._record(contracts={
            "expectations_sha256": "0" * 64,
            "config_sha256": _sha(self.cfg_data)})
        rel = self._write(rec)
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")
        r7 = [c for c in out["checks"] if c["id"] == "R7"][0]
        self.assertEqual(r7["status"], "fail")
        self.assertIn("expectations", r7["detail"])

    def test_moved_record_contract_mismatch_fails(self):
        # 把别的 HEAD 产出的记录搬到新 tag 下 (git_head 一致但契约内容不同) → fail
        self.git("commit", "-qm", "touch", "--allow-empty")
        rec = self._record(contracts={
            "expectations_sha256": _sha(b'{"expectations": [{"id": "OTHER"}]}'),
            "config_sha256": _sha(self.cfg_data)})
        rel = self._write(rec)
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        r7 = [c for c in out["checks"] if c["id"] == "R7"][0]
        self.assertEqual(r7["status"], "fail")

    def test_tampered_hex_fails(self):
        rel = self._write(self._record())
        with open(os.path.join(self.ws, self.hex_rel), "wb") as f:
            f.write(b"TAMPERED")
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")
        r3 = [c for c in out["checks"] if c["id"] == "R3"][0]
        self.assertEqual(r3["status"], "fail")

    def test_head_mismatch_fails(self):
        rel = self._write(self._record(git_head="0" * 40))
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        r2 = [c for c in out["checks"] if c["id"] == "R2"][0]
        self.assertEqual(r2["status"], "fail")

    def test_missing_tag_fails(self):
        rel = self._write(self._record(), make_tag=False)
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")

    def test_fail_entry_in_results_fails(self):
        rel = self._write(self._record(results=[
            {"id": "FR-A", "status": "pass"},
            {"id": "FR-B", "status": "fail"}]))
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")

    def test_xpass_entry_fails(self):
        rel = self._write(self._record(results=[
            {"id": "FR-B", "status": "xpass"}], waived=["FR-B"]))
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")

    def test_waiver_mismatch_fails(self):
        rel = self._write(self._record(results=[
            {"id": "FR-B", "status": "xfail"}], waived=[]))
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "failed")

    def test_hex_missing_degrades_to_warning(self):
        rel = self._write(self._record())
        os.remove(os.path.join(self.ws, self.hex_rel))
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "warned")  # 字节不在场 ≠ 被篡改
        r3 = [c for c in out["checks"] if c["id"] == "R3"][0]
        self.assertEqual(r3["status"], "warn")

    def test_untracked_record_warns(self):
        rel = self._write(self._record(), commit_record=False)
        out = release_audit.audit_record(self.ws, "v1.1.0", rel)
        self.assertEqual(out["verdict"], "warned")
        r6 = [c for c in out["checks"] if c["id"] == "R6"][0]
        self.assertEqual(r6["status"], "warn")

    def test_unparseable_record_fails(self):
        rel = os.path.join(".workbench", "releases", "v9.9.9.json")
        with open(os.path.join(self.ws, rel), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.git("add", rel)
        self.git("commit", "-qm", "corrupt record")
        out = release_audit.audit_record(self.ws, "v9.9.9", rel)
        self.assertEqual(out["verdict"], "failed")
        self.assertEqual(out["checks"][0]["id"], "R1")

    def test_audit_project_aggregates(self):
        self._write(self._record(), tag="v1.1.0")
        # 第二次发布前 HEAD 已前进 (含 v1.1.0 记录的 commit), 记录 git_head 应为当前 HEAD
        _, self.head, _ = release_audit._git(["rev-parse", "HEAD"], self.ws)
        self._write(self._record(tag="v1.2.0"), tag="v1.2.0")
        out = release_audit.audit_project(self.ws)
        self.assertEqual(out["verdict"], "clean")
        self.assertEqual(len(out["records"]), 2)
        # --all 只在 releases/ 内找; 指定不存在的 tag 报 failed
        out2 = release_audit.audit_project(self.ws, only_tag="v0.0.1")
        self.assertEqual(out2["verdict"], "failed")
        self.assertIn("不存在", out2["error"])


if __name__ == "__main__":
    unittest.main()
