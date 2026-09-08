r"""生成代码中断安全模式钉 (F-080)。

F-071/F-079 钉的是寄存器数学, 本文件钉中断相关生成的最低安全配置——
这些模式丢了不报编译错, 但在 -O2 下是死循环或 ISR 永不触发 (C 类):

  1. ISR 共享变量必须 volatile: gen_systick 的 tick_ms 丢了 volatile,
     delay_ms 在 -O2 下读寄存器缓存值 → 永久死循环;
  2. delay 必须让核睡眠: __WFI 缺失 = 忙等烧 CPU;
  3. SysTick 必须开 TICKINT (否则 tick_ms 永不走);
  4. 定时器 ISR 必须先查更新标志再清标志 (顺序 + 归属: 清除动作
     必须在 if 体内), 且 DIER 更新中断使能必须落行。

只断言生成文本模式, 不动生产代码; 与 F-071 的 IRQ 编号钉互补不重复。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402


class SystickInterruptSafetyTests(unittest.TestCase):

    def setUp(self):
        self.out = gen_periph.gen_systick(1000)
        self.lines = self.out.splitlines()

    def test_isr_shared_variable_is_volatile(self):
        self.assertIn("static volatile uint32_t tick_ms;", self.out)

    def test_delay_sleeps_via_wfi(self):
        self.assertIn("while ((tick_ms - start) < ms) { __WFI(); }", self.out)

    def test_systick_control_enables_tickint(self):
        ctrl = [l for l in self.lines if "SysTick->CTRL" in l]
        self.assertEqual(len(ctrl), 1)
        for bit in ("SysTick_CTRL_ENABLE", "SysTick_CTRL_TICKINT",
                    "SysTick_CTRL_CLKSOURCE"):
            self.assertIn(bit, ctrl[0])


class TimerIrqSafetyTests(unittest.TestCase):

    def setUp(self):
        self.out = gen_periph.gen_timer_int("TIM2", 1, 72)
        self.lines = self.out.splitlines()

    def test_update_interrupt_enabled(self):
        self.assertIn("TIM2->DIER = 1;", self.out)

    def test_flag_checked_then_cleared_inside_if_body(self):
        """清除动作必须在 if (SR & 1) 体内且先于业务 TODO —
        清在体外=每次中断都清, 清在 TODO 后=业务慢了丢标志。"""
        idx_check = next(i for i, l in enumerate(self.lines)
                         if "if (TIM2->SR & 1)" in l)
        idx_clear = next(i for i, l in enumerate(self.lines)
                         if "TIM2->SR &= ~1;" in l)
        idx_todo = next(i for i, l in enumerate(self.lines) if "TODO" in l)
        self.assertLess(idx_check, idx_clear,
                        f"ISR 顺序被破坏: check@{idx_check} clear@{idx_clear}")
        self.assertLess(idx_clear, idx_todo,
                        f"清标志必须先于业务 TODO: clear@{idx_clear} "
                        f"todo@{idx_todo}")

    def test_handler_name_follows_cmsis_vector_naming(self):
        # 向量表名错 = 中断静默不触发 (链接器不报错)
        self.assertIn("void TIM2_IRQHandler(void) {", self.out)


class Timer1VectorNameTests(unittest.TestCase):
    """F-086 缺陷 1 修复钉: TIM1 的 CMSIS 向量名是 TIM1_UP_IRQ*。

    STM32F103 事实 (RM0008/CMSIS): bit25 = TIM1_UP_IRQn，向量表函数
    TIM1_UP_IRQHandler；TIM1_IRQHandler / TIM1_IRQn 均不存在——生成物
    编译链接都不报错（弱默认处理函数接管），ISR 永不执行（C 类静默）。
    """

    def setUp(self):
        self.out = gen_periph.gen_timer_int("TIM1", 10, 72)

    def test_handler_is_tim1_up_irqhandler(self):
        self.assertIn("void TIM1_UP_IRQHandler(void) {", self.out)
        self.assertNotIn("TIM1_IRQHandler", self.out)

    def test_iser_comment_names_tim1_up_irqn(self):
        self.assertIn("NVIC->ISER[0] = (1UL << 25);", self.out)
        self.assertIn("// TIM1_UP_IRQn = 25", self.out)
        self.assertNotIn("TIM1_IRQn =", self.out)

    def test_tim2_3_4_vector_names_unchanged(self):
        # 修复不得波及 TIM2~4 的常规命名
        out3 = gen_periph.gen_timer_int("TIM3", 1, 72)
        self.assertIn("void TIM3_IRQHandler(void) {", out3)
        self.assertIn("// TIM3_IRQn = 29", out3)


if __name__ == "__main__":
    unittest.main()
