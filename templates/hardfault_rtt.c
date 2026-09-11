/**
  ******************************************************************************
  * @file    hardfault_rtt.c
  * @brief   HardFault C 级现场诊断 — SEGGER RTT 后端 (B1/F-115, toolkit 模板)
  *
  * 移植源: stm32f103-blink (semihosting printf 版, 2026-07 真机端到端验证,
  * commit 7370ba1 实录) —— 解码逻辑/字段文案原样保留, 输出通道换
  * SEGGER_RTT_WriteString (printf→RTT, 无调试器 host 时不再 BKPT halt)。
  *
  * 契约 (verify.py Step 4b 与 hardfault.py 依赖, 勿改):
  *   - 首行必含 "=== HARDFAULT ===" (verify 标记判据, 子串匹配区分大小写)
  *   - 纯整数格式 (%08X), 不依赖浮点 printf (nano.specs 教训)
  *   - 只读 SCB 不清粘滞位 —— 保位留证据, 清位归工具 (F-109 设计修正)
  *   - 末尾 for(;;) 自旋保现场 (不复位: 复位会丢 OpenOCD 层 2 取证窗口)
  *
  * 用法 (RTT 闭环工程):
  *   1. 本文件与 SEGGER_RTT.c 一起进构建 (Makefile C_SOURCES 加一行)
  *   2. 工程自有的 HardFault_Handler 死循环桩须删除/让位 (启动文件 weak 默认
  *      即可) —— 本文件提供强符号, 重复定义会链接报错, 报错即提醒
  *   3. RTT 初始化须在主循环前; 故障早于 RTT init 时本 handler 仍安全
  *      (SEGGER_RTT 未 init 时 WriteString 返回不崩, 标记写不出 →
  *      verify 落"烧录过但空捕获"兜底路径, 归因语义不变)
  ******************************************************************************
  */

#include "SEGGER_RTT.h"
#include <stdint.h>

/* SCB 故障寄存器 (Cortex-M3 标准地址, 不依赖 HAL 头) */
#define SCB_CFSR  (*(volatile uint32_t *)0xE000ED28UL)
#define SCB_HFSR  (*(volatile uint32_t *)0xE000ED2CUL)
#define SCB_MMFAR (*(volatile uint32_t *)0xE000ED34UL)
#define SCB_BFAR  (*(volatile uint32_t *)0xE000ED38UL)

/* 异常入栈帧布局: 硬件自动压 R0-R3,R12,LR,PC,xPSR (0-7 号字) */
#define FRAME_LR   5U
#define FRAME_PC   6U

#define RTT_CH     0U

static void _hf_puts(const char *s)
{
    SEGGER_RTT_WriteString(RTT_CH, s);
}

/* 纯整数 hex 输出 (同 blink 版思路, 不经 printf 路径) */
static void _hf_puthex(uint32_t v)
{
    static const char hexd[] = "0123456789ABCDEF";
    char buf[9];
    int i;
    buf[8] = '\0';
    for (i = 7; i >= 0; i--) {
        buf[i] = hexd[v & 0xFUL];
        v >>= 4;
    }
    SEGGER_RTT_Write(RTT_CH, buf, 8U);
}

static void _hf_flag(uint32_t v, unsigned bit, const char *name)
{
    if (v & (1UL << bit)) {
        _hf_puts(name);
        _hf_puts("\r\n");
    }
}

/**
  * @brief 异常上下文 C 处理体 (naked 汇编入口传入压栈帧指针)。
  *        used: 仅被 naked 函数的 asm 引用, 编译器视角"未使用"会被优化掉
  *        —— -O2 下真丢符号, 链接才炸 (B1 自查修正)。
  */
