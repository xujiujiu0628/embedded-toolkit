r"""F-178 (WB-20260920-04, H-3) gen_periph spi burst 排空读回归钉。

契约 (RM0008 §25.3.5 SPI 单缓冲接收语义):
  1. `spiN_write_burst` 每写一字节 DR 之后**必须**等待 RXNE 并读回 DR。
     SPI 接收是单缓冲: 读 DR 才清 RXNE; RXNE 未清时下一字节到达只置 OVR
     并把该字节丢弃。旧生成体只写不读 → burst 收尾缓冲里滞留最后一个陈旧
     字节且 OVR=1, 随后 `spiN_transfer` 的 wait-RXNE 立即通过、返回 burst
     残留字节, 本次真收到的字节被 OVR 丢弃, 且 OVR 无人清理永不自愈
     ("发命令再收数据"的传感器序列全体错位);
  2. `spiN_transfer` **一字不动** — 排空读只加在 burst 上, 不改既有点断言
     形态 (行为保持型变更的钉子);
  3. 仓内样例 `examples/f103-spi1|2` 的 burst 函数体必须与生成器**现输出**
     逐字节一致 (生成器↔样例漂移守卫); `f103-spi3` 系 SPI2 生成物手工适配
     (生成器不支持 SPI3, GAP-G-1), 按**注释与实例名归一化**后须与生成体
     同形;
  4. 三个 spi 样例目录仍落在样例工厂 (`test_sample_factory`) 的巡检范围内。

诚实注记: 本文件全部为**生成物静态断言**(RM0008 语义推导 + 文本确认),
未真机复现 (简报禁线上板); 寄存器级行为由样例工程的 `make all` 编译级
巡检与下游工程背书。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gen_periph  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")

# 生成器 CLI 级调用参数 (与样例 README 声明的生成命令同源)
SPI_ARGS = {
    "SPI1": dict(mode=0, nss="PA4", sck="PA5", miso="PA6", mosi="PA7",
                 baud_div=8),
    "SPI2": dict(mode=0, nss="PB12", sck="PB13", miso="PB14", mosi="PB15",
                 baud_div=8),
}

# spiN_transfer 的特征文本: H-3 明确要求"一字不动", 逐字节钉死。
TRANSFER_BODY = (
    "    while (!(%(p)s->SR & (1<<1)));  // wait TXE\n"
    "    %(p)s->DR = tx_byte;\n"
    "    while (!(%(p)s->SR & (1<<0)));  // wait RXNE\n"
    "    return %(p)s->DR;"
)


def _gen(periph):
    return gen_periph.gen_spi(periph, **SPI_ARGS[periph])


def _fn_body(text, periph, name):
    """抓 `static <ret> <name>(...)... {` 到行首 `}` 之间的函数体。"""
    m = re.search(
        r"static \w+ %s\((?:[^)]*)\) \{(.*?)\n\}" % re.escape(name),
        text, re.DOTALL)
    return m.group(1) if m else None


def _burst_body(text, n):
    return _fn_body(text, n, "spi%d_write_burst" % n)


def _dr_reads(body, periph):
    """函数体里的**读** DR 行 (排除 `X->DR = ...` 这种写)。"""
    reads = []
    for line in body.splitlines():
        if "%s->DR" % periph not in line:
            continue
        if re.search(r"%s->DR\s*=" % re.escape(periph), line):
            continue
        reads.append(line.strip())
    return reads


def _normalize(body):
    """去注释 + 实例名归一 (SPI1/spi1 → SPIX/spiX) + 压空白 — 用于
    手工适配样例 (f103-spi3 注释风格为 /* */) 的同形比对。"""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    body = re.sub(r"SPI\d", "SPIX", body)
    body = re.sub(r"spi\d", "spiX", body)
    return [" ".join(x.split()) for x in body.splitlines() if x.split()]


def _read(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


class BurstDrainsRxTests(unittest.TestCase):
    """契约 1: 生成的 burst 必须逐字节排空 DR。"""

    def test_spi1_burst_contains_dr_read(self):
        body = _burst_body(_gen("SPI1"), 1)
        self.assertIsNotNone(body, "spi1_write_burst 未生成")
        self.assertTrue(_dr_reads(body, "SPI1"),
                        "spi1_write_burst 全文无 ->DR 读 (只写不读 → OVR 滞留)")

    def test_spi2_burst_contains_dr_read(self):
        body = _burst_body(_gen("SPI2"), 2)
        self.assertIsNotNone(body, "spi2_write_burst 未生成")
        self.assertTrue(_dr_reads(body, "SPI2"),
                        "spi2_write_burst 全文无 ->DR 读 (只写不读 → OVR 滞留)")

    def test_burst_waits_rxne_before_draining(self):
        # 排空读必须**先等 RXNE** 再读 —— 直接读 DR 会读到上一次的残留,
        # 且读早了并不解除"该字节尚未到达"的状态。
        body = _burst_body(_gen("SPI1"), 1)
        zero_bit = [ln.strip() for ln in body.splitlines()
                    if "SPI1->SR & (1<<0)" in ln]
        self.assertTrue(zero_bit, "burst 缺 wait-RXNE (SR bit0) 步骤")

    def test_burst_drain_is_inside_the_loop(self):
        # 排空读必须在 for 循环体内 —— 循环外补一次只能清最后一个字节,
        # 中间字节照样被 OVR 丢弃。
        body = _burst_body(_gen("SPI1"), 1)
        idx_for = body.index("for (int i")
        idx_end = body.rindex("}")            # for 循环闭合
        inner = body[idx_for:idx_end]
        self.assertTrue(_dr_reads(inner, "SPI1"),
                        "排空读不在 for 循环体内 — 中间字节仍会被 OVR 丢弃")


class TransferUntouchedTests(unittest.TestCase):
    """契约 2: spiN_transfer 一字不动 (特征文本逐字节钉)。"""

    def test_spi1_transfer_body_pinned(self):
        body = _fn_body(_gen("SPI1"), "SPI1", "spi1_transfer")
        self.assertEqual(body, "\n" + TRANSFER_BODY % {"p": "SPI1"})

    def test_spi2_transfer_body_pinned(self):
        body = _fn_body(_gen("SPI2"), "SPI2", "spi2_transfer")
        self.assertEqual(body, "\n" + TRANSFER_BODY % {"p": "SPI2"})


class SampleDriftGuardTests(unittest.TestCase):
    """契约 3 + 4: 样例生成物与生成器现输出同源。"""

    def test_spi1_sample_matches_generator_output(self):
        gen_body = _burst_body(_gen("SPI1"), 1)
        sample = _read(os.path.join(EXAMPLES, "f103-spi1", "main.c"))
        self.assertEqual(_burst_body(sample, 1), gen_body,
                         "examples/f103-spi1 的 burst 体与生成器现输出漂移")

    def test_spi2_sample_matches_generator_output(self):
        gen_body = _burst_body(_gen("SPI2"), 2)
        sample = _read(os.path.join(EXAMPLES, "f103-spi2", "main.c"))
        self.assertEqual(_burst_body(sample, 2), gen_body,
                         "examples/f103-spi2 的 burst 体与生成器现输出漂移")

    def test_spi1_sample_transfer_also_untouched(self):
        sample = _read(os.path.join(EXAMPLES, "f103-spi1", "main.c"))
        self.assertEqual(
            _fn_body(sample, "SPI1", "spi1_transfer"),
            "\n" + TRANSFER_BODY % {"p": "SPI1"})

    def test_spi3_sample_burst_same_shape_as_generator(self):
        # f103-spi3 = SPI2 生成物 + 三处手工适配 (GAP-G-1); 注释风格与实例名
        # 已被适配改写, 故按归一化后同形比对。
        gen_norm = _normalize(_burst_body(_gen("SPI2"), 2))
        sample = _read(os.path.join(EXAMPLES, "f103-spi3", "main.c"))
        self.assertEqual(_normalize(_burst_body(sample, 3)), gen_norm,
                         "f103-spi3 的 burst 体与生成体不同形")

    def test_samples_burst_contain_dr_read(self):
        # 仓内样例也是"生成物" —— 只改生成器而忘记重生成样例, 样例里就仍
        # 躺着只写不读的 burst (AI 消费方照抄的正是样例)。三条一并咬住。
        for name, n, periph in (("f103-spi1", 1, "SPI1"),
                                ("f103-spi2", 2, "SPI2"),
                                ("f103-spi3", 3, "SPI3")):
            with self.subTest(sample=name):
                sample = _read(os.path.join(EXAMPLES, name, "main.c"))
                body = _burst_body(sample, n)
                self.assertIsNotNone(body, name + ": burst 未找到")
                self.assertTrue(
                    _dr_reads(body, periph),
                    "%s: 样例 burst 全文无 ->DR 读 (H-3 未落到样例)" % name)

    def test_spi_samples_are_in_factory_sweep(self):
        # 契约 4: 三个样例目录必须仍在样例工厂巡检范围内 (目录存在 +
        # 命名前缀 f103- ⇒ 被 _sample_dirs() 采集)。
        for name in ("f103-spi1", "f103-spi2", "f103-spi3"):
            d = os.path.join(EXAMPLES, name)
            self.assertTrue(os.path.isdir(d), "样例目录缺失: " + d)
            self.assertTrue(os.path.isfile(os.path.join(d, "main.c")), d)
            self.assertTrue(os.path.isfile(os.path.join(d, "Makefile")), d)


if __name__ == "__main__":
    unittest.main()
