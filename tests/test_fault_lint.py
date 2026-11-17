"""F-251: 故障路径静态闸 — 每条规则的"报/不报"都要有钉。

规则是启发式的, 价值全在边界: 赋值右值不算丢弃、取值函数不算丢弃、故障上下文
的轮询不算无界等、有实际工作的循环不算等。2026-11-17 首轮在 11 个真工程上
校准过 (校准前的误报: Tetris_HardDrop 的搜索循环、vendor 时钟轮询、Fault_Puts)。
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import fault_lint  # noqa: E402

HDR = "#include <stdint.h>\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proj, True)

    def write(self, rel, body):
        path = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(HDR + body)
        return path

    def rules(self, rel="User/mod.c", body=""):
        self.write(rel, body)
        findings, harsh = fault_lint.lint_project(self.proj)
        return sorted(f["rule"] for f in findings), harsh


class R1UncheckedCall(_Base):
    def test_bare_comm_call_is_flagged(self):
        rules, _ = self.rules(body="""
void f(void) { HAL_I2C_Master_Transmit(0, 0xD0, 0, 1, 10); }
""")
        self.assertIn("R1", rules)

    def test_assignment_and_return_are_not_flagged(self):
        rules, _ = self.rules(body="""
int f(void) {
    int rc = HAL_I2C_Master_Transmit(0, 0xD0, 0, 1, 10);
    return HAL_SPI_Transmit(0, 0, 1, 10);
}
""")
        self.assertNotIn("R1", rules)

    def test_value_and_void_functions_are_not_flagged(self):
        rules, _ = self.rules(body="""
void f(void) {
    HAL_GPIO_WritePin(0, 1, 0);
    (void)HAL_SPI_GetFlagStatus(0, 1);
}
""")
        self.assertNotIn("R1", rules)

    def test_definition_is_not_flagged(self):
        rules, _ = self.rules(body="""
void HAL_I2C_MspInit(void) { }
""")
        self.assertNotIn("R1", rules)


class R2UnboundedWait(_Base):
    def test_empty_poll_loop_is_flagged(self):
        rules, _ = self.rules(body="""
void f(void) { while (SPI_I2S_GetFlagStatus(SPI1, SPI_FLAG_TXE) == RESET) { } }
""")
        self.assertIn("R2", rules)

    def test_dwt_bounded_wait_is_not_flagged(self):
        rules, _ = self.rules(body="""
void f(void) {
    uint32_t start = DWT->CYCCNT;
    while ((DWT->CYCCNT - start) < 72000u) { }
}
""")
        self.assertNotIn("R2", rules)

    def test_loop_with_real_work_is_not_flagged(self):
        rules, _ = self.rules(body="""
int f(void) {
    int y = 0;
    while (!collide(&y)) { y++; counter++; }
    return y;
}
""")
        self.assertNotIn("R2", rules)

    def test_fault_context_polling_is_not_flagged(self):
        rules, _ = self.rules(body="""
static void Fault_Puts(const char *s) {
    while (*s) { while (USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET) { } s++; }
}
""")
        self.assertNotIn("R2", rules)


class R3BlockingInIsr(_Base):
    def test_delay_in_irq_handler_is_flagged(self):
        rules, _ = self.rules(body="""
void TIM2_IRQHandler(void) { HAL_Delay(5); }
""")
        self.assertIn("R3", rules)

    def test_normal_irq_handler_is_not_flagged(self):
        rules, _ = self.rules(body="""
void USART1_IRQHandler(void) { g_rx_ready = 1; }
""")
        self.assertNotIn("R3", rules)

    def test_fault_handlers_are_exempt(self):
        rules, _ = self.rules(body="""
void HardFault_Handler(void) { while (1) { } }
void Error_Handler(void) { while (1) { } }
""")
        self.assertNotIn("R3", rules)


class Suppression(_Base):
    def test_suppression_with_reason_is_silent(self):
        rules, harsh = self.rules(body="""
/* fault-lint:ignore R1 — 探测用的调用, 失败由上层重试 */
void f(void) { HAL_I2C_Master_Transmit(0, 0xD0, 0, 1, 10); }
""")
        self.assertNotIn("R1", rules)
        self.assertEqual(harsh, [])

    def test_suppression_without_reason_is_counted(self):
        rules, harsh = self.rules(body="""
/* fault-lint:ignore R1 */
void f(void) { HAL_I2C_Master_Transmit(0, 0xD0, 0, 1, 10); }
""")
        self.assertNotIn("R1", rules)
        self.assertEqual(len(harsh), 1)


class Scope(_Base):
    def test_system_file_is_skipped(self):
        rules, _ = self.rules(rel="User/system_ch32v30x.c", body="""
void f(void) { while (RCC->CTLR & RCC_HSERDY) { } }
""")
        self.assertNotIn("R2", rules)

    def test_vendor_dirs_are_skipped(self):
        rules, _ = self.rules(rel="Peripheral/src/ch32v30x_flash.c", body="""
void f(void) { while (FLASH->STATR & FLASH_FLAG_BSY) { } }
""")
        self.assertNotIn("R2", rules)

    def test_r4_warns_without_fault_tests(self):
        self.write("User/i2c_bus.c", "void f(void) { }\n")
        findings, _ = fault_lint.lint_project(self.proj)
        self.assertIn("R4", [f["rule"] for f in findings])

    def test_r4_silent_when_fault_test_present(self):
        self.write("User/i2c_bus.c", "void f(void) { }\n")
        self.write("tests/test_fault.c", "/* 用 fault_shim_ 注入故障 */\n")
        findings, _ = fault_lint.lint_project(self.proj)
        self.assertNotIn("R4", [f["rule"] for f in findings])


if __name__ == "__main__":
    unittest.main()
