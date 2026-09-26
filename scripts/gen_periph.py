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

from wb_common import TOOLKIT_ROOT, find_project_root, load_ref  # F-157: 三份 load_ref 收编

# F-158 (P2-4): 引脚/时钟/中断映射数据外置 data/stm32f103-gen-maps.json —
# 生成器纯逻辑, 数据单一事实源; 载入后还原为与旧字面量完全相同的内存形态
# (tuple 键/整型键/元组值), 生成物逐字节不变。
_GEN_MAPS = json.load(open(os.path.join(TOOLKIT_ROOT, "data",
                                        "stm32f103-gen-maps.json"),
                           encoding="utf-8"))

# ---- GPIO 引脚地址映射 ----
GPIO_BASE = _GEN_MAPS["gpio_base"]
GPIO_CLOCK_BIT = _GEN_MAPS["gpio_clock_bit"]
GPIO_CR_OFFSET = _GEN_MAPS["gpio_cr_offset"]

# ---- TIM 通道 → 引脚映射 (默认复用映射; JSON 键 "TIM2:1" 还原 tuple) ----
TIM_CH_PINS = {
    (t, int(c)): v
    for k, v in _GEN_MAPS["tim_ch_pins"].items()
    for t, c in [k.split(":")]
}

# ---- TIM 基址和时钟映射 ----
TIM_CLOCK_BIT = _GEN_MAPS["tim_clock_bit"]

# ---- TIM 总线映射 (F-077, RM0008: TIM1 高级定时器挂 APB2, TIM2~7 挂 APB1) ----
# 旧版两个 TIM 生成器硬编码 APB1ENR, TIM1 会产出 RCC_APB1ENR_TIM1EN —
# 该宏在 CMSIS 头文件不存在 (TIM1EN 在 APB2ENR bit 0), 编译即失败;
# 更隐蔽的变体是 AI 顺手"修"成使能别的位 → 定时器时钟从未开启。
TIM_BUS = _GEN_MAPS["tim_bus"]

# ---- I2C 时钟映射 ----
I2C_CLOCK_BIT = {k: tuple(v) for k, v in _GEN_MAPS["i2c_clock_bit"].items()}

# ---- SPI 时钟映射 ----
# F-110: 第 4 项从 pclk 字面量 (72/36) 改为总线归属——时钟走 apb_clock_mhz
# 统一推导, 表不再各自携带频率常数。
SPI_CLOCK_BIT = {k: tuple(v) for k, v in _GEN_MAPS["spi_clock_bit"].items()}

# ---- SPI 分频表 (BR[2:0]) ----
SPI_BAUD_DIV = {int(k): v for k, v in _GEN_MAPS["spi_baud_div"].items()}

# ---- I2C 速度模式 ----
I2C_SPEED_MODES = {int(k): tuple(v)
                   for k, v in _GEN_MAPS["i2c_speed_modes"].items()}

# ---- F-110: 时钟树推导 (单一事实源) ----
HCLK_MIN, HCLK_MAX = 2, 72  # 2 起: pclk1=HCLK//2 须 ≥1; 72 = F103 规格上限
# WB-20260920-01: PCLK1 规格上限 36MHz = APB1 总线顶速 (RM0008/F103 数据
# 手册"外设时钟"表; ref.json 未登记 — GAP-D-4 纪律: 架构常量+行内出处,
# 不入 ref.json)。PCLK2 上限即 HCLK_MAX。
PCLK1_MAX = 36


def apb_clock_mhz(hclk_mhz: int, bus: str,
                  pclk1_mhz: int | None = None,
                  pclk2_mhz: int | None = None) -> int:
    """HCLK → APB 总线时钟。

    F-110: 默认按 F103 标准分频假设 (HPRE=1 / PPRE2=1 / PPRE1=2, CubeMX
    复位默认即此)——APB2 = HCLK; APB1 = HCLK//2 (floor——奇数 HCLK 的取整
    结果由注释如实呈现)。
    WB-20260920-01 (--pclk1/--pclk2): 对应总线的显式 PCLK 覆盖推导值,
    逐键独立; 未传的键维持 F-110 公式不动。默认路径 (两参皆 None) 与
    F-110 行为逐字节一致。"""
    if bus == "APB2":
        return pclk2_mhz if pclk2_mhz is not None else hclk_mhz
    return pclk1_mhz if pclk1_mhz is not None else hclk_mhz // 2


def tim_kernel_clock_mhz(hclk_mhz: int, pclk1_mhz: int | None = None) -> int:
    """TIM2~4 定时器内核时钟派生 (RM0008 §7.3.7: APB1 分频≠1 时定时器
    时钟 ×2; 分频=1 不倍增)。

    WB-20260920-01 派生链 (简报 §2.1): 显式 --tim-clk (调用方处理) >
    APB1×2 规则随 --pclk1 派生 > hclk 推导 (F-110 现状)。

    --pclk1 为整数 MHz, 无法从参数得知分频器原值——按以下**前提规则**
    判定 (非静默: 该前提随生成物注记与本报告披露):
      pclk1 == hclk//2 → 标准 PPRE1=2 → ×2 抵消, 内核 = hclk (F-110 现状);
      pclk1 == hclk    → PPRE1=1 → 分频=1, ×2 **不**适用, 内核 = pclk1
                         (RM0008 §7.3.7 原文锚定——简报规则的物理边界
                         补全, 详见报告三列对账表);
      其余             → 视为 PPRE1∈{4,8,16} → 内核 = pclk1×2。
    pclk1 未传 → F-110 现状推导 (内核 = hclk)。"""
    if pclk1_mhz is None:
        return hclk_mhz
    if pclk1_mhz == hclk_mhz // 2:
        return hclk_mhz
    if pclk1_mhz == hclk_mhz:
        return pclk1_mhz
    return pclk1_mhz * 2


def _hclk_error(hclk_mhz: int) -> str | None:
    """F-111 (复审 M-3): hclk 域校验收敛到库级——F-103 纪律是"生成器函数
    内返回 ERROR", 旧版只在 main() 校验, 库直调 (gen_systick(1000, 0) 等)
    会绕过守卫产出 LOAD=-1 的伪合法代码。CLI 层校验保留 (报错消息含
    --hclk 提示更友好), 两层互补。"""
    if not (HCLK_MIN <= hclk_mhz <= HCLK_MAX):
        return (f"/* ERROR: hclk={hclk_mhz}MHz 越界 — 有效范围 "
                f"{HCLK_MIN}~{HCLK_MAX} MHz (F103 规格; pclk1=hclk/2 须≥1)。*/")
    return None


def _pclk_error(hclk_mhz: int, pclk1_mhz: int | None = None,
                pclk2_mhz: int | None = None) -> str | None:
    """WB-20260920-01: --pclk1/--pclk2 域校验 (库级, 与 _hclk_error 同款
    F-103 两层互补纪律)。规则:
      pclk2 ∈ [1, HCLK_MAX] 且 ≤ hclk (PPRE2≥1 ⇒ PCLK2 ≤ HCLK);
      pclk1 ∈ [1, PCLK1_MAX=36] 且 ≤ hclk (36 = APB1 总线顶速, RM0008
      数据手册"外设时钟"表 — GAP-D-4 架构常量);
      非整数 (含 bool) / 空白串同律 — 显式报错, 禁止静默回落默认。"""
    for key, value, lo, hi in (("--pclk2", pclk2_mhz, 1, HCLK_MAX),
                               ("--pclk1", pclk1_mhz, 1, PCLK1_MAX)):
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            return (f"/* ERROR: {key}={value!r} 非整数 — 须为整数 MHz "
                    f"(F-103: 不静默回落默认)。*/")
        if not (lo <= value <= hi):
            bound_note = ("PCLK2 ≤ HCLK" if key == "--pclk2"
                          else "36 = APB1 总线顶速 (RM0008 数据手册, GAP-D-4 架构常量)")
            return (f"/* ERROR: {key}={value} 越界 — 有效范围 {lo}~{hi} MHz "
                    f"({bound_note})。*/")
        if value > hclk_mhz:
            return (f"/* ERROR: {key}={value} > hclk={hclk_mhz} — PPRE 分频比 "
                    f"不可能小于 1:1 (F-103: 不静默回落默认)。*/")
    return None


