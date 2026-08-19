#!/usr/bin/env python3
"""
STM32F103 外设代码生成器 — 参数 → 寄存器级 C init 代码

用法:
    python gen_periph.py --type pwm --timer TIM2 --ch 1 --pin PA0 --freq 1000 --duty 50
    python gen_periph.py --type usart --usart USART1 --baud 115200 --tx PA9 --rx PA10
    python gen_periph.py --type adc --adc ADC1 --ch 1 --pin PA1
    python gen_periph.py --type gpio --pin PC13 --mode out-pp-50mhz
    python gen_periph.py --type systick --freq 1000
    python gen_periph.py --type timer-int --timer TIM2 --period-ms 1

依赖: stm32f103-ref.json (寄存器定义 + 配方参考)
"""

import argparse
import json
import os
import sys

from wb_common import TOOLKIT_ROOT, find_project_root

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")


def load_ref():
    with open(REF_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


# ---- GPIO 引脚地址映射 ----
GPIO_BASE = {"A": "GPIOA", "B": "GPIOB", "C": "GPIOC"}
GPIO_CLOCK_BIT = {"A": "IOPAEN", "B": "IOPBEN", "C": "IOPCEN"}
GPIO_CR_OFFSET = {"0-7": "CRL", "8-15": "CRH"}

# ---- TIM 通道 → 引脚映射 (默认复用映射) ----
TIM_CH_PINS = {
    ("TIM2", 1): "PA0", ("TIM2", 2): "PA1", ("TIM2", 3): "PA2", ("TIM2", 4): "PA3",
    ("TIM3", 1): "PA6", ("TIM3", 2): "PA7", ("TIM3", 3): "PB0", ("TIM3", 4): "PB1",
    ("TIM4", 1): "PB6", ("TIM4", 2): "PB7", ("TIM4", 3): "PB8", ("TIM4", 4): "PB9",
}

# ---- TIM 基址和时钟映射 ----
TIM_CLOCK_BIT = {"TIM2": "TIM2EN", "TIM3": "TIM3EN", "TIM4": "TIM4EN"}

# ---- I2C 时钟映射 ----
I2C_CLOCK_BIT = {
    "I2C1": ("APB1ENR", "I2C1EN", 21),
    "I2C2": ("APB1ENR", "I2C2EN", 22),
}

# ---- SPI 时钟映射 ----
SPI_CLOCK_BIT = {
    "SPI1": ("APB2ENR", "SPI1EN", 12, 72),  # bus_reg, bit_name, bit_num, pclk_mhz
    "SPI2": ("APB1ENR", "SPI2EN", 14, 36),
}

# ---- SPI 分频表 (BR[2:0]) ----
SPI_BAUD_DIV = {2: 0, 4: 1, 8: 2, 16: 3, 32: 4, 64: 5, 128: 6, 256: 7}

# ---- I2C 速度模式 ----
I2C_SPEED_MODES = {
    100000: ("standard", False, False),   # SM, DUTY=0, F/S=0
    400000: ("fast", True, False),         # FM, DUTY=0, F/S=1
}

# ---- 引脚号提取 ----
def pin_port(pin: str) -> str:
    """PA0 → A, PC13 → C"""
    return pin[1] if pin[1].isdigit() else pin[1:2]

def pin_num(pin: str) -> int:
    """PA0 → 0, PC13 → 13"""
    m = __import__('re').search(r'(\d+)', pin)
    return int(m.group(1)) if m else 0

def pin_cr_shift(pin: str) -> int:
    """引脚在 CRL/CRH 中的位移: PA0→0, PC13→20"""
    n = pin_num(pin)
    return (n % 8) * 4

def pin_cr_reg(pin: str) -> str:
    """PA0→CRL, PC13→CRH"""
    return "CRH" if pin_num(pin) >= 8 else "CRL"


# ============================================================
# 代码生成函数
# ============================================================

def gen_gpio(pin: str, mode: str) -> str:
    """生成 GPIO 引脚配置代码"""
    port = pin_port(pin)
    port_base = GPIO_BASE.get(port, f"GPIO{port}")
    clock_bit = GPIO_CLOCK_BIT.get(port, f"IOP{port}EN")
    cr_reg = pin_cr_reg(pin)
    shift = pin_cr_shift(pin)

    # 模式映射
    mode_map = {
        "out-pp-50mhz":  ("0x3", "通用推挽输出 50MHz"),
        "out-pp-2mhz":   ("0x2", "通用推挽输出 2MHz"),
        "out-od-50mhz":  ("0x7", "通用开漏输出 50MHz"),
        "af-pp-50mhz":   ("0xB", "复用推挽输出 50MHz (UART TX / PWM)"),
        "af-od-50mhz":   ("0xF", "复用开漏输出 50MHz (I2C)"),
        "in-floating":   ("0x4", "浮空输入"),
        "in-pullup":     ("0x8", "上拉输入"),
        "in-analog":     ("0x0", "模拟输入 (ADC)"),
    }
    mode_val, mode_desc = mode_map.get(mode, ("0x3", mode))

    lines = []
    lines.append(f"/* {pin} — {mode_desc} */")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{clock_bit};")
    lines.append(f"__DSB();")
    lines.append(f"{port_base}->{cr_reg} &= ~(0xFUL << {shift});")
    lines.append(f"{port_base}->{cr_reg} |=  ({mode_val}UL << {shift});")
    return "\n".join(lines)


def gen_systick(freq_hz: int) -> str:
    """生成 SysTick 配置代码 (假设 72MHz 内核时钟)"""
    if 72000000 % freq_hz != 0:
        return f"/* ERROR: 72MHz / {freq_hz} is not an integer. Choose a divisor of 72MHz. */"

    load = 72000000 // freq_hz - 1
    period_us = 1000000 // freq_hz

    lines = []
    lines.append(f"/* SysTick — {freq_hz}Hz ({period_us}us interval), 72MHz core clock */")
    lines.append(f"SysTick->LOAD = {load};         // 72MHz/{freq_hz} - 1")
    lines.append(f"SysTick->VAL  = 0;")
    lines.append(f"SysTick->CTRL = SysTick_CTRL_ENABLE | SysTick_CTRL_TICKINT | SysTick_CTRL_CLKSOURCE;")
    lines.append(f"")
    lines.append(f"/* SysTick ISR */")
    lines.append(f"void SysTick_Handler(void) {{")
    lines.append(f"    // called every {period_us}us")
    lines.append(f"}}")
    lines.append(f"")
    lines.append(f"/* 基于 SysTick 的延时函数 */")
    lines.append(f"static volatile uint32_t tick_ms;")
    lines.append(f"void delay_ms(uint32_t ms) {{")
    lines.append(f"    uint32_t start = tick_ms;")
    lines.append(f"    while ((tick_ms - start) < ms) {{ __WFI(); }}")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_usart(usart: str, baud: int, tx: str, rx: str) -> str:
    """生成 USART 初始化代码"""
    usart_n = usart[-1]  # "1", "2", "3"
    bus = "APB2" if usart_n == "1" else "APB1"
    pclk_mhz = 72 if bus == "APB2" else 36

    # 波特率计算
    div = pclk_mhz * 1000000 / (16 * baud)
    mantissa = int(div)
    fraction = round((div - mantissa) * 16)
    brr = (mantissa << 4) | fraction

    tx_port = pin_port(tx)
    rx_port = pin_port(rx)
    tx_shift = pin_cr_shift(tx)
    rx_shift = pin_cr_shift(rx)

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {usart} — {baud} baud, 8N1, TX={tx} RX={rx}")
    lines.append(f" * PCLK{bus[-1].lower()}={pclk_mhz}MHz, BRR=0x{brr:04X} ({mantissa}.{fraction}/16)")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. 时钟使能 */")
    lines.append(f"RCC->APB{bus[-1]}ENR |= RCC_APB{bus[-1]}ENR_{usart}EN;")
    for port in sorted(set([tx_port, rx_port])):
        lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{port}EN;")
    lines.append(f"__DSB();")
    lines.append(f"")
    lines.append(f"/* 2. GPIO 配置 */")
    lines.append(f"// {tx} = {usart}_TX (复用推挽 50MHz)")
    lines.append(f"GPIO{tx_port}->CRH &= ~(0xFUL << {tx_shift});")
    lines.append(f"GPIO{tx_port}->CRH |=  (0xBUL << {tx_shift});")
    lines.append(f"// {rx} = {usart}_RX (浮空输入)")
    lines.append(f"GPIO{rx_port}->CRH &= ~(0xFUL << {rx_shift});")
    lines.append(f"GPIO{rx_port}->CRH |=  (0x4UL << {rx_shift});")
    lines.append(f"")
    lines.append(f"/* 3. USART 配置 */")
    lines.append(f"{usart}->BRR = 0x{brr:04X};")
    lines.append(f"{usart}->CR1 = USART_CR1_TE | USART_CR1_RE;")
    lines.append(f"{usart}->CR1 |= USART_CR1_UE;")
    lines.append(f"")
    lines.append(f"/* 4. printf 重定向 (Microlib fputc) */")
    lines.append(f"int fputc(int ch, FILE *f) {{")
    lines.append(f"    while (!({usart}->SR & (1UL<<7)));  // wait TXE")
    lines.append(f"    {usart}->DR = (uint8_t)ch;")
    lines.append(f"    return ch;")
    lines.append(f"}}")
    lines.append(f"")
    lines.append(f"/* 5. 轮询读写 */")
    lines.append(f"static void uart_putc(uint8_t byte) {{")
    lines.append(f"    while (!({usart}->SR & (1UL<<7)));")
    lines.append(f"    {usart}->DR = byte;")
    lines.append(f"}}")
    lines.append(f"static uint8_t uart_getc(void) {{")
    lines.append(f"    while (!({usart}->SR & (1UL<<5)));  // wait RXNE")
    lines.append(f"    return {usart}->DR;")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_pwm(timer: str, ch: int, pin: str, freq: int, duty: int,
            tim_clk_mhz: int = 72) -> str:
    """生成 PWM 初始化代码"""
    # 确定默认引脚
    default_pin = TIM_CH_PINS.get((timer, ch), pin)
    pin = pin or default_pin
    port = pin_port(pin)
    shift = pin_cr_shift(pin)

    # 计算 PSC 和 ARR
    # PWM_freq = TIM_CLK / ((PSC+1) * (ARR+1))
    # 选择 ARR 为合理的 16 位值, 使 PSC 为整数
    best_arr = 999
    best_psc = None
    for arr in [999, 1999, 4999, 9999, 19999, 49999, 65535]:
        if arr > 65535:
            continue
        psc_float = (tim_clk_mhz * 1_000_000) / (freq * (arr + 1)) - 1
        if psc_float >= 0 and psc_float == int(psc_float) and psc_float <= 65535:
            best_arr = arr
            best_psc = int(psc_float)
            break

    if best_psc is None:
        # 找不到整除组合，用最接近的
        best_arr = 999
        best_psc = int((tim_clk_mhz * 1_000_000) / (freq * (best_arr + 1)) - 1)
        best_psc = max(0, min(65535, best_psc))
        actual_freq = (tim_clk_mhz * 1_000_000) / ((best_psc + 1) * (best_arr + 1))
        freq_note = f"(target {freq}Hz, actual ~{actual_freq:.0f}Hz)"
    else:
        freq_note = ""

    ccr = round((best_arr + 1) * duty / 100)

    # Timer 时钟位
    tim_clock = TIM_CLOCK_BIT.get(timer, f"{timer}EN")
    port_clock = GPIO_CLOCK_BIT.get(port, f"IOP{port}EN")

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {timer} CH{ch} PWM — {pin}, {freq}Hz, {duty}% duty")
    lines.append(f" * TIM_CLK={tim_clk_mhz}MHz, PSC={best_psc}, ARR={best_arr}, CCR{ch}={ccr} {freq_note}")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. 时钟使能 */")
    lines.append(f"RCC->APB1ENR |= RCC_APB1ENR_{tim_clock};")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{port_clock};")
    lines.append(f"__DSB();")
    lines.append(f"")
    lines.append(f"/* 2. GPIO — {pin} 复用推挽 50MHz */")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} &= ~(0xFUL << {shift});")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} |=  (0xBUL << {shift});")
    lines.append(f"")
    lines.append(f"/* 3. Timer 配置 */")
    lines.append(f"{timer}->PSC = {best_psc};            // {tim_clk_mhz}MHz/({best_psc}+1) = {tim_clk_mhz*1000000//(best_psc+1)}Hz")
    lines.append(f"{timer}->ARR = {best_arr};           // → {freq}Hz")
    lines.append(f"{timer}->CCR{ch} = {ccr};            // {duty}% duty")
    # CCMR 配置 (CH1/2 用 CCMR1, CH3/4 用 CCMR2)
    if ch <= 2:
        ccmr = "CCMR1"
        ch_shift = (ch - 1) * 8
    else:
        ccmr = "CCMR2"
        ch_shift = (ch - 3) * 8
    ocxm_shift = ch_shift + 4   # OCxM is at bits [ch_shift+6 : ch_shift+4]
    ocxpe_shift = ch_shift + 3  # OCxPE is at bit ch_shift+3
    lines.append(f"{timer}->{ccmr} = (6<<{ocxm_shift}) | (1<<{ocxpe_shift});  // CH{ch}: PWM mode 1, preload")
    lines.append(f"{timer}->CCER  |= (1<<{(ch-1)*4});           // CH{ch} output enable")
    lines.append(f"{timer}->CR1 = (1<<7) | 1;        // ARPE + enable")
    return "\n".join(lines)


