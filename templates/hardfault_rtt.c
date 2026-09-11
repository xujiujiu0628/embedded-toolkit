/**
  ******************************************************************************
  * @file    hardfault_rtt.c
  * @brief   HardFault C-level on-site diagnosis - SEGGER RTT backend
  *          (B1/F-115 + F-116, toolkit template)
  *
  * Ported from: stm32f103-blink semihosting printf handler (2026-07,
  * end-to-end verified on real hardware, commit 7370ba1) - decode logic and
  * field wording kept as-is; output channel switched to SEGGER_RTT_WriteString
  * (printf -> RTT: no BKPT halt when no debugger host is attached).
  *
  * ASCII-only comments: toolchain-neutral (ARMCC-era lesson) - this file is
  * copied into arbitrary firmware projects. Code must stay ASCII too.
  *
  * CONTRACT (verify.py Step 4b and hardfault.py depend on this - do not change):
  *   - first line contains "=== HARDFAULT ===" (verify marker trigger,
  *     case-sensitive substring match)
  *   - a line "[HF] PC=xxxxxxxx LR=xxxxxxxx" MUST exist (F-116/H-1:
  *     hardfault.py --fault-text parses it - when halted inside the spinning
  *     handler, live PC points at the handler chain, NEVER at the fault
  *     site; the stacked-frame PC/LR printed here is the only fault-site
  *     evidence)
  *   - wb_hardfault_body is deliberately NON-static: it must appear in the
  *     linker map so layer-2 resolves handler-chain addresses honestly as
  *     wb_hardfault_body+N, not as whatever global symbol precedes (F-116/H-1)
  *   - pure integer %08X formatting, never %f/printf (nano.specs lesson)
  *   - SCB registers are READ ONLY - sticky bits are NOT cleared here:
  *     preserve bits = preserve evidence; clearing belongs to the tool
  *     (F-109 design correction)
  *   - ends with for(;;) spin to hold the scene (no reset: reset destroys
  *     the OpenOCD layer-2 forensics window)
  *
  * Usage (RTT closed-loop projects):
  *   1. add this file next to SEGGER_RTT.c in the build (Makefile C_SOURCES)
  *   2. remove/replace the project's own HardFault_Handler while(1) stub -
  *      this file provides the strong symbol; duplicate definition = link
  *      error, which is itself the reminder
  *   3. RTT must be initialized before the main loop; a fault BEFORE RTT
  *      init is still safe here (SEGGER_RTT auto-initializes on first write,
  *      worst case the marker is lost -> verify falls into the
  *      empty-capture fallback, attribution semantics unchanged)
  *
  * Known limits (F-116/L-5): on STKERR/UNSTKERR (exception push itself
  * failed) the stacked frame is incomplete, frame[5]/[6] may be garbage -
  * trust the SCB registers from layer 2; this line is best-effort evidence.
  * A corrupted stack this early double-faults into lockup (no marker).
  ******************************************************************************
  */

#include "SEGGER_RTT.h"
#include <stdint.h>

/* SCB fault registers (Cortex-M3 standard addresses, no HAL dependency) */
#define SCB_CFSR  (*(volatile uint32_t *)0xE000ED28UL)
#define SCB_HFSR  (*(volatile uint32_t *)0xE000ED2CUL)
#define SCB_MMFAR (*(volatile uint32_t *)0xE000ED34UL)
#define SCB_BFAR  (*(volatile uint32_t *)0xE000ED38UL)

/* exception frame layout: hardware pushes R0,R1,R2,R3,R12,LR,PC,xPSR (0-7) */
#define FRAME_LR   5U
#define FRAME_PC   6U

#define RTT_CH     0U

static void _hf_puts(const char *s)
{
    SEGGER_RTT_WriteString(RTT_CH, s);
}

/* pure integer hex output (no printf path, nano.specs-safe) */
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
  * @brief C body of the handler (naked asm entry passes the stacked frame).
  *        used: only referenced from asm, compiler would otherwise drop it;
  *        NON-static on purpose so it lands in the map (see CONTRACT above).
  */
__attribute__((used))
void wb_hardfault_body(volatile uint32_t *frame)
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
    _hf_puts((cfsr & (1UL << 15)) ? " (valid)\r\n" : " (INVALID)\r\n");
    _hf_puts("[HF] MMFAR="); _hf_puthex(mmfar);
    _hf_puts((cfsr & (1UL << 7)) ? " (valid)\r\n" : " (INVALID)\r\n");

    _hf_puts("[HF] PC=");   _hf_puthex(pc);
    _hf_puts(" LR=");       _hf_puthex(lr);
    _hf_puts("\r\n");

    /* bit decode: CFSR absolute bit numbers (MFSR 0-7 / BFSR 8-15 /
       UFSR 16-31). Wording matches the semihosting-era lines so the
       feedback-db fault_type matching keeps working (F-115 self-check:
       an early byte-split variant misnumbered UNALIGNED/DIVBYZERO). */
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

    /* spin to hold the scene: OpenOCD layer 2 (hardfault.py) reads THIS
       scene via halt; reset or exit destroys it. Sticky-bit clearing is
       the tool's job (F-109). */
    for (;;) {
        __asm volatile ("nop");
    }
}

/**
  * @brief strong symbol overriding the startup-file weak HardFault_Handler.
  *        naked + EXC_RETURN bit2: thread-mode-on-PSP faults stack the frame
  *        on PSP; reading MSP blindly yields a bogus frame (blink lesson R3)
  */
__attribute__((naked))
void HardFault_Handler(void)
{
    __asm volatile (
        "tst   lr, #4            \n"   /* EXC_RETURN bit2: 0=MSP, 1=PSP */
        "ite   eq                \n"
        "mrseq r0, msp           \n"
        "mrsne r0, psp           \n"
        "b     wb_hardfault_body \n"
    );
}
