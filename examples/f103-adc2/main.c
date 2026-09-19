/* f103-adc2 — T1 样例 (编译级)。
 * 用途: ADC2 CH0 (PA0) 单次软件触发采样最小样例。
 * 生成方式: gen_periph --type adc --adc ADC2 --ch 0 --pin PA0
 * ref.json anchor: peripherals.ADC2 (注: _relationships 无 ADC2 引脚条目, CH0=PA0 通用)
 * 组装变换: 仅两处 — ①生成体裸语句包入 adc2_init(); ②static 函数/ISR/
 * #define 保持原文落文件作用域。生成行未做任何缩进或措辞修改。
 */
#include "f103_regs.h"

/* ── 生成体 (gen_periph 原文, 文件作用域定义) ── */
/* 4. 单次转换 */
static uint16_t adc_read_ch0(void) {
    ADC2->CR2 |= (1UL << 22);    // SWSTART
    while (!(ADC2->SR & 2));    // 等待 EOC
    return ADC2->DR & 0xFFF;     // 12-bit result
}

/* 5. 电压换算 (Vref=3.3V) */
static uint32_t adc_to_mv(uint16_t val) {
    return (uint32_t)val * 3300 / 4096;
}

/* ── 生成体 (gen_periph 原文, 裸语句仅包入 init 函数, 行保持原文) ── */
static void adc2_init(void) {
/* ========================================================================
 * ADC2 CH0 — PA0 (single conversion, 12-bit)
 * ======================================================================== */

/* 1. 时钟使能 */
RCC->APB2ENR |= RCC_APB2ENR_ADC2EN | RCC_APB2ENR_IOPAEN;
__DSB();

/* 1b. ADC 时钟分频 — ADCPRE=/6 (12MHz @ PCLK2=72MHz, ≤14MHz 上限) */
RCC->CFGR &= ~(3UL << 14);         // 清 ADCPRE[1:0]
RCC->CFGR |=  (2UL << 14);         // ADCPRE=10b → PCLK2/6

/* 2. GPIO — PA0 模拟输入 */
GPIOA->CRL &= ~(0xFUL << 0);
// CNF=00 MODE=00 → 模拟输入

/* 3. ADC 配置 (单次转换, 软件触发) */
// 采样时间: 55.5 cycles (推荐用于 12-bit 精度)
ADC2->SMPR2 |= (5UL << 0);  // CH0: 55.5 cycles
ADC2->SQR3 = 0;                 // 转换序列: 1 个通道 = CH0
ADC2->CR2 = 1;                    // ADON 上电

}


int main(void)
{
    adc2_init();
    for (;;) {
        volatile uint16_t last_mv = adc_to_mv(adc_read_ch0());
        (void)last_mv;
        for (volatile int d = 0; d < 200000; d++) {
        }
    }
}
