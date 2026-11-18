"""verify 报告里的配置摘要（config_attestation）。

## 为什么要有

报告只写 `.workbench/config.json` 这个路径没有信息量——路径在工程生命周期里
是常量，内容不是。报告要能回答两个问题：这次跑的是哪份配置（sha256），以及
跑的过程中它有没有被改过（`diverged_from_file`）。字段挂在 `_output` 这个
唯一出口上，所以 build/flash 早退也带着它。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402


class ConfigAttestationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = self.tmp.name
        os.makedirs(os.path.join(self.project, ".workbench"))
        self.cfg = os.path.join(self.project, ".workbench", "config.json")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        verify._CONFIG_ATTESTATION.clear()

    def tearDown(self):
        verify._CONFIG_ATTESTATION.clear()
        self.tmp.cleanup()

    def test_records_digest_and_relative_path(self):
        verify._record_config_attestation(self.project)
        att = verify._CONFIG_ATTESTATION
        self.assertEqual(att["rel"], ".workbench/config.json")
        self.assertEqual(len(att["sha256"]), 64)
        # 摘要必须是真的文件字节摘要，不是占位
        self.assertEqual(att["sha256"], verify._sha256_file(self.cfg))

    def test_attach_marks_not_diverged(self):
        verify._record_config_attestation(self.project)
        result = {}
        verify._attach_config_attestation(result)
        self.assertEqual(result["config_attestation"]["path"],
                         ".workbench/config.json")
        self.assertFalse(result["config_attestation"]["diverged_from_file"])

    def test_attach_marks_diverged_after_edit(self):
        verify._record_config_attestation(self.project)
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"builder": "gcc", "toolkit_min_version": "9.9"}, f)
        result = {}
        verify._attach_config_attestation(result)
        ca = result["config_attestation"]
        self.assertTrue(ca["diverged_from_file"])
        self.assertNotEqual(ca["sha256"], ca["file_sha256"])

    def test_absent_attestation_writes_nothing(self):
        result = {}
        verify._attach_config_attestation(result)
        self.assertNotIn("config_attestation", result)

    def test_missing_config_file_is_not_fabricated(self):
        os.remove(self.cfg)
        verify._record_config_attestation(self.project)
        self.assertEqual(verify._CONFIG_ATTESTATION, {})


if __name__ == "__main__":
    unittest.main()
