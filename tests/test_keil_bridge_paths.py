"""F-069b: _keil_bridge_paths 4 分支覆盖 (H-1 fresh-checker 反馈)

verify.py F-067b 改动新增 _keil_bridge_paths() 函数 (启动时检测 Keil
退役桥路径, 不在则 FileNotFoundError 指向 archive README), 但仓内零
直接单测覆盖 — F-067b 阶段测试全绿不代表该函数行为正确。

4 个分支:
  (a) env=set + 路径在 + 脚本在 → 返 (build_path, analyze_path)
  (b) env=set + 路径不在 → FileNotFoundError 指向 archive
  (c) env=unset + 默认路径不在 → FileNotFoundError
  (d) 路径在但脚本缺失 → FileNotFoundError "脚本缺失"

全部纯 mock (env-var / temp dir), 不触 archive 物理副本。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

# 与 test_writeback_guards / test_gcc_build 同口径: 把 scripts/ 加进 path
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import verify  # noqa: E402


class KeilBridgePathsTests(unittest.TestCase):

    def setUp(self):
        # 保存 env 状态, 测完恢复
        self._env_backup = os.environ.get("EMBEDDED_TOOLKIT_KEIL_ARCHIVE")

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("EMBEDDED_TOOLKIT_KEIL_ARCHIVE", None)
        else:
            os.environ["EMBEDDED_TOOLKIT_KEIL_ARCHIVE"] = self._env_backup

    def test_a_env_set_path_exists_scripts_present(self):
        # (a) env set + path exists + scripts present
        tmp = tempfile.mkdtemp()
        try:
            sk_dir = os.path.join(tmp, "scripts_legacy_keil")
            os.makedirs(sk_dir)
            build = os.path.join(sk_dir, "keil_build.py")
            analyze = os.path.join(sk_dir, "keil_analyze.py")
            with open(build, "w", encoding="utf-8") as f:
                f.write("# stub\n")
            with open(analyze, "w", encoding="utf-8") as f:
                f.write("# stub\n")
            with mock.patch.object(verify, "KEIL_BRIDGE_DIR", tmp):
                b, a = verify._keil_bridge_paths()
            self.assertEqual(b, build)
            self.assertEqual(a, analyze)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_b_env_set_path_missing_raises(self):
        # (b) env set + path missing → FileNotFoundError
        with mock.patch.object(verify, "KEIL_BRIDGE_DIR",
                               r"C:\does\not\exist\keil-bridge-20260905"):
            with self.assertRaises(FileNotFoundError) as cm:
                verify._keil_bridge_paths()
        msg = str(cm.exception)
        self.assertIn("Keil 退役桥不在", msg)
        self.assertIn("EMBEDDED_TOOLKIT_KEIL_ARCHIVE", msg)
        # F-069a 整改: 错误信息应引导用户替换占位符
        self.assertIn("占位符", msg)

    def test_c_env_unset_default_missing_raises(self):
        # (c) env unset + default path missing → FileNotFoundError
        os.environ.pop("EMBEDDED_TOOLKIT_KEIL_ARCHIVE", None)
        with mock.patch.object(verify, "KEIL_BRIDGE_DIR",
                               r"C:\does\not\exist\default-archive"):
            with self.assertRaises(FileNotFoundError) as cm:
                verify._keil_bridge_paths()
        msg = str(cm.exception)
        self.assertIn("Keil 退役桥不在", msg)

    def test_d_path_exists_scripts_missing_raises(self):
        # (d) path exists but scripts missing → FileNotFoundError "脚本缺失"
        tmp = tempfile.mkdtemp()
        try:
            sk_dir = os.path.join(tmp, "scripts_legacy_keil")
            os.makedirs(sk_dir)
            # 故意不建 keil_build.py / keil_analyze.py
            with mock.patch.object(verify, "KEIL_BRIDGE_DIR", tmp):
                with self.assertRaises(FileNotFoundError) as cm:
                    verify._keil_bridge_paths()
            msg = str(cm.exception)
            self.assertIn("脚本缺失", msg)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