def _hclk_precondition_note(hclk_mhz: int, pclk1_mhz: int | None = None,
                            pclk2_mhz: int | None = None) -> list:
    """F-111 (复审 M-4, spec §6 承诺三处声明的生成物落点): 非默认时钟假设时
    生成物头部回显前提。hclk=72 且无 pclk 覆盖 → 空列表 (默认路径逐字节
    兼容契约优先)。
    WB-20260920-01: 显式 pclk 在场时**必须**注入 (哪怕是 hclk=72——新信息
    必须如实回显, 含 tim 内核 ×2 前提, 不许静默)。"""
    if hclk_mhz == 72 and pclk1_mhz is None and pclk2_mhz is None:
        return []
    if pclk1_mhz is None and pclk2_mhz is None:
        # F-110 原文 (hclk 非默认) — 逐字节保持
        return [" * 时钟前提 (F-110): HCLK=%dMHz 按标准 APB 分频推导" % hclk_mhz,
                " *   APB1=%d/APB2=%d MHz (HPRE=1/PPRE2=1/PPRE1=2, TIM×2"
                " §7.3.7); 异常分频请显式传 --tim-clk 或手改。"
                % (hclk_mhz // 2, hclk_mhz)]
    lines = [" * 时钟前提 (WB-20260920-01): HCLK=%dMHz, 显式 PCLK 覆盖生效"
             % hclk_mhz]
    if pclk1_mhz is not None:
        tim = tim_kernel_clock_mhz(hclk_mhz, pclk1_mhz)
        if pclk1_mhz == hclk_mhz // 2:
            premise = "标准 PPRE1=2, ×2 抵消"
        elif pclk1_mhz == hclk_mhz:
            premise = "PPRE1=1, ×2 不适用"
        else:
            premise = "PPRE1≠1, ×2 (分频器原值不可知, 按整数 pclk1 前提)"
        lines.append(" *   PCLK1=%dMHz (--pclk1); TIM2~4 内核=%dMHz (%s,"
                     " §7.3.7)" % (pclk1_mhz, tim, premise))
    else:
        lines.append(" *   PCLK1=%dMHz (PPRE1=2 推导)" % (hclk_mhz // 2))
    if pclk2_mhz is not None:
        lines.append(" *   PCLK2=%dMHz (--pclk2)" % pclk2_mhz)
    else:
        lines.append(" *   PCLK2=%dMHz (PPRE2=1 推导)" % hclk_mhz)
    return lines

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

# F-103: mode_map 提为模块级并单一事实源 (argparse choices 与 gen_gpio 共用,
# 两处判据永不漂移)。F-158: 数据外置 gen-maps.json。
GPIO_MODE_MAP = {k: tuple(v) for k, v in _GEN_MAPS["gpio_mode_map"].items()}


def gen_gpio(pin: str, mode: str) -> str:
    """生成 GPIO 引脚配置代码"""
    # F-103: 未知 mode 显式报错。旧行为 mode_map.get(mode, ("0x3", mode))
    # 静默降级推挽——拼错的 mode 标签配 0x3 输出, 生成物"看起来合法"但
    # 与注释意图相反 (B 类静默缺陷, 与 F-086/F-103 边界报错同族纪律)。
    if mode not in GPIO_MODE_MAP:
        return (f"/* ERROR: 未知 GPIO 模式 '{mode}' — 有效模式: "
                f"{', '.join(sorted(GPIO_MODE_MAP))}。*/")
    port = pin_port(pin)
    port_base = GPIO_BASE.get(port, f"GPIO{port}")
    clock_bit = GPIO_CLOCK_BIT.get(port, f"IOP{port}EN")
    cr_reg = pin_cr_reg(pin)
    shift = pin_cr_shift(pin)

    mode_val, mode_desc = GPIO_MODE_MAP[mode]

    lines = []
    lines.append(f"/* {pin} — {mode_desc} */")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{clock_bit};")
    lines.append("__DSB();")
    lines.append(f"{port_base}->{cr_reg} &= ~(0xFUL << {shift});")
    lines.append(f"{port_base}->{cr_reg} |=  ({mode_val}UL << {shift});")
    # F-087: CNF=10/MODE=00 (输入模式 0x8) 的上下拉方向由 ODR 决定, 复位
    # ODR=0 → 只写 CRL/CRH 实际是下拉, 与"上拉"标签相反 (B 类静默缺陷)。
    # 上拉必须显式置 ODR 对应位; 其他模式不得触碰 ODR。
    if mode == "in-pullup":
        lines.append(f"{port_base}->ODR |= (1UL << {pin_num(pin)});")
    return "\n".join(lines)


def gen_systick(freq_hz: int, hclk_mhz: int = 72) -> str:
    """生成 SysTick 配置代码 (F-110: 内核时钟默认 72MHz, 可经 --hclk 参数化)"""
    # F-108 (L-1): 零/负值统一为结构化 ERROR (与 gen_pwm freq 守卫对齐),
    # 不再让内核 % 0 抛 ZeroDivisionError traceback。
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    if freq_hz <= 0:
        return f"/* ERROR: freq={freq_hz}Hz 非法 — 必须为正整数。*/"
    hz = hclk_mhz * 1000000
    if hz % freq_hz != 0:
        return f"/* ERROR: {hclk_mhz}MHz / {freq_hz} is not an integer. Choose a divisor of {hclk_mhz}MHz. */"

    load = hz // freq_hz - 1
    # F-103: SysTick->LOAD 是 24 位寄存器 (RM0008 §9.1.2), 超限被硬件静默
    # 截断低位 → 周期错误却自称正确 (实测 --freq 2 → 35999999 > 0xFFFFFF)。
    if load > 0xFFFFFF:
        # 最低可表频率 = ⌈hclk / 2^24⌉ (72MHz 下 = 5Hz; 整除下取整会虚报)
        return (f"/* ERROR: SysTick LOAD={load} > 0xFFFFFF (24-bit) — "
                f"{freq_hz}Hz 在 {hclk_mhz}MHz 下不可表示; 请提高频率 "
                f"(最低 {-(-hz // (0xFFFFFF + 1))}Hz) 或改用定时器。*/")
    period_us = 1000000 // freq_hz

    lines = []
    lines.append(f"/* SysTick — {freq_hz}Hz ({period_us}us interval), {hclk_mhz}MHz core clock */")
    lines.extend(_hclk_precondition_note(hclk_mhz))
    lines.append(f"SysTick->LOAD = {load};         // {hclk_mhz}MHz/{freq_hz} - 1")
    lines.append("SysTick->VAL  = 0;")
    lines.append("SysTick->CTRL = SysTick_CTRL_ENABLE | SysTick_CTRL_TICKINT | SysTick_CTRL_CLKSOURCE;")
    lines.append("")
    # F-087: tick_ms 声明必须在 Handler 之前 (生成物是可独立编译的片段,
    # 先用后声明编译即失败); Handler 必须递增 tick_ms, 否则 delay_ms 永久挂死
    # (F-080 同族不变量)。
    lines.append("/* 基于 SysTick 的延时计数 */")
    lines.append("static volatile uint32_t tick_ms;")
    lines.append("")
    lines.append("/* SysTick ISR */")
    lines.append("void SysTick_Handler(void) {")
    lines.append("    tick_ms++;                  // F-087: 必须递增, 否则 delay_ms 永久挂死")
    lines.append(f"    // called every {period_us}us — 用户代码加在这里")
    lines.append("}")
    lines.append("")
    lines.append("void delay_ms(uint32_t ms) {")
    lines.append("    uint32_t start = tick_ms;")
    lines.append("    while ((tick_ms - start) < ms) { __WFI(); }")
    lines.append("}")
    return "\n".join(lines)


def gen_usart(usart: str, baud: int, tx: str, rx: str,
              hclk_mhz: int = 72, pclk1_mhz: int | None = None,
              pclk2_mhz: int | None = None) -> str:
    """生成 USART 初始化代码 (F-110: 总线时钟经 apb_clock_mhz 推导;
    WB-20260920-01: pclk1/pclk2 显式覆盖逐键独立, USART1 吃 pclk2,
    USART2/3 吃 pclk1)"""
    err = _hclk_error(hclk_mhz)
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk1_mhz, pclk2_mhz)
    if err:
        return err
    usart_n = usart[-1]  # "1", "2", "3"
    bus = "APB2" if usart_n == "1" else "APB1"
    pclk_mhz = apb_clock_mhz(hclk_mhz, bus, pclk1_mhz, pclk2_mhz)

    # F-108 (L-1): baud<=0 结构化 ERROR, 不再除零 traceback。
    if baud <= 0:
        return f"/* ERROR: baud={baud} 非法 — 必须为正整数。*/"

    # 波特率计算
    div = pclk_mhz * 1000000 / (16 * baud)
    mantissa = int(div)
    fraction = round((div - mantissa) * 16)
    # F-076: fraction 舍入到 16 = mantissa 进位。旧式 (m<<4)|f 在奇数 m 下
    # bit4 已被占用, |16 会静默丢弃进位 (实测 baud=1377 → 0xCC30, 应 0xCC40;
    # F-071 曾误记 0xCB00 = 3248.0, 见 CHANGELOG F-076 账本订正)。
    if fraction >= 16:
        mantissa += 1
        fraction = 0
    # F-103: F1 USART BRR 的 DIV_Mantissa 只有 bit[15:4] 共 12 位 (RM0008
    # §27.5.5), mantissa > 0xFFF 装不进 → 低波特率显式报错。
    # 72MHz 阈值 ≈ 1100 baud, 36MHz ≈ 550 baud, 常用波特率不受影响。
    if mantissa > 0xFFF:
        return (f"/* ERROR: {usart} BRR mantissa {mantissa} > 0xFFF (12-bit) "
                f"at {baud} baud / PCLK{bus[-1]}={pclk_mhz}MHz — 波特率过低 "
                f"(最低约 {pclk_mhz * 1000000 // (16 * 0xFFF)} baud)。*/")
    brr = (mantissa << 4) | fraction

    tx_port = pin_port(tx)
    rx_port = pin_port(rx)
    tx_shift = pin_cr_shift(tx)
    rx_shift = pin_cr_shift(rx)

    lines = []
    lines.append("/* ========================================================================")
    lines.append(f" * {usart} — {baud} baud, 8N1, TX={tx} RX={rx}")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk1_mhz, pclk2_mhz))
    lines.append(f" * PCLK{bus[-1].lower()}={pclk_mhz}MHz, BRR=0x{brr:04X} ({mantissa}.{fraction}/16)")
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. 时钟使能 */")
    lines.append(f"RCC->APB{bus[-1]}ENR |= RCC_APB{bus[-1]}ENR_{usart}EN;")
    for port in sorted(set([tx_port, rx_port])):
        lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{port}EN;")
    lines.append("__DSB();")
    lines.append("")
    lines.append("/* 2. GPIO 配置 */")
    # F-075: CRL/CRH 按引脚号选择 (pin<8 → CRL, >=8 → CRH) — 旧版硬编码 CRH,
    # 低引脚会把位移落在 CRH 的错误字段上 (PA2 的位移 8 实际改写 PA10),
    # 外设脚保持浮空 → 生成物编译通过但外设无输出 (B 类静默缺陷)。
    # 位移沿用 pin_cr_shift 的 (n%8)*4, 与 CRL/CRH 两段寄存器布局一致。
    lines.append(f"// {tx} = {usart}_TX (复用推挽 50MHz)")
    lines.append(f"GPIO{tx_port}->{pin_cr_reg(tx)} &= ~(0xFUL << {tx_shift});")
    lines.append(f"GPIO{tx_port}->{pin_cr_reg(tx)} |=  (0xBUL << {tx_shift});")
    lines.append(f"// {rx} = {usart}_RX (浮空输入)")
    lines.append(f"GPIO{rx_port}->{pin_cr_reg(rx)} &= ~(0xFUL << {rx_shift});")
    lines.append(f"GPIO{rx_port}->{pin_cr_reg(rx)} |=  (0x4UL << {rx_shift});")
    lines.append("")
    lines.append("/* 3. USART 配置 */")
    lines.append(f"{usart}->BRR = 0x{brr:04X};")
    lines.append(f"{usart}->CR1 = USART_CR1_TE | USART_CR1_RE;")
    lines.append(f"{usart}->CR1 |= USART_CR1_UE;")
    lines.append("")
    # F-131 (工单 P2-2): Keil Microlib 的 int fputc(int, FILE*) 在 GCC/newlib-nano
    # 下 printf 根本不调用它——重定向静默失效 (旧产物来自 Keil 时代, 退役后成
    # 死代码)。改 newlib 系统桩 _write: printf/puts 最终都走 write(fd,buf,len)。
    lines.append("/* 4. printf 重定向 (GCC/newlib-nano 系统桩 _write; Keil Microlib 的 fputc 在此链不生效) */")
    lines.append("#include <unistd.h>")
    lines.append("int _write(int fd, char *buf, int len) {")
    lines.append("    for (int i = 0; i < len; i++) {")
    lines.append(f"        while (!({usart}->SR & (1UL<<7)));  // wait TXE")
    lines.append(f"        {usart}->DR = (uint8_t)buf[i];")
    lines.append("    }")
    lines.append("    return len;")
    lines.append("}")
    lines.append("")
    lines.append("/* 5. 轮询读写 */")
    lines.append("static void uart_putc(uint8_t byte) {")
    lines.append(f"    while (!({usart}->SR & (1UL<<7)));")
    lines.append(f"    {usart}->DR = byte;")
    lines.append("}")
    lines.append("static uint8_t uart_getc(void) {")
    lines.append(f"    while (!({usart}->SR & (1UL<<5)));  // wait RXNE")
    lines.append(f"    return {usart}->DR;")
    lines.append("}")
    return "\n".join(lines)


def gen_pwm(timer: str, ch: int, pin: str, freq: int, duty: int,
            tim_clk_mhz: int = None, hclk_mhz: int = 72,
            pclk1_mhz: int | None = None) -> str:
    """生成 PWM 初始化代码

    F-110 优先级契约: tim_clk_mhz 显式传值 > hclk 推导
    (TIM2~4 内核 = APB1×2 = hclk; TIM1 = APB2 = hclk, 恒为 hclk)。
    WB-20260920-01 派生链: 显式 tim_clk > pclk1 派生 (APB1 族, §7.3.7)
    > hclk 推导; TIM1 (APB2) 维持 hclk 推导 (pclk2×2 耦合未建模 —
    见报告 GAP-P-1)。"""
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk1_mhz)
    if err:
        return err
    # F-111 (M-3): 显式 tim_clk 也纳域纪律——旧版 tim_clk=0/-5 产出
    # ARR=-1 / 负 PSC 注释伪合法代码 (基线旧病, 随参数化收口)。
    if tim_clk_mhz is not None and tim_clk_mhz <= 0:
        return f"/* ERROR: tim_clk={tim_clk_mhz}MHz 非法 — 必须为正整数。*/"
    if tim_clk_mhz is None:
        tim_bus = TIM_BUS.get(timer, "APB1")   # F-077: TIM1 → APB2, 其余 APB1
        tim_clk_mhz = (tim_kernel_clock_mhz(hclk_mhz, pclk1_mhz)
                       if tim_bus == "APB1" else hclk_mhz)
    tim_bus = TIM_BUS.get(timer, "APB1")   # F-077: TIM1 → APB2, 其余 APB1
    # F-103 边界三连 (仿 F-086 gen_timer_int 显式报错惯例):
    # ① TIM2~4 只有 4 通道, ch≥5 时 CCR5/CCMR 写的是保留位——硬件静默无效,
    #    生成物编译通过但永远无输出 (B 类静默缺陷);
    # ② duty 越界 [0,100] 时 CCR 算术失去意义 (负值/恒满占空);
    # ③ freq≤0 直接除零 traceback。
    if ch < 1 or ch > 4:
        return (f"/* ERROR: {timer} 通道 {ch} 越界 — TIM2~4 仅 CH1~4, "
                f"CH≥5 写保留位硬件静默无效。*/")
    if duty < 0 or duty > 100:
        return f"/* ERROR: duty={duty} 越界 — 有效范围 0~100 (%)。*/"
    if freq <= 0:
        return f"/* ERROR: freq={freq}Hz 非法 — 必须为正整数。*/"
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
    lines.append("/* ========================================================================")
    lines.append(f" * {timer} CH{ch} PWM — {pin}, {freq}Hz, {duty}% duty")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk1_mhz))
    lines.append(f" * TIM_CLK={tim_clk_mhz}MHz, PSC={best_psc}, ARR={best_arr}, CCR{ch}={ccr} {freq_note}")
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. 时钟使能 */")
    lines.append(f"RCC->{tim_bus}ENR |= RCC_{tim_bus}ENR_{tim_clock};")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{port_clock};")
    lines.append("__DSB();")
    lines.append("")
    lines.append(f"/* 2. GPIO — {pin} 复用推挽 50MHz */")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} &= ~(0xFUL << {shift});")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} |=  (0xBUL << {shift});")
    lines.append("")
    lines.append("/* 3. Timer 配置 */")
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
    # F-122 (工单 P0-5): 高级定时器 MOE 缺位是 B 类静默缺陷——编译通过、
    # 运行永远无波形 (RM0008 §17.4.23 BDTR.MOE=0 强制关闭全部 OC 输出)。
    if timer == "TIM1":
        lines.append(f"{timer}->BDTR |= (1<<15);        // MOE: 主输出使能（高级定时器必需）")
    return "\n".join(lines)