def gen_adc(adc: str, ch: int, pin: str) -> str:
    """生成 ADC 初始化 + 单次转换代码"""
    port = pin_port(pin)
    shift = pin_cr_shift(pin)

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {adc} CH{ch} — {pin} (single conversion, 12-bit)")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. 时钟使能 */")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{adc}EN | RCC_APB2ENR_IOP{port}EN;")
    lines.append(f"__DSB();")
    lines.append(f"")
    lines.append(f"/* 2. GPIO — {pin} 模拟输入 */")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} &= ~(0xFUL << {shift});")
    lines.append(f"// CNF=00 MODE=00 → 模拟输入")
    lines.append(f"")
    lines.append(f"/* 3. ADC 配置 (单次转换, 软件触发) */")
    lines.append(f"// 采样时间: 55.5 cycles (推荐用于 12-bit 精度)")
    if ch <= 9:
        lines.append(f"{adc}->SMPR2 |= (5UL << {(ch)*3});  // CH{ch}: 55.5 cycles")
    else:
        lines.append(f"{adc}->SMPR1 |= (5UL << {(ch-10)*3});  // CH{ch}: 55.5 cycles")
    lines.append(f"{adc}->SQR3 = {ch};                 // 转换序列: 1 个通道 = CH{ch}")
    lines.append(f"{adc}->CR2 = 1;                    // ADON 上电")
    lines.append(f"")
    lines.append(f"/* 4. 单次转换 */")
    lines.append(f"static uint16_t adc_read_ch{ch}(void) {{")
    lines.append(f"    {adc}->CR2 |= (1UL << 22);    // SWSTART")
    lines.append(f"    while (!({adc}->SR & 2));    // 等待 EOC")
    lines.append(f"    return {adc}->DR & 0xFFF;     // 12-bit result")
    lines.append(f"}}")
    lines.append(f"")
    lines.append(f"/* 5. 电压换算 (Vref=3.3V) */")
    lines.append(f"static uint32_t adc_to_mv(uint16_t val) {{")
    lines.append(f"    return (uint32_t)val * 3300 / 4096;")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_timer_int(timer: str, period_ms: int, tim_clk_mhz: int = 72) -> str:
    """生成定时中断代码"""
    tim_clock = TIM_CLOCK_BIT.get(timer, f"{timer}EN")

    # IRQ 号
    irq_map = {"TIM1": 25, "TIM2": 28, "TIM3": 29, "TIM4": 30}
    irq = irq_map.get(timer, 28)

    # 计算 PSC/ARR
    target_hz = 1000 // period_ms
    best_psc = 71  # → 1MHz
    best_arr = (tim_clk_mhz * 1_000_000) // ((best_psc + 1) * target_hz) - 1

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {timer} 定时中断 — 每 {period_ms}ms 触发一次")
    lines.append(f" * TIM_CLK={tim_clk_mhz}MHz, PSC={best_psc}, ARR={best_arr}")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. 时钟 + NVIC */")
    lines.append(f"RCC->APB1ENR |= RCC_APB1ENR_{tim_clock};")
    lines.append(f"__DSB();")
    lines.append(f"NVIC->ISER[{irq//32}] = (1UL << {irq%32});  // {timer}_IRQn = {irq}")
    lines.append(f"")
    lines.append(f"/* 2. Timer 配置 */")
    lines.append(f"{timer}->PSC = {best_psc};            // {tim_clk_mhz}MHz/({best_psc}+1) = {tim_clk_mhz*1000000//(best_psc+1)}Hz")
    lines.append(f"{timer}->ARR = {best_arr};           // → {1000//period_ms}Hz ({period_ms}ms)")
    lines.append(f"{timer}->DIER = 1;                  // 更新中断使能")
    lines.append(f"{timer}->CR1 = 1;                   // 使能")
    lines.append(f"")
    lines.append(f"/* 3. ISR */")
    lines.append(f"void {timer}_IRQHandler(void) {{")
    lines.append(f"    if ({timer}->SR & 1) {{          // 更新标志")
    lines.append(f"        {timer}->SR &= ~1;           // 清除标志")
    lines.append(f"        // TODO: 每 {period_ms}ms 执行的代码")
    lines.append(f"    }}")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_i2c(i2c_periph: str, speed_hz: int, scl: str, sda: str) -> str:
    """Generate I2C initialization code (register-level).

    Note: STM32F103 I2C has known errata (clock stretching, state machine
    hangs). For production, prefer HAL_I2C or software I2C (i2c_soft module).
    See: f103_known_issues.json → I2C section.
    """
    i2c_n = i2c_periph[-1]  # "1" or "2"

    # Clock config
    clock_info = I2C_CLOCK_BIT.get(i2c_periph)
    if not clock_info:
        return f"/* ERROR: Unknown I2C peripheral {i2c_periph} */"
    bus_reg, bit_name, bit_num = clock_info
    pclk1_mhz = 36  # APB1 max

    # Speed mode
    speed_info = I2C_SPEED_MODES.get(speed_hz)
    if not speed_info:
        return f"/* ERROR: Unsupported I2C speed {speed_hz}Hz. Supported: 100000, 400000 */"
    mode_name, is_fast, duty = speed_info

    # CCR calculation
    if is_fast:
        if not duty:
            ccr_val = pclk1_mhz * 1000000 // (3 * speed_hz)
        else:
            ccr_val = pclk1_mhz * 1000000 // (25 * speed_hz)
    else:
        ccr_val = pclk1_mhz * 1000000 // (2 * speed_hz)
    ccr_val = max(4, min(4095, ccr_val))  # clamp to 12-bit

    # TRISE calculation
    if is_fast:
        trise_val = (pclk1_mhz * 300 // 1000) + 1
    else:
        trise_val = pclk1_mhz + 1
    trise_val = max(1, min(63, trise_val))

    # GPIO config
    scl_port = pin_port(scl)
    sda_port = pin_port(sda)
    scl_shift = pin_cr_shift(scl)
    sda_shift = pin_cr_shift(sda)

    fs_bit = " | (1<<15)" if is_fast else ""

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {i2c_periph} — {speed_hz//1000}kHz {mode_name} mode, SCL={scl} SDA={sda}")
    lines.append(f" * CCR=0x{ccr_val:03X} ({ccr_val}), TRISE=0x{trise_val:02X} ({trise_val})")
    lines.append(f" * WARNING: STM32F103 I2C has known errata. Consider software I2C for")
    lines.append(f" *          production use. See f103_known_issues.json.")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. Clock enable */")
    lines.append(f"RCC->{bus_reg} |= RCC_{bus_reg}_{bit_name};")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{scl_port}EN | RCC_APB2ENR_IOP{sda_port}EN;")
    lines.append(f"__DSB();")
    lines.append(f"")
    lines.append(f"/* 2. GPIO — SCL={scl} AF-OD, SDA={sda} AF-OD */")
    lines.append(f"GPIO{scl_port}->{pin_cr_reg(scl)} &= ~(0xFUL << {scl_shift});")
    lines.append(f"GPIO{scl_port}->{pin_cr_reg(scl)} |=  (0xFUL << {scl_shift});")
    lines.append(f"GPIO{sda_port}->{pin_cr_reg(sda)} &= ~(0xFUL << {sda_shift});")
    lines.append(f"GPIO{sda_port}->{pin_cr_reg(sda)} |=  (0xFUL << {sda_shift});")
    lines.append(f"")
    lines.append(f"/* 3. {i2c_periph} config */")
    lines.append(f"{i2c_periph}->CR2 = {pclk1_mhz};               // FREQ = PCLK1 MHz")
    lines.append(f"{i2c_periph}->CCR = 0x{ccr_val:03X}{fs_bit};       // {speed_hz//1000}kHz, CCR={ccr_val}")
    lines.append(f"{i2c_periph}->TRISE = {trise_val};                // max rise time = {trise_val}")
    lines.append(f"{i2c_periph}->CR1 = 1;                  // PE=1, enable")
    lines.append(f"")
    lines.append(f"/* 4. Poll write helper */")
    lines.append(f"static error_chain_t i2c{i2c_n}_write(uint8_t dev_addr, uint8_t reg, uint8_t data) {{")
    lines.append(f"    uint32_t timeout = 100000;")
    lines.append(f"    while ({i2c_periph}->SR2 & (1<<1)) {{        // wait BUSY=0")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE001, \"I2C BUSY timeout\");")
    lines.append(f"    }}")
    lines.append(f"    {i2c_periph}->CR1 |= (1<<8);                 // START")
    lines.append(f"    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & 1)) {{           // wait SB")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE002, \"I2C START timeout\");")
    lines.append(f"    }}")
    lines.append(f"    {i2c_periph}->DR = (dev_addr << 1);          // ADDR + W")
    lines.append(f"    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<1))) {{       // wait ADDR")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE003, \"I2C ADDR timeout\");")
    lines.append(f"    }}")
    lines.append(f"    (void){i2c_periph}->SR2;                       // clear ADDR")
    lines.append(f"    {i2c_periph}->DR = reg;                       // send register")
    lines.append(f"    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<7))) {{       // wait TXE")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE004, \"I2C TXE timeout\");")
    lines.append(f"    }}")
    lines.append(f"    {i2c_periph}->DR = data;                      // send data")
    lines.append(f"    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<7))) {{")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE004, \"I2C TXE timeout\");")
    lines.append(f"    }}")
    lines.append(f"    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<2))) {{       // wait BTF")
    lines.append(f"        if (--timeout == 0) return ERR_PLAIN(0xE005, \"I2C BTF timeout\");")
    lines.append(f"    }}")
    lines.append(f"    {i2c_periph}->CR1 |= (1<<9);                  // STOP")
    lines.append(f"    return ERR_OK;")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_spi(spi_periph: str, mode: int, nss: str, sck: str,
            miso: str, mosi: str, baud_div: int = 16) -> str:
    """Generate SPI initialization code (register-level).

    SPI1 on APB2 (72MHz), SPI2 on APB1 (36MHz).
    Mode = CPOL:CPHA (0-3). NSS handled as GPIO output (software CS).
    """
    spi_n = spi_periph[-1]  # "1" or "2"

    clock_info = SPI_CLOCK_BIT.get(spi_periph)
    if not clock_info:
        return f"/* ERROR: Unknown SPI peripheral {spi_periph} */"
    bus_reg, bit_name, bit_num, pclk_mhz = clock_info

    # Mode parsing
    cpol = 1 if mode & 2 else 0
    cpha = 1 if mode & 1 else 0
    mode_names = {0: "CPOL=0,CPHA=0", 1: "CPOL=0,CPHA=1",
                  2: "CPOL=1,CPHA=0", 3: "CPOL=1,CPHA=1"}

    # Baud rate
    br_val = SPI_BAUD_DIV.get(baud_div, 3)  # default /16
    actual_div = [k for k, v in SPI_BAUD_DIV.items() if v == br_val][0]
    spi_freq_hz = pclk_mhz * 1000000 // actual_div

    # GPIO config
    nss_port = pin_port(nss)
    scl_shift = pin_cr_shift(sck)
    miso_shift = pin_cr_shift(miso)
    mosi_shift = pin_cr_shift(mosi)
    nss_shift = pin_cr_shift(nss)

    # CR1 bit fields
    cr1 = (br_val << 3) | (cpol << 1) | (cpha << 0) | (1 << 2)  # MSTR=1

    lines = []
    lines.append(f"/* ========================================================================")
    lines.append(f" * {spi_periph} — Mode {mode} ({mode_names.get(mode, '?')}), {spi_freq_hz//1000}kHz")
    lines.append(f" * SCK={sck} MISO={miso} MOSI={mosi} NSS={nss} (software CS)")
    lines.append(f" * PCLK={pclk_mhz}MHz, BR[2:0]={br_val} (/ {actual_div})")
    lines.append(f" * ======================================================================== */")
    lines.append(f"")
    lines.append(f"/* 1. Clock enable */")
    lines.append(f"RCC->{bus_reg} |= RCC_{bus_reg}_{bit_name};")
    # Collect unique ports for clock enable
    ports = sorted(set([pin_port(sck), pin_port(miso), pin_port(mosi), pin_port(nss)]))
    for port in ports:
        lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{port}EN;")
    lines.append(f"__DSB();")
    lines.append(f"")
    lines.append(f"/* 2. GPIO config */")
    lines.append(f"// SCK={sck} — AF push-pull 50MHz")
    lines.append(f"GPIO{pin_port(sck)}->{pin_cr_reg(sck)} &= ~(0xFUL << {scl_shift});")
    lines.append(f"GPIO{pin_port(sck)}->{pin_cr_reg(sck)} |=  (0xBUL << {scl_shift});")
    lines.append(f"// MOSI={mosi} — AF push-pull 50MHz")
    lines.append(f"GPIO{pin_port(mosi)}->{pin_cr_reg(mosi)} &= ~(0xFUL << {mosi_shift});")
    lines.append(f"GPIO{pin_port(mosi)}->{pin_cr_reg(mosi)} |=  (0xBUL << {mosi_shift});")
    lines.append(f"// MISO={miso} — floating input")
    lines.append(f"GPIO{pin_port(miso)}->{pin_cr_reg(miso)} &= ~(0xFUL << {miso_shift});")
    lines.append(f"GPIO{pin_port(miso)}->{pin_cr_reg(miso)} |=  (0x4UL << {miso_shift});")
    lines.append(f"// NSS={nss} — GPIO output (software CS)")
    lines.append(f"GPIO{pin_port(nss)}->{pin_cr_reg(nss)} &= ~(0xFUL << {nss_shift});")
    lines.append(f"GPIO{pin_port(nss)}->{pin_cr_reg(nss)} |=  (0x3UL << {nss_shift});")
    lines.append(f"GPIO{pin_port(nss)}->BSRR = (1UL << {pin_num(nss)});  // CS=HIGH (inactive)")
    lines.append(f"")
    lines.append(f"/* 3. {spi_periph} config */")
    lines.append(f"// CR1: BR[2:0]={br_val} CPOL={cpol} CPHA={cpha} MSTR=1 SSM=1 SSI=1")
    lines.append(f"{spi_periph}->CR1 = 0x{cr1:04X} | (1<<9) | (1<<8);  // SSM+SSI (software NSS)")
    lines.append(f"// CR2: SSOE=0 (output disabled, manual CS)")
    lines.append(f"{spi_periph}->CR1 |= (1<<6);                        // SPE=1, enable")
    lines.append(f"")
    lines.append(f"/* 4. CS control macros */")
    lines.append(f"#define SPI{spi_n}_CS_LOW()  GPIO{pin_port(nss)}->BRR = (1UL << {pin_num(nss)})")
    lines.append(f"#define SPI{spi_n}_CS_HIGH() GPIO{pin_port(nss)}->BSRR = (1UL << {pin_num(nss)})")
    lines.append(f"")
    lines.append(f"/* 5. Poll transfer */")
    lines.append(f"static uint8_t spi{spi_n}_transfer(uint8_t tx_byte) {{")
    lines.append(f"    while (!({spi_periph}->SR & (1<<1)));  // wait TXE")
    lines.append(f"    {spi_periph}->DR = tx_byte;")
    lines.append(f"    while (!({spi_periph}->SR & (1<<0)));  // wait RXNE")
    lines.append(f"    return {spi_periph}->DR;")
    lines.append(f"}}")
    lines.append(f"")
    lines.append(f"/* 6. Burst write example */")
    lines.append(f"static void spi{spi_n}_write_burst(uint8_t *buf, int len) {{")
    lines.append(f"    SPI{spi_n}_CS_LOW();")
    lines.append(f"    for (int i = 0; i < len; i++) {{")
    lines.append(f"        while (!({spi_periph}->SR & (1<<1)));")
    lines.append(f"        {spi_periph}->DR = buf[i];")
    lines.append(f"    }}")
    lines.append(f"    while ({spi_periph}->SR & (1<<7));  // wait BSY=0")
    lines.append(f"    SPI{spi_n}_CS_HIGH();")
    lines.append(f"}}")
    return "\n".join(lines)