__attribute__((used))
static void _hardfault_body(volatile uint32_t *frame)
{
    uint32_t cfsr  = SCB_CFSR;
    uint32_t hfsr  = SCB_HFSR;
    uint32_t bfar  = SCB_BFAR;
    uint32_t mmfar = SCB_MMFAR;
    uint32_t pc    = frame ? frame[FRAME_PC] : 0UL;
    uint32_t lr    = frame ? frame[FRAME_LR] : 0UL;

    _hf_puts("\r\n=== HARDFAULT ===\r\n");

    _hf_puts("[HF] CFSR="); _hf_puthex(cfsr);
    _hf_puts(" HFSR=");     _hf_puthex(hfsr);
    _hf_puts("\r\n");

    _hf_puts("[HF] BFAR="); _hf_puthex(bfar);
    _hf_puts(" MMFAR=");    _hf_puthex(mmfar);
    _hf_puts("\r\n");

    _hf_puts("[HF] PC=");   _hf_puthex(pc);
    _hf_puts(" LR=");       _hf_puthex(lr);
    _hf_puts("\r\n");

    /* 位域解码: 一律用 CFSR 绝对位号 (MFSR 0-7 / BFSR 8-15 / UFSR 16-31),
       文案与 semihosting 版一致 → 反馈库 fault_type 匹配不破 (B1 自查:
       早期按字节拆传曾把 UNALIGNED 位号错位成恒不命中) */
    if (hfsr & (1UL << 30)) _hf_puts("[HF] HFSR: FORCED (escalated)\r\n");
    if (hfsr & (1UL << 1))  _hf_puts("[HF] HFSR: VECTTBL (bad VTOR?)\r\n");

    _hf_flag(cfsr, 8,  "[HF] BFSR: IBUSERR");
    if (cfsr & (1UL << 9)) {
        _hf_puts("[HF] BFSR: PRECISERR BFAR=");
        _hf_puthex(bfar); _hf_puts("\r\n");
    }
    _hf_flag(cfsr, 10, "[HF] BFSR: IMPRECISERR");
    _hf_flag(cfsr, 11, "[HF] BFSR: UNSTKERR");
    _hf_flag(cfsr, 12, "[HF] BFSR: STKERR");

    _hf_flag(cfsr, 16, "[HF] UFSR: UNDEFINSTR");
    _hf_flag(cfsr, 17, "[HF] UFSR: INVSTATE");
    _hf_flag(cfsr, 18, "[HF] UFSR: INVPC");
    _hf_flag(cfsr, 19, "[HF] UFSR: NOCP");
    _hf_flag(cfsr, 24, "[HF] UFSR: UNALIGNED");
    _hf_flag(cfsr, 25, "[HF] UFSR: DIVBYZERO");

    _hf_flag(cfsr, 0,  "[HF] MFSR: IACCVIOL");
    if (cfsr & (1UL << 1)) {
        _hf_puts("[HF] MFSR: DACCVIOL MMFAR=");
        _hf_puthex(mmfar); _hf_puts("\r\n");
    }
    _hf_flag(cfsr, 3,  "[HF] MFSR: MUNSTKERR");
    _hf_flag(cfsr, 4,  "[HF] MFSR: MSTKERR");

    if (cfsr == 0UL && hfsr == 0UL) {
        _hf_puts("[HF] No SCB fault flags -- BKPT without debugger?\r\n");
    }

    /* 自旋保现场: OpenOCD 层 2 (hardfault.py) 靠 halt 读同一现场,
       复位/退出都会销毁证据; 粘滞位清除归工具 (F-109)。 */
    for (;;) {
        __asm volatile ("nop");
    }
}

/**
  * @brief 强符号覆盖启动文件 weak HardFault_Handler
  *        naked + MSP/PSP 甄别 (EXC_RETURN bit2): 线程态 PSP 出异常时
  *        帧在 PSP, 直接按 MSP 取会读到中断栈错位现场 (blink 教训 R3)
  */
__attribute__((naked))
void HardFault_Handler(void)
{
    __asm volatile (
        "tst   lr, #4          \n"   /* EXC_RETURN bit2: 0=MSP, 1=PSP   */
        "ite   eq              \n"
        "mrseq r0, msp         \n"
        "mrsne r0, psp         \n"
        "b     _hardfault_body \n"
    );
}