def gen_adc(adc: str, ch: int, pin: str, hclk_mhz: int = 72,
            pclk2_mhz: int | None = None) -> str:
    """生成 ADC 初始化 + 单次转换代码 (F-110: ADCPRE 按 pclk2 自动选;
    WB-20260920-01: pclk2 显式覆盖逐键独立)"""
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk2_mhz=pclk2_mhz)
    if err:
        return err
    # F-119 (工单 P0-4): 通道域校验 (仿 gen_pwm F-103 三连守卫)。F103 ADC
    # 合法通道 0~17; 旧版 ch=20 写 SMPR1 保留位 (硬件静默无效), 负数生成
    # 负位移 C 代码 (UB)。
    if ch < 0 or ch > 17:
        return (f"/* ERROR: ADC 通道 {ch} 越界 — F103 合法通道 0~17 "
                f"(0~15 外部引脚, 16/17 为 vrefint/temp 内部通道)。*/")
    port = pin_port(pin)
    shift = pin_cr_shift(pin)

    # F-087: 默认 ADCPRE=/2 → PCLK2/2 = 36MHz, 超出 ADC 14MHz 上限
    # (data/f103_known_issues.json "ADC.max_clock")。F-110 泛化: 按推导的
    # pclk2 自动选**最小合规分频** (/2 /4 /6 /8 中首个 ≤14MHz);
    # hclk=72 时结果 = /6, 与 F-087 修复后输出逐字节一致 (兼容性契约)。
    # F-111 (复审 H-1): 合规判断用精确比较 pclk2 <= 14*div——旧式
    # pclk2//div <= 14 的 floor 截断会把 29/2=14.5MHz 粉饰成 "14MHz 合规"
    # (实测 hclk∈{29,57,58,59} 越限)。72 下两式选档与显示值完全一致。
    pclk2 = apb_clock_mhz(hclk_mhz, "APB2", pclk2_mhz=pclk2_mhz)
    # (ADCPRE 位值, 分频数) — RM0008 CFGR ADCPRE[1:0]: 00=/2 01=/4 10=/6 11=/8
    for bits, div in ((0, 2), (1, 4), (2, 6), (3, 8)):
        if pclk2 <= 14 * div:
            break
    if pclk2 % div == 0:
        adc_clk_s = f"{pclk2 // div}"          # 整除: 纯整数, 72 下逐字节不变
    else:
        adc_clk_s = f"{pclk2 / div:.2f}"       # 非整除: 真值如实 (F-111 H-1)

    lines = []
    lines.append("/* ========================================================================")
    lines.append(f" * {adc} CH{ch} — {pin} (single conversion, 12-bit)")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk2_mhz=pclk2_mhz))
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. 时钟使能 */")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_{adc}EN | RCC_APB2ENR_IOP{port}EN;")
    lines.append("__DSB();")
    lines.append("")
    # F-087: 默认 ADCPRE=/2 → PCLK2/2 = 36MHz, 超出 ADC 14MHz 上限
    # (data/f103_known_issues.json "ADC.max_clock")。先清后置 CFGR 位 15:14
    # = 10b → ADCPRE=/6 = 12MHz; 用 |= 保留 CFGR 其他位。
    lines.append(f"/* 1b. ADC 时钟分频 — ADCPRE=/{div} ({adc_clk_s}MHz @ PCLK2={pclk2}MHz, ≤14MHz 上限) */")
    lines.append("RCC->CFGR &= ~(3UL << 14);         // 清 ADCPRE[1:0]")
    lines.append(f"RCC->CFGR |=  ({bits}UL << 14);         // ADCPRE={bits:02b}b → PCLK2/{div}")
    lines.append("")
    lines.append(f"/* 2. GPIO — {pin} 模拟输入 */")
    lines.append(f"GPIO{port}->{pin_cr_reg(pin)} &= ~(0xFUL << {shift});")
    lines.append("// CNF=00 MODE=00 → 模拟输入")
    lines.append("")
    lines.append("/* 3. ADC 配置 (单次转换, 软件触发) */")
    lines.append("// 采样时间: 55.5 cycles (推荐用于 12-bit 精度)")
    if ch >= 16:
        # F-119: 16=内部 vrefint, 17=内部 temp sensor — 不接外部引脚,
        # 上面的 GPIO 模拟输入步骤对内部通道无意义 (RM0008 §11.5)
        lines.append(f"// CH{ch} 为内部通道 ({'vrefint' if ch == 16 else '温度传感器'}) — 无需外部引脚")
    if ch <= 9:
        lines.append(f"{adc}->SMPR2 |= (5UL << {(ch)*3});  // CH{ch}: 55.5 cycles")
    else:
        lines.append(f"{adc}->SMPR1 |= (5UL << {(ch-10)*3});  // CH{ch}: 55.5 cycles")
    lines.append(f"{adc}->SQR3 = {ch};                 // 转换序列: 1 个通道 = CH{ch}")
    lines.append(f"{adc}->CR2 = 1;                    // ADON 上电")
    lines.append("")
    lines.append("/* 4. 单次转换 */")
    lines.append(f"static uint16_t adc_read_ch{ch}(void) {{")
    lines.append(f"    {adc}->CR2 |= (1UL << 22);    // SWSTART")
    lines.append(f"    while (!({adc}->SR & 2));    // 等待 EOC")
    lines.append(f"    return {adc}->DR & 0xFFF;     // 12-bit result")
    lines.append("}")
    lines.append("")
    lines.append("/* 5. 电压换算 (Vref=3.3V) */")
    lines.append("static uint32_t adc_to_mv(uint16_t val) {")
    lines.append("    return (uint32_t)val * 3300 / 4096;")
    lines.append("}")
    return "\n".join(lines)