def gen_doc(periph_name: str, out_dir: str = "") -> str:
    """Generate a DESIGN.md and Doxygen header from knowledge base data.

    Reads stm32f103-ref.json for the peripheral, extracts registers and
    recipes, and outputs Markdown documentation + Doxygen .h file.

    Args:
        periph_name: Peripheral name (e.g. 'I2C1', 'SPI1')
        out_dir: Output directory for generated files (default: modules/<name>/)

    Returns:
        Summary string of generated files.
    """
    ref = load_ref()

    # Look up peripheral in KB
    periph_data = ref.get("peripherals", {}).get(periph_name)
    rel_data = ref.get("_relationships", {}).get(periph_name)
    if not periph_data and not rel_data:
        return f"Error: {periph_name} not found in stm32f103-ref.json"

    base = periph_data.get("base", "?") if periph_data else (rel_data.get("base", "?") if rel_data else "?")
    bus = periph_data.get("bus", "?") if periph_data else (rel_data.get("bus", "?") if rel_data else "?")
    desc = periph_data.get("desc", "") if periph_data else ""
    registers = periph_data.get("registers", {}) if periph_data else {}
    recipes = periph_data.get("recipes", []) if periph_data else []

    # Build register summary table
    reg_table = "| Register | Offset | Description | Key Fields |\n"
    reg_table += "|----------|--------|-------------|------------|\n"
    for rname, rdata in sorted(registers.items()):
        offset = rdata.get("offset", "?")
        rdesc = rdata.get("desc", "")[:60]
        bits = rdata.get("bits", {})
        field_names = ", ".join(
            finfo.get("name", "?")
            for finfo in list(bits.values())[:5]
        ) if isinstance(bits, dict) else ""
        reg_table += f"| {rname} | {offset} | {rdesc} | {field_names} |\n"

    # Build dependency section from relationships
    deps = []
    if rel_data:
        clock_info = rel_data.get("clock", {})
        if clock_info:
            deps.append(f"- Clock: RCC_{clock_info.get('rcc_register', '?')}ENR bit {clock_info.get('rcc_bit', '?')} ({clock_info.get('rcc_bit_name', '?')})")
        pins = rel_data.get("pins", {})
        if pins:
            pin_list = ", ".join(f"{pname}={pinfo.get('port','?')}{pinfo.get('pin','?')}" for pname, pinfo in pins.items())
            deps.append(f"- Pins: {pin_list}")
        dma_info = rel_data.get("dma", {})
        if dma_info:
            dma_list = ", ".join(f"{ch}={dev}" for ch, dev in dma_info.items())
            deps.append(f"- DMA: {dma_list}")
        irq_info = rel_data.get("irq", {})
        if irq_info:
            deps.append(f"- IRQ: {irq_info.get('name', '?')} = {irq_info.get('number', '?')}")

    # Build Doxygen header
    periph_lower = periph_name.lower()
    doxygen = f"""/**
 * @file {periph_lower}_doc.h
 * @brief {periph_name} Peripheral Reference — Auto-generated from stm32f103-ref.json
 *
 * Base Address: {base}
 * Bus: {bus}
 *
 * Register Summary:
{chr(10).join(' * ' + l for l in reg_table.split(chr(10))[:20])}
 *
 * @note This file is auto-generated. Regenerate with:
 *       python .embeddedskills/gen_periph.py --type doc --periph {periph_name}
 */
"""

    # Build Markdown doc
    md = f"# {periph_name} Peripheral Reference\n\n"
    md += f"- **Base**: {base} | **Bus**: {bus} | **Chip**: STM32F103C8T6\n"
    md += f"- **Description**: {desc}\n\n"
    md += f"## Registers\n\n{reg_table}\n\n"
    if deps:
        md += f"## Dependencies\n\n" + "\n".join(deps) + "\n\n"
    if recipes:
        md += f"## Code Recipes ({len(recipes)})\n\n"
        for i, r in enumerate(recipes, 1):
            md += f"### {i}. {r.get('title', 'Untitled')}\n\n"
            md += f"```c\n{r.get('code', '')}\n```\n\n"

    # Write output
    if not out_dir:
        proj = find_project_root(os.getcwd()) or "."
        out_dir = os.path.join(proj, "modules", periph_lower)
    os.makedirs(out_dir, exist_ok=True)

    dox_path = os.path.join(out_dir, f"{periph_lower}_doc.h")
    with open(dox_path, 'w', encoding='ascii', errors='replace') as f:
        f.write(doxygen)

    md_path = os.path.join(out_dir, f"{periph_lower}_ref.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)

    return f"Generated:\n  {dox_path}\n  {md_path}"


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="STM32F103 外设代码生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python gen_periph.py --type pwm --timer TIM2 --ch 1 --pin PA0 --freq 1000 --duty 50
  python gen_periph.py --type usart --usart USART1 --baud 115200 --tx PA9 --rx PA10
  python gen_periph.py --type adc --adc ADC1 --ch 1 --pin PA1
  python gen_periph.py --type gpio --pin PC13 --mode out-pp-50mhz
  python gen_periph.py --type systick --freq 1000
  python gen_periph.py --type timer-int --timer TIM2 --period-ms 1
  python gen_periph.py --type i2c --i2c I2C1 --scl PB6 --sda PB7 --speed 100000
  python gen_periph.py --type spi --spi SPI1 --sck PA5 --miso PA6 --mosi PA7 --nss PA4
  python gen_periph.py --type doc --periph I2C1

GPIO 模式:
  out-pp-50mhz, out-od-50mhz, af-pp-50mhz, af-od-50mhz,
  in-floating, in-pullup, in-analog
        """
    )
    parser.add_argument("--type", required=True,
                        choices=["gpio", "usart", "pwm", "adc", "systick", "timer-int",
                                 "i2c", "spi", "doc"],
                        help="外设类型")
    # gpio
    parser.add_argument("--pin", default="", help="引脚: PA0, PC13")
    parser.add_argument("--mode", default="out-pp-50mhz", help="GPIO 模式")
    # usart
    parser.add_argument("--usart", default="USART1", help="USART 外设: USART1/2/3")
    parser.add_argument("--baud", type=int, default=115200, help="波特率")
    parser.add_argument("--tx", default="PA9", help="TX 引脚")
    parser.add_argument("--rx", default="PA10", help="RX 引脚")
    # pwm
    parser.add_argument("--timer", default="TIM2", help="定时器: TIM2/3/4")
    parser.add_argument("--ch", type=int, default=1, help="通道: 1-4")
    parser.add_argument("--freq", type=int, default=1000, help="PWM 频率 Hz")
    parser.add_argument("--duty", type=int, default=50, help="占空比 %% (0-100)")
    parser.add_argument("--tim-clk", type=int, default=72, help="定时器时钟 MHz")
    # adc
    parser.add_argument("--adc", default="ADC1", help="ADC 外设: ADC1/2")
    # timer-int
    parser.add_argument("--period-ms", type=int, default=1, help="中断周期 ms")
    # i2c
    parser.add_argument("--i2c", default="I2C1", help="I2C 外设: I2C1/2")
    parser.add_argument("--speed", type=int, default=100000, help="I2C 速率 Hz (100000/400000)")
    parser.add_argument("--scl", default="PB6", help="SCL 引脚")
    parser.add_argument("--sda", default="PB7", help="SDA 引脚")
    # spi
    parser.add_argument("--spi", default="SPI1", help="SPI 外设: SPI1/2")
    parser.add_argument("--spi-mode", type=int, default=0, choices=[0,1,2,3],
                        help="SPI mode (CPOL:CPHA): 0-3")
    parser.add_argument("--baud-div", type=int, default=16, help="SPI 分频: 2/4/8/16/32/64/128/256")
    parser.add_argument("--sck", default="PA5", help="SCK 引脚")
    parser.add_argument("--miso", default="PA6", help="MISO 引脚")
    parser.add_argument("--mosi", default="PA7", help="MOSI 引脚")
    parser.add_argument("--nss", default="PA4", help="NSS 引脚 (software CS)")
    # doc
    parser.add_argument("--periph", default="", help="目标外设名 (用于 --type doc)")
    parser.add_argument("--out-dir", default="", help="文档输出目录")

    args = parser.parse_args()

    if args.type == "gpio":
        if not args.pin:
            print("Error: --pin required for GPIO", file=sys.stderr)
            sys.exit(1)
        print(gen_gpio(args.pin, args.mode))

    elif args.type == "usart":
        print(gen_usart(args.usart, args.baud, args.tx, args.rx))

    elif args.type == "pwm":
        if not args.pin and args.ch and args.timer:
            args.pin = TIM_CH_PINS.get((args.timer, args.ch), "")
        if not args.pin:
            print("Error: --pin required for PWM (or use --timer + --ch for auto-detect)", file=sys.stderr)
            sys.exit(1)
        print(gen_pwm(args.timer, args.ch, args.pin, args.freq, args.duty, args.tim_clk))

    elif args.type == "adc":
        if not args.pin:
            print("Error: --pin required for ADC", file=sys.stderr)
            sys.exit(1)
        print(gen_adc(args.adc, args.ch, args.pin))

    elif args.type == "systick":
        print(gen_systick(args.freq))

    elif args.type == "timer-int":
        print(gen_timer_int(args.timer, args.period_ms, args.tim_clk))

    elif args.type == "i2c":
        print(gen_i2c(args.i2c, args.speed, args.scl, args.sda))

    elif args.type == "spi":
        print(gen_spi(args.spi, args.spi_mode, args.nss, args.sck,
                      args.miso, args.mosi, args.baud_div))

    elif args.type == "doc":
        if not args.periph:
            print("Error: --periph required for --type doc", file=sys.stderr)
            sys.exit(1)
        print(gen_doc(args.periph, args.out_dir))


if __name__ == "__main__":
    main()
