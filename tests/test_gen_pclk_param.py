r"""WB-20260920-01: gen_periph ``--pclk1/--pclk2`` 时钟树参数化回归钉 (F-110 下半场)。

结构镜像 tests/test_gen_hclk_param.py (F-110) 的四种钉形:
  ① 金矩阵默认兼容钉 (本文件 commit1, 基线上先绿) —— tests/fixtures/
     pclk_golden.json 为基线 c0df0c6 上 capture-once 的 9 组代表参数 ×
     {缺省, --hclk 8, --hclk 72 显式} 全量输出; 拆分后"不传 pclk = 与
     基线逐字节一致"由本类逐条复跑比对 (第一契约)。
  ② 派生函数钉 —— apb_clock_mhz 的 pclk 覆盖参数 + tim_kernel_clock_mhz
     (APB1×2 规则随 --pclk1 派生, RM0008 §7.3.7)。
  ③ 优先级钉 —— 显式 --tim-clk > pclk1 派生 > hclk 推导; 显式 pclk > 推导。
  ④ 域边界钉 —— pclk2∈[1,72]∧≤hclk / pclk1∈[1,36]∧≤hclk (36=APB1 规格
     上限, RM0008 数据手册值, ref.json 未登记 — GAP-D-4 架构常量), 越界/
     非整数 → ERROR 非零退出 (F-103, 不静默回落); systick 不受 pclk 扰动钉。
  ⑤ P1 (L-5) —— hclk=2 × i2c 400k 病态 (CCR clamp 4 假装 400kHz +
     CR2.FREQ=1) 既有测试未钉 (2026-09-20 grep 取证: 仅钉默认 72 输出)
     → 改显式 ERROR 并钉。
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "gen_periph.py")
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "fixtures", "pclk_golden.json")


def _run_cli(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT] + argv, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
        cwd=os.path.dirname(os.path.abspath(__file__)) or None)


class GoldenMatrixTests(unittest.TestCase):
    """① 第一契约: 不传 --pclk1/--pclk2 时, 全部金矩阵条目与基线逐字节一致。

    fixture 每条含基线 (c0df0c6, 参数化之前) 的 CLI stdout; 本类在拆分前后
    都逐条复跑比对 —— 拆分若扰动默认路径, 此处立即红。"""

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, encoding="utf-8") as f:
            cls.golden = json.load(f)
        cls.entries = {k: v for k, v in cls.golden.items() if not k.startswith("_")}

    def test_matrix_covers_nine_groups_x_three_variants(self):
        self.assertEqual(len(self.entries), 27)

    def test_default_path_reproduces_baseline_byte_for_byte(self):
        for key, entry in sorted(self.entries.items()):
            with self.subTest(entry=key):
                r = _run_cli(entry["argv"])
                self.assertEqual(r.returncode, 0,
                                 f"{key}: rc={r.returncode}\n{r.stdout[:300]}")
                self.assertEqual(
                    r.stdout, entry["output"],
                    f"{key}: 默认输出偏离基线金矩阵 (第一契约破约)")

    def test_explicit_72_equals_default(self):
        """--hclk 72 显式 == 缺省 (F-110 兼容契约在金矩阵上的延伸)。"""
        for label in {k.rsplit("_", 1)[0] for k in self.entries}:
            with self.subTest(label=label):
                d = _run_cli(self.entries[f"{label}_default"]["argv"])
                s = _run_cli(self.entries[f"{label}_hclk72"]["argv"])
                self.assertEqual(d.stdout, s.stdout, label)


if __name__ == "__main__":
    unittest.main()