def gen_timer_int(timer: str, period_ms: int,
                  tim_clk_mhz: int = None, hclk_mhz: int = 72,
                  pclk1_mhz: int | None = None) -> str:
    """生成定时中断代码

    F-110 优先级契约同 gen_pwm: 显式 tim_clk > hclk 推导 (= hclk,
    TIM2~4 内核 = APB1×2 抵消; TIM1 = APB2 = hclk)。
    WB-20260920-01 派生链: 显式 tim_clk > pclk1 派生 (APB1 族, §7.3.7)
    > hclk 推导; TIM1 (APB2) 维持 hclk 推导 (见 gen_pwm GAP-P-1 注)。

    F-086 修复两处 C 类静默缺陷:
      1. TIM1 的 CMSIS 向量名是 TIM1_UP_* (bit25 = TIM1_UP_IRQn);
         TIM1_IRQHandler/TIM1_IRQn 不存在 — 弱默认处理函数接管, 编译
         链接都不报错, ISR 永不执行;
      2. ARR 超 16 位 (period ≥ 63ms, 因 target_hz=1000//period_ms 整除)
         被硬件截断而注释照写名义周期 — 现显式报错 (周期类配置在固定
         PSC 下无合理近似, 不产出假装正确的配置)。
    """
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk1_mhz)
    if err:
        return err
    # F-111 (M-3): 显式 tim_clk 纳入域纪律 (同 gen_pwm)。
    if tim_clk_mhz is not None and tim_clk_mhz <= 0:
        return f"/* ERROR: tim_clk={tim_clk_mhz}MHz 非法 — 必须为正整数。*/"
    if tim_clk_mhz is None:
        tim_bus = TIM_BUS.get(timer, "APB1")   # F-077: TIM1 → APB2, 其余 APB1
        tim_clk_mhz = (tim_kernel_clock_mhz(hclk_mhz, pclk1_mhz)
                       if tim_bus == "APB1" else hclk_mhz)
    tim_bus = TIM_BUS.get(timer, "APB1")   # F-077: TIM1 → APB2, 其余 APB1
    tim_clock = TIM_CLOCK_BIT.get(timer, f"{timer}EN")

    # F-108 (L-1): period_ms<=0 结构化 ERROR, 不再 1000//0 traceback。
    if period_ms <= 0:
        return f"/* ERROR: period {period_ms}ms 非法 — 必须为正整数。*/"

    # IRQ 号
    irq_map = _GEN_MAPS["tim_irq"]   # F-158: 数据外置
    irq = irq_map.get(timer, 28)

    # 计算 PSC/ARR
    target_hz = 1000 // period_ms
    best_psc = 71  # → 1MHz
    best_arr = (tim_clk_mhz * 1_000_000) // ((best_psc + 1) * target_hz) - 1
    # F-086 缺陷 2: ARR 16 位上限。固定 PSC=71 无缩放自由度, 超限即不可
    # 表示 (实测阈值 63ms: target_hz=1000//period_ms 整除, 63ms→15Hz→
    # ARR 66665 > 65535)。对照 gen_pwm: 它有候选 ARR 表可缩放故走
    # "最接近值+旁注"; 本函数无自由度, 仿 gen_systick/gen_i2c 显式报错。
    if best_arr > 65535:
        # F-111 (复审 L-1): tick 文案随实际 tim_clk 诚实化——旧版恒写
        # "1MHz tick", hclk≠72 时 PSC=71 的 tick 实为 tim_clk/72 MHz。
        # 72MHz 下该式 = 1MHz → 文案逐字节不变 (兼容契约)。
        tick_str = ("1MHz" if tim_clk_mhz == 72
                    else f"{tim_clk_mhz * 1000000 // (best_psc + 1)}Hz")
        return (f"/* ERROR: {timer} ARR={best_arr} > 65535 (16-bit) — "
                f"period {period_ms}ms (target {target_hz}Hz) 在固定 "
                f"PSC={best_psc} ({tick_str} tick) 下不可表示; "
                f"请缩短周期或自行降低 tick 频率。*/")

    # F-086 缺陷 1: 向量表命名 — TIM1 走 TIM1_UP_* (更新中断), TIM2~4
    # 走常规命名
    vec_irq = f"{timer}_UP_IRQn" if timer == "TIM1" else f"{timer}_IRQn"
    vec_handler = (f"{timer}_UP_IRQHandler" if timer == "TIM1"
                   else f"{timer}_IRQHandler")

    lines = []
    lines.append("/* ========================================================================")
    lines.append(f" * {timer} 定时中断 — 每 {period_ms}ms 触发一次")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk1_mhz))
    lines.append(f" * TIM_CLK={tim_clk_mhz}MHz, PSC={best_psc}, ARR={best_arr}")
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. 时钟 + NVIC */")
    lines.append(f"RCC->{tim_bus}ENR |= RCC_{tim_bus}ENR_{tim_clock};")
    lines.append("__DSB();")
    lines.append(f"NVIC->ISER[{irq//32}] = (1UL << {irq%32});  // {vec_irq} = {irq}")
    lines.append("")
    lines.append("/* 2. Timer 配置 */")
    lines.append(f"{timer}->PSC = {best_psc};            // {tim_clk_mhz}MHz/({best_psc}+1) = {tim_clk_mhz*1000000//(best_psc+1)}Hz")
    lines.append(f"{timer}->ARR = {best_arr};           // → {1000//period_ms}Hz ({period_ms}ms)")
    lines.append(f"{timer}->DIER = 1;                  // 更新中断使能")
    lines.append(f"{timer}->CR1 = 1;                   // 使能")
    lines.append("")
    lines.append("/* 3. ISR */")
    lines.append(f"void {vec_handler}(void) {{")
    lines.append(f"    if ({timer}->SR & 1) {{          // 更新标志")
    lines.append(f"        {timer}->SR &= ~1;           // 清除标志")
    lines.append(f"        // TODO: 每 {period_ms}ms 执行的代码")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def gen_i2c(i2c_periph: str, speed_hz: int, scl: str, sda: str,
            hclk_mhz: int = 72, pclk1_mhz: int | None = None) -> str:
    """Generate I2C initialization code (register-level).

    WB-20260920-01: pclk1 显式覆盖逐键独立 (CR2.FREQ/CCR/TRISE 全随派生值)。

    Note: STM32F103 I2C has known errata (clock stretching, state machine
    hangs). For production, prefer HAL_I2C or software I2C (i2c_soft module).
    See: f103_known_issues.json → I2C section.
    """
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk1_mhz=pclk1_mhz)
    if err:
        return err
    i2c_n = i2c_periph[-1]  # "1" or "2"

    # Clock config
    clock_info = I2C_CLOCK_BIT.get(i2c_periph)
    if not clock_info:
        return f"/* ERROR: Unknown I2C peripheral {i2c_periph} */"
    bus_reg, bit_name, bit_num = clock_info
    # WB-20260920-01: 派生值用独立局部名 pclk1 (不复写覆盖参数——注记需以
    # 覆盖参数的 None-ness 区分"显式"与"推导")
    pclk1 = apb_clock_mhz(hclk_mhz, "APB1", pclk1_mhz=pclk1_mhz)

    # Speed mode
    speed_info = I2C_SPEED_MODES.get(speed_hz)
    if not speed_info:
        return f"/* ERROR: Unsupported I2C speed {speed_hz}Hz. Supported: 100000, 400000 */"
    mode_name, is_fast, duty = speed_info

    # CCR calculation
    if is_fast:
        if not duty:
            ccr_val = pclk1 * 1000000 // (3 * speed_hz)
        else:
            ccr_val = pclk1 * 1000000 // (25 * speed_hz)
    else:
        ccr_val = pclk1 * 1000000 // (2 * speed_hz)
    # WB-20260920-01 (P1, L-5 收口): 静默 clamp 改显式 ERROR — 旧版
    # max(4, ...) 把 pclk1=1MHz × 400kHz 的 CCR=0 顶到 4 (实际 SCL≈83kHz
    # 却自称 400kHz) 且 CR2.FREQ=1 违反 RM0008 §27.5.2 (FREQ≥2)。
    # 既有测试仅钉默认 72 输出 (2026-09-20 grep 取证), 简报 §2 P1 条件
    # 满足 → 顺路修。pclk1=2 @100k (CCR=10) 等合法低频配置不受影响。
    if pclk1 < 2:
        return (f"/* ERROR: PCLK1={pclk1}MHz < 2 — CR2.FREQ 下限为 2 "
                f"(RM0008 §27.5.2), 该时钟下 I2C 不可用。*/")
    if ccr_val < 4:
        return (f"/* ERROR: {i2c_periph} @{speed_hz}Hz 在 PCLK1="
                f"{pclk1}MHz 下 CCR={ccr_val} < 4 — 目标速率超出该时钟"
                f"可表达范围 (旧版静默 clamp, 实际 SCL 远低于请求值); "
                f"请提高 PCLK1 或降低速率。*/")
    ccr_val = min(4095, ccr_val)  # 上限截断 (现支持速率×合法 pclk1 域不可达, 保留防御)

    # TRISE calculation
    if is_fast:
        trise_val = (pclk1 * 300 // 1000) + 1
    else:
        trise_val = pclk1 + 1
    trise_val = max(1, min(63, trise_val))

    # GPIO config
    scl_port = pin_port(scl)
    sda_port = pin_port(sda)
    scl_shift = pin_cr_shift(scl)
    sda_shift = pin_cr_shift(sda)

    fs_bit = " | (1<<15)" if is_fast else ""

    lines = []
    lines.append("/* ========================================================================")
    lines.append(f" * {i2c_periph} — {speed_hz//1000}kHz {mode_name} mode, SCL={scl} SDA={sda}")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk1_mhz=pclk1_mhz))
    lines.append(f" * CCR=0x{ccr_val:03X} ({ccr_val}), TRISE=0x{trise_val:02X} ({trise_val})")
    lines.append(" * WARNING: STM32F103 I2C has known errata. Consider software I2C for")
    lines.append(" *          production use. See f103_known_issues.json.")
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. Clock enable */")
    lines.append(f"RCC->{bus_reg} |= RCC_{bus_reg}_{bit_name};")
    lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{scl_port}EN | RCC_APB2ENR_IOP{sda_port}EN;")
    lines.append("__DSB();")
    lines.append("")
    lines.append(f"/* 2. GPIO — SCL={scl} AF-OD, SDA={sda} AF-OD */")
    lines.append(f"GPIO{scl_port}->{pin_cr_reg(scl)} &= ~(0xFUL << {scl_shift});")
    lines.append(f"GPIO{scl_port}->{pin_cr_reg(scl)} |=  (0xFUL << {scl_shift});")
    lines.append(f"GPIO{sda_port}->{pin_cr_reg(sda)} &= ~(0xFUL << {sda_shift});")
    lines.append(f"GPIO{sda_port}->{pin_cr_reg(sda)} |=  (0xFUL << {sda_shift});")
    lines.append("")
    lines.append(f"/* 3. {i2c_periph} config */")
    lines.append(f"{i2c_periph}->CR2 = {pclk1};               // FREQ = PCLK1 MHz")
    lines.append(f"{i2c_periph}->CCR = 0x{ccr_val:03X}{fs_bit};       // {speed_hz//1000}kHz, CCR={ccr_val}")
    lines.append(f"{i2c_periph}->TRISE = {trise_val};                // max rise time = {trise_val}")
    lines.append(f"{i2c_periph}->CR1 = 1;                  // PE=1, enable")
    lines.append("")
    lines.append("/* 4. Poll write helper */")
    lines.append(f"static error_chain_t i2c{i2c_n}_write(uint8_t dev_addr, uint8_t reg, uint8_t data) {{")
    lines.append("    uint32_t timeout = 100000;")
    lines.append(f"    while ({i2c_periph}->SR2 & (1<<1)) {{        // wait BUSY=0")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE001, \"I2C BUSY timeout\");")
    lines.append("    }")
    lines.append(f"    {i2c_periph}->CR1 |= (1<<8);                 // START")
    lines.append("    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & 1)) {{           // wait SB")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE002, \"I2C START timeout\");")
    lines.append("    }")
    lines.append(f"    {i2c_periph}->DR = (dev_addr << 1);          // ADDR + W")
    lines.append("    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<1))) {{       // wait ADDR")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE003, \"I2C ADDR timeout\");")
    lines.append("    }")
    lines.append(f"    (void){i2c_periph}->SR2;                       // clear ADDR")
    lines.append(f"    {i2c_periph}->DR = reg;                       // send register")
    lines.append("    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<7))) {{       // wait TXE")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE004, \"I2C TXE timeout\");")
    lines.append("    }")
    lines.append(f"    {i2c_periph}->DR = data;                      // send data")
    lines.append("    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<7))) {{")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE004, \"I2C TXE timeout\");")
    lines.append("    }")
    lines.append("    timeout = 100000;")
    lines.append(f"    while (!({i2c_periph}->SR1 & (1<<2))) {{       // wait BTF")
    lines.append("        if (--timeout == 0) return ERR_PLAIN(0xE005, \"I2C BTF timeout\");")
    lines.append("    }")
    lines.append(f"    {i2c_periph}->CR1 |= (1<<9);                  // STOP")
    lines.append("    return ERR_OK;")
    lines.append("}")
    return "\n".join(lines)


