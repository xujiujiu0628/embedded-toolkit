import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import wb_common  # noqa: E402


class TestFindProjectRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_workbench_config_in_cwd(self):
        wb = os.path.join(self.tmp, ".workbench")
        os.makedirs(wb)
        open(os.path.join(wb, "config.json"), "w").close()
        self.assertEqual(wb_common.find_project_root(self.tmp), self.tmp)

    def test_walks_up_to_ancestor(self):
        proj = os.path.join(self.tmp, "proj")
        wb = os.path.join(proj, ".workbench")
        os.makedirs(wb)
        open(os.path.join(wb, "config.json"), "w").close()
        sub = os.path.join(proj, "a", "b")
        os.makedirs(sub)
        self.assertEqual(wb_common.find_project_root(sub), proj)

    def test_legacy_embeddedskills_fallback(self):
        old = os.path.join(self.tmp, ".embeddedskills")
        os.makedirs(old)
        open(os.path.join(old, "config.json"), "w").close()
        self.assertEqual(wb_common.find_project_root(self.tmp), self.tmp)

    def test_none_when_no_config(self):
        self.assertIsNone(wb_common.find_project_root(self.tmp))


class TestVersionOk(unittest.TestCase):
    def test_equal(self):
        self.assertTrue(wb_common.version_ok("0.1", "0.1"))

    def test_newer(self):
        self.assertTrue(wb_common.version_ok("0.2", "0.1"))

    def test_older(self):
        self.assertFalse(wb_common.version_ok("0.1", "0.2"))

    def test_major_step(self):
        self.assertTrue(wb_common.version_ok("1.0", "0.9"))


if __name__ == "__main__":
    unittest.main()
