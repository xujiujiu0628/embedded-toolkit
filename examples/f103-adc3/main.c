/* f103-adc3 — T3 参考型样例 (编译级)。
 * 用途: ADC3 单次软件触发转换核心配置 — 寄存器布局与 ADC1 同构。
 * ref.json anchor: peripherals.ADC3 (base=0x40013C00, 寄存器布局同
 *                  peripherals.ADC1), RCC.APB2ENR bit15=ADC3EN。
 * GAP-D-4: ref.json 无 ADC3 的 _relationships 引脚条目 — 本样例不配
 *          GPIO (通道引脚按目标板线另行确认)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

static void adc3_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_ADC3EN;  /* ref.json RCC.APB2ENR bit15 */
    __DSB();
    ADC3->SMPR2 |= (5UL << 0);           /* CH0: 55.5 cycles (同 ADC1 布局) */
    ADC3->SQR3  = 0;                     /* 序列 1 个转换 = CH0 */
    ADC3->CR2   = 1;                     /* ADON 上电 */
}

static uint16_t adc3_read_ch0(void)
{
    ADC3->CR2 |= (1UL << 22);            /* SWSTART (ref.json ADC1.CR2 位域) */
    while (!(ADC3->SR & (1UL << 1))) {   /* EOC (ref.json ADC1.SR bit1) */
    }
    return (uint16_t)(ADC3->DR & 0xFFFu);
}

int main(void)
{
    adc3_init();
    for (;;) {
        volatile uint16_t raw = adc3_read_ch0();
        (void)raw;
        for (volatile int d = 0; d < 200000; d++) {
        }
    }
}