def gen_spi(spi_periph: str, mode: int, nss: str, sck: str,
            miso: str, mosi: str, baud_div: int = 16,
            hclk_mhz: int = 72, pclk1_mhz: int | None = None,
            pclk2_mhz: int | None = None) -> str:
    """Generate SPI initialization code (register-level).

    SPI1 on APB2, SPI2 on APB1 (F-110: 总线时钟经 apb_clock_mhz 推导;
    WB-20260920-01: pclk1/pclk2 显式覆盖逐键独立)。
    Mode = CPOL:CPHA (0-3). NSS handled as GPIO output (software CS).
    """
    err = _hclk_error(hclk_mhz)  # F-111 (M-3): 库级域校验
    if err:
        return err
    err = _pclk_error(hclk_mhz, pclk1_mhz, pclk2_mhz)
    if err:
        return err
    spi_n = spi_periph[-1]  # "1" or "2"

    clock_info = SPI_CLOCK_BIT.get(spi_periph)
    if not clock_info:
        return f"/* ERROR: Unknown SPI peripheral {spi_periph} */"
    bus_reg, bit_name, bit_num, bus = clock_info
    pclk_mhz = apb_clock_mhz(hclk_mhz, bus, pclk1_mhz, pclk2_mhz)

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
    scl_shift = pin_cr_shift(sck)
    miso_shift = pin_cr_shift(miso)
    mosi_shift = pin_cr_shift(mosi)
    nss_shift = pin_cr_shift(nss)

    # CR1 bit fields
    cr1 = (br_val << 3) | (cpol << 1) | (cpha << 0) | (1 << 2)  # MSTR=1

    lines = []
    lines.append("/* ========================================================================")
    lines.append(f" * {spi_periph} — Mode {mode} ({mode_names.get(mode, '?')}), {spi_freq_hz//1000}kHz")
    lines.append(f" * SCK={sck} MISO={miso} MOSI={mosi} NSS={nss} (software CS)")
    lines.extend(_hclk_precondition_note(hclk_mhz, pclk1_mhz, pclk2_mhz))
    lines.append(f" * PCLK={pclk_mhz}MHz, BR[2:0]={br_val} (/ {actual_div})")
    lines.append(" * ======================================================================== */")
    lines.append("")
    lines.append("/* 1. Clock enable */")
    lines.append(f"RCC->{bus_reg} |= RCC_{bus_reg}_{bit_name};")
    # Collect unique ports for clock enable
    ports = sorted(set([pin_port(sck), pin_port(miso), pin_port(mosi), pin_port(nss)]))
    for port in ports:
        lines.append(f"RCC->APB2ENR |= RCC_APB2ENR_IOP{port}EN;")
    lines.append("__DSB();")
    lines.append("")
    lines.append("/* 2. GPIO config */")
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
    lines.append("")
    lines.append(f"/* 3. {spi_periph} config */")
    lines.append(f"// CR1: BR[2:0]={br_val} CPOL={cpol} CPHA={cpha} MSTR=1 SSM=1 SSI=1")
    lines.append(f"{spi_periph}->CR1 = 0x{cr1:04X} | (1<<9) | (1<<8);  // SSM+SSI (software NSS)")
    lines.append("// CR2: SSOE=0 (output disabled, manual CS)")
    lines.append(f"{spi_periph}->CR1 |= (1<<6);                        // SPE=1, enable")
    lines.append("")
    lines.append("/* 4. CS control macros */")
    lines.append(f"#define SPI{spi_n}_CS_LOW()  GPIO{pin_port(nss)}->BRR = (1UL << {pin_num(nss)})")
    lines.append(f"#define SPI{spi_n}_CS_HIGH() GPIO{pin_port(nss)}->BSRR = (1UL << {pin_num(nss)})")
    lines.append("")
    lines.append("/* 5. Poll transfer */")
    lines.append(f"static uint8_t spi{spi_n}_transfer(uint8_t tx_byte) {{")
    lines.append(f"    while (!({spi_periph}->SR & (1<<1)));  // wait TXE")
    lines.append(f"    {spi_periph}->DR = tx_byte;")
    lines.append(f"    while (!({spi_periph}->SR & (1<<0)));  // wait RXNE")
    lines.append(f"    return {spi_periph}->DR;")
    lines.append("}")
    lines.append("")
    lines.append("/* 6. Burst write example */")
    lines.append(f"static void spi{spi_n}_write_burst(uint8_t *buf, int len) {{")
    lines.append(f"    SPI{spi_n}_CS_LOW();")
    lines.append("    for (int i = 0; i < len; i++) {")
    lines.append(f"        while (!({spi_periph}->SR & (1<<1)));  // wait TXE")
    lines.append(f"        {spi_periph}->DR = buf[i];")
    # F-178 (WB-20260920-04, H-3): RM0008 §25.3.5 —— SPI 接收是**单缓冲**:
    # 读 DR 才清 RXNE; RXNE 未清时下一字节到达只置 OVR 并把该字节丢弃。
    # 只写不读的 burst 收尾会把最后一个陈旧字节滞留在缓冲里并留下 OVR=1,
    # 随后同片段生成的 spiN_transfer 的 wait-RXNE 立即通过、返回 burst 残留
    # 字节, 本次真收到的字节被 OVR 丢弃且无人清理 —— "发命令再收数据"的
    # 传感器读写序列全体错位。故每写一字节必须逐字节排空。
    lines.append(f"        while (!({spi_periph}->SR & (1<<0)));  // wait RXNE")
    lines.append(f"        (void){spi_periph}->DR;                // drain RX (清 RXNE, 防 OVR 滞留)")
    lines.append("    }")
    lines.append(f"    while ({spi_periph}->SR & (1<<7));  // wait BSY=0")
    lines.append(f"    SPI{spi_n}_CS_HIGH();")
    lines.append("}")
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
            # F-074: KB 的 rcc_register 本身已带 ENR 后缀 (APB1ENR/APB2ENR/AHBENR,
            # 实测全表 55 外设无一例外), 旧拼接再补 ENR 会产出 RCC_APB1ENRENR
            # 这种不存在的宏, AI 照抄进 C 代码即编译失败。防御式归一化:
            # 未来 KB 条目若只写 "APB1" 也能拼出合法宏名。
            reg = str(clock_info.get('rcc_register', '?'))
            # F-187 (GAP-F-16, WB-20260922-02 取证): F-074 的"补 ENR"归一化隐含
            # "寄存器名要么以 ENR 结尾要么是可补后缀的词干"前提, BDCR 破口——
            # "BDCR" 补出 RCC_BDCRENR 这种不存在的宏 (F-074 同族未覆盖面)。
            # 根治 = 以 KB 自身 RCC.registers 键表为事实源: 表内寄存器名(BDCR/CSR/
            # CIR/各ENR)一律原样信任; 仅"非表内且不以 ENR 结尾"的词干才补 ENR
            # (保留 F-074 对 "APB1" 形态的防御意图)。
            _rcc_regs = ref.get("peripherals", {}).get("RCC", {}).get("registers", {})
            if not reg.endswith("ENR") and reg not in _rcc_regs:
                reg = f"{reg}ENR"
            deps.append(f"- Clock: RCC_{reg} bit {clock_info.get('rcc_bit', '?')} ({clock_info.get('rcc_bit_name', '?')})")
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
 * @note This file is auto-generated. Regenerate from the embedded-toolkit
 *       repo root with: python scripts/gen_periph.py --type doc --periph {periph_name}
 */
"""

    # Build Markdown doc
    md = f"# {periph_name} Peripheral Reference\n\n"
    md += f"- **Base**: {base} | **Bus**: {bus} | **Chip**: STM32F103C8T6\n"
    md += f"- **Description**: {desc}\n\n"
    md += f"## Registers\n\n{reg_table}\n\n"
    if deps:
        md += "## Dependencies\n\n" + "\n".join(deps) + "\n\n"
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

def _emit(out: str) -> None:
    """打印生成物; ERROR 注释 → 退出码 1。

    F-086 先例 (gen_timer_int) 泛化: 所有带"不可表示"错误分支的生成器共用
    这一出口——机器消费方按退出码判失败, 不产出被硬件截断/静默无效却自称
    正确的配置。"""
    print(out)
    if out.startswith("/* ERROR"):
        sys.exit(1)


def main():
    # F-191 (WB-20260926-02 T3, 销 WB-05 M-2): --timer 登记集 = gen-maps
    # tim_bus ∪ tim_irq 键集 (与 ref.json _relationships 收编的 TIM 全集
    # 一致, 11 个)。不取 ref.json TIM 字面全集: TIM8/10/11 无
    # _relationships 条目, tim_irq 无源可互证, 放行即生成半伪代码。
    registered_timers = sorted(set(TIM_BUS) | set(_GEN_MAPS["tim_irq"]))
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

GPIO 模式 (F-103: 由 --mode choices 强制, 未知模式报错):
  """ + ", ".join(sorted(GPIO_MODE_MAP)) + """
        """
    )
    parser.add_argument("--type", required=True,
                        choices=["gpio", "usart", "pwm", "adc", "systick", "timer-int",
                                 "i2c", "spi", "doc"],
                        help="外设类型")
    # gpio
    parser.add_argument("--pin", default="", help="引脚: PA0, PC13")
    # F-103: --mode 加 choices。旧行为是 mode_map.get(mode, ("0x3", mode))
    # 未知 mode 静默降级为推挽输出——拼写错误 (out-pp-50mhz2) 会产出"看起来
    # 合法"的输出配置, 与 mode 标签相反。argparse 层直接拒, 生成函数层
    # (gen_gpio 的 ERROR 分支) 兜库调用方。
    parser.add_argument("--mode", default="out-pp-50mhz",
                        choices=sorted(GPIO_MODE_MAP), help="GPIO 模式")
    # usart
    parser.add_argument("--usart", default="USART1", help="USART 外设: USART1/2/3")
    parser.add_argument("--baud", type=int, default=115200, help="波特率")
    parser.add_argument("--tx", default="PA9", help="TX 引脚")
    parser.add_argument("--rx", default="PA10", help="RX 引脚")
    # pwm
    parser.add_argument("--timer", default="TIM2",
                        help=f"定时器 (已登记: {', '.join(registered_timers)}; "
                             f"默认 TIM2)")
    parser.add_argument("--ch", type=int, default=1, help="通道: PWM 1-4 / ADC 0-17 (16/17 内部通道)")
    parser.add_argument("--freq", type=int, default=1000, help="PWM 频率 Hz")
    parser.add_argument("--duty", type=int, default=50, help="占空比 %% (0-100)")
    # F-110: --hclk 单一入口 (标准 APB 分频假设 HPRE=1/PPRE2=1/PPRE1=2,
    # CubeMX 默认即此); --tim-clk 未显式传时由 hclk 推导, 显式传值胜出。
    parser.add_argument("--hclk", type=int, default=72,
                        help=f"内核时钟 MHz (默认 72; 有效 {HCLK_MIN}~{HCLK_MAX}; "
                             f"APB1=hclk/2, APB2=hclk, 标准分频假设)")
    parser.add_argument("--tim-clk", type=int, default=None,
                        help="定时器时钟 MHz (显式值优先; 缺省由 --hclk 推导)")
    # WB-20260920-01: --pclk1/--pclk2 显式 APB 时钟覆盖 (逐键独立;
    # 缺省维持 F-110 标准分频推导, 默认路径输出逐字节不变)。
    parser.add_argument("--pclk1", type=int, default=None,
                        help=f"APB1 时钟 MHz 显式覆盖 (有效 1~{PCLK1_MAX} 且 "
                             f"≤hclk; 缺省 = hclk/2 推导; TIM2~4 内核按 "
                             f"RM0008 §7.3.7 随之派生)")
    parser.add_argument("--pclk2", type=int, default=None,
                        help="APB2 时钟 MHz 显式覆盖 (有效 1~72 且 ≤hclk; "
                             "缺省 = hclk)")
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

    # F-110: hclk 域校验前置 (仅时钟相关 type; gpio/doc 不涉及时钟)。
    # 越界走 _emit 统一 ERROR→exit 1 (F-103 边界纪律)。
    # WB-20260920-01: --pclk1/--pclk2 域校验同层前置 (非整数由 argparse
    # type=int 拒收 rc=2; 越界/>hclk 走 _emit ERROR→exit 1)。
    if args.type in ("usart", "pwm", "adc", "systick", "timer-int", "i2c", "spi"):
        if not (HCLK_MIN <= args.hclk <= HCLK_MAX):
            _emit(f"/* ERROR: --hclk={args.hclk} 越界 — 有效范围 "
                  f"{HCLK_MIN}~{HCLK_MAX} MHz (F103 规格; pclk1=hclk/2 须≥1)。*/")
        pclk_err = _pclk_error(args.hclk, args.pclk1, args.pclk2)
        if pclk_err:
            _emit(pclk_err)

    # F-191 (WB-20260926-02 T3): 未登记名此前被三连 .get 缺省 (APB1 /
    # 28 / f"{timer}EN") 吞成"看起来合法"的错码 — TIM9 三层错实录
    # (WB-20260925-01 M-2: APB1ENR_TIM9EN 宏不存在 / ISER 28 是 TIM2 的 /
    # 内核时钟误走 pclk1 分支)。显式收口 (F-185 P-3 --baud-div 同款契约:
    # _emit "/* ERROR" → rc=1, 合法集随文案); 库态 .get 缺省维持 P-3
    # 先例不动 (库调用方域纪律由生成函数 F-111 层管辖)。
    if (args.type in ("pwm", "timer-int")
            and args.timer not in registered_timers):
        _emit("/* ERROR: 非法 --timer %r, 已登记集: %s */"
              % (args.timer, ", ".join(registered_timers)))

    if args.type == "gpio":
        if not args.pin:
            print("Error: --pin required for GPIO", file=sys.stderr)
            sys.exit(1)
        _emit(gen_gpio(args.pin, args.mode))

    elif args.type == "usart":
        _emit(gen_usart(args.usart, args.baud, args.tx, args.rx, args.hclk,
                        args.pclk1, args.pclk2))

    elif args.type == "pwm":
        if not args.pin and args.ch and args.timer:
            args.pin = TIM_CH_PINS.get((args.timer, args.ch), "")
        if not args.pin:
            print("Error: --pin required for PWM (or use --timer + --ch for auto-detect)", file=sys.stderr)
            sys.exit(1)
        _emit(gen_pwm(args.timer, args.ch, args.pin, args.freq, args.duty,
                      args.tim_clk, args.hclk, args.pclk1))

    elif args.type == "adc":
        if not args.pin:
            print("Error: --pin required for ADC", file=sys.stderr)
            sys.exit(1)
        # F-119 (工单 P0-4): 旧版此处裸 print — ERROR 也恒 exit 0。
        # 改走 _emit 统一 ERROR→exit 1 纪律 (F-103 收敛遗漏的一半)。
        _emit(gen_adc(args.adc, args.ch, args.pin, args.hclk, args.pclk2))

    elif args.type == "systick":
        _emit(gen_systick(args.freq, args.hclk))

    elif args.type == "timer-int":
        _emit(gen_timer_int(args.timer, args.period_ms, args.tim_clk,
                            args.hclk, args.pclk1))

    elif args.type == "i2c":
        _emit(gen_i2c(args.i2c, args.speed, args.scl, args.sda, args.hclk,
                      args.pclk1))

    elif args.type == "spi":
        # F-185 (P-3, WB-20260919-05 审查 M-2 伴生项): 非法 --baud-div 静默回落
        # /16 违反 F-103 "非法值禁止静默回落默认" 统一纪律 —— 改显式 ERROR→rc=1,
        # 复用 _emit 的 "/* ERROR" 出口 (机器消费方按退出码判失败)。
        if args.baud_div not in SPI_BAUD_DIV:
            _emit("/* ERROR: 非法 --baud-div %r, 合法值: %s */"
                  % (args.baud_div, sorted(SPI_BAUD_DIV)))
        _emit(gen_spi(args.spi, args.spi_mode, args.nss, args.sck,
                      args.miso, args.mosi, args.baud_div, args.hclk,
                      args.pclk1, args.pclk2))

    elif args.type == "doc":
        if not args.periph:
            print("Error: --periph required for --type doc", file=sys.stderr)
            sys.exit(1)
        doc_out = gen_doc(args.periph, args.out_dir)
        # F-178 P1 (WB-20260920-04, 09-19 审查 M-11): gen_doc 的"外设不存在"
        # 返回值 (test_gen_periph.py 已钉其原文, 故不改返回格式) 必须按**失败**
        # 退出 —— 与同文件 _emit 的 ERROR→exit 1 纪律同款, 机器消费方按 rc
        # 判定, 不再把 "Error: ... not found" 当成功。错误走 stderr。
        if doc_out.startswith("Error:"):
            print(doc_out, file=sys.stderr)
            sys.exit(1)
        print(doc_out)


if __name__ == "__main__":
    main()
