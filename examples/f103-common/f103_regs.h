/*
 * f103_regs.h — 样例工厂共享寄存器层 (裸偏移, 无 HAL/LL/CMSIS 依赖)
 *
 * 数据纪律 (WB-20260919-04):
 *   - 所有外设基地址 / 寄存器偏移 / 位域名称逐项取自
 *     data/stm32f103-ref.json (v2.0.0, 55 外设), 每行注明 anchor;
 *     禁止凭 ST 文档记忆默写。对不上的差异记 GAPREPORT, 不在本头内圆场。
 *   - error_chain_t / ERR_PLAIN / ERR_OK 是 gen_periph 生成体引用的
 *     既有契约 (tests/test_gen_syntax_smoke.py STUB_HEADER 同源), 本头
 *     提供样本侧最小实现。
 *   - __DSB/__WFI 为编译级样例的同步屏障最小宏; host mock 测试
 *     (F103_SAMPLE_HOST_TEST) 下置空。
 *   - F103_MOCK_<外设> 宏把该外设实例重定向到 host 内存结构,
 *     供 `make test` (host gcc) 断言寄存器写入序列与纯逻辑换算。
 */
#ifndef F103_REGS_H
#define F103_REGS_H

#include <stdint.h>

/* ── gen_periph 生成体契约垫片 (与 tests/test_gen_syntax_smoke.py 同源) ── */
typedef struct { uint16_t code; const char *msg; } error_chain_t;
#define ERR_OK   ((error_chain_t){0u, (const char *)0})
#define ERR_PLAIN(code, msg_) ((error_chain_t){(uint16_t)(code), (msg_)})

/* ── 同步屏障 (架构指令, 非 ref.json 域; host 测试置空) ── */
#ifdef F103_SAMPLE_HOST_TEST
#define __DSB() ((void)0)
#define __WFI() ((void)0)
#else
#define __DSB() __asm volatile ("dsb" ::: "memory")
#define __WFI() __asm volatile ("wfi")
#endif

/* ── 寄存器结构 (成员顺序即地址递增, 偏移 = ref.json peripherals.<P>.registers) ── */

typedef struct {   /* ref.json peripherals.RCC */
    volatile uint32_t CR, CFGR, CIR, APB2RSTR, APB1RSTR,
        AHBENR, APB2ENR, APB1ENR, BDCR, CSR;
} RCC_TypeDef;

typedef struct {   /* ref.json peripherals.GPIOA..GPIOG: CRL@0x00 .. LCKR@0x18 */
    volatile uint32_t CRL, CRH, IDR, ODR, BSRR, BRR, LCKR;
} GPIO_TypeDef;

typedef struct {   /* ref.json peripherals.USART1: SR@0x00 .. GTPR@0x10 */
    volatile uint32_t SR, DR, BRR, CR1, CR2, CR3, GTPR;
} USART_TypeDef;

typedef struct {   /* ref.json peripherals.TIM1 (通用/高级通用共用布局; TIM6/7
                     的保留位段落在未访问成员, 偏移一致) */
    volatile uint32_t CR1, CR2, SMCR, DIER, SR, EGR, CCMR1, CCMR2,
        CCER, CNT, PSC, ARR, RCR, CCR1, CCR2, CCR3, CCR4, BDTR,
        DCR, DMAR;
} TIM_TypeDef;

typedef struct {   /* ref.json peripherals.ADC1: SR@0x00 .. DR@0x4C */
    volatile uint32_t SR, CR1, CR2, SMPR1, SMPR2, JOFR1, JOFR2, JOFR3,
        JOFR4, HTR, LTR, SQR1, SQR2, SQR3, JSQR, JDR1, JDR2, JDR3,
        JDR4, DR;
} ADC_TypeDef;

typedef struct {   /* ref.json peripherals.I2C1: CR1@0x00 .. TRISE@0x20 */
    volatile uint32_t CR1, CR2, OAR1, OAR2, DR, SR1, SR2, CCR, TRISE;
} I2C_TypeDef;

typedef struct {   /* ref.json peripherals.SPI1: CR1@0x00 .. I2SCFGR@0x1C */
    volatile uint32_t CR1, CR2, SR, DR, CRCPR, RXCRCR, TXCRCR, I2SCFGR;
} SPI_TypeDef;

typedef struct {   /* Cortex-M3 核心外设 (架构定义; ref.json peripherals.SysTick) */
    volatile uint32_t CTRL, LOAD, VAL, CALIB;
} SysTick_Type;

typedef struct {   /* Cortex-M3 核心外设; ref.json peripherals.NVIC 已登记
                     ISER@0xE100 + ICER/ISPR/ICPR/IABR/IP (@F-179 P1 入册,
                     base 相对 offset 0x80/0x100/0x180/0x200/0x300 —
                     原 GAP-D-1 已闭合, 现为正式登记)。IP 为字节宽 (架构定义)。 */
    volatile uint32_t ISER[8u], ICER[8u], ISPR[8u], ICPR[8u], IABR[8u];
    volatile uint8_t  IP[240u];
} NVIC_Type;

typedef struct {   /* ref.json peripherals.DMA1: ISR@0x00 IFCR@0x04,
                     通道 1..7 起于 CCR1@0x08, 步进 0x14 (CCR2@0x1C..CCR7@0x80) */
    volatile uint32_t CCR, CNDTR, CPAR, CMAR, RESERVED;
} DMA_Channel_TypeDef;

typedef struct {
    volatile uint32_t ISR, IFCR;
    DMA_Channel_TypeDef CH[7];
} DMA_TypeDef;

typedef struct {   /* ref.json peripherals.FLASH: ACR@0x00 .. WRPR@0x20 (0x18 保留) */
    volatile uint32_t ACR, KEYR, OPTKEYR, SR, CR, AR, RESERVED, OBR, WRPR;
} FLASH_TypeDef;

typedef struct {   /* ref.json peripherals.EXTI: IMR@0x00 .. PR@0x14 */
    volatile uint32_t IMR, EMR, RTSR, FTSR, SWIER, PR;
} EXTI_TypeDef;

typedef struct {   /* ref.json peripherals.AFIO: EVCR@0x00 .. MAPR2@0x1C (0x18 保留) */
    volatile uint32_t EVCR, MAPR, EXTICR1, EXTICR2, EXTICR3, EXTICR4,
        RESERVED, MAPR2;
} AFIO_TypeDef;

typedef struct {   /* ref.json peripherals.IWDG: KR@0x00 .. SR@0x0C */
    volatile uint32_t KR, PR, RLR, SR;
} IWDG_TypeDef;

typedef struct {   /* ref.json peripherals.WWDG: CR@0x00 .. SR@0x08 */
    volatile uint32_t CR, CFR, SR;
} WWDG_TypeDef;

typedef struct {   /* ref.json peripherals.CRC: DR@0x00 IDR@0x04 CR@0x08 */
    volatile uint32_t DR, IDR, CR;
} CRC_TypeDef;

typedef struct {   /* ref.json peripherals.CAN: MCR@0x00, 邮箱三组步进 0x10
                     (TI0R@0x180..), FIFO 两组步进 0x10 (RI0R@0x1B0..) */
    volatile uint32_t MCR, MSR, TSR, RF0R, RF1R, IER, ESR, BTR;
    volatile uint32_t RESERVED0[88];          /* 0x20..0x17F */
    struct { volatile uint32_t TIR, TDTR, TDLR, TDHR; } TXM[3];   /* 0x180 */
    struct { volatile uint32_t RIR, RDTR, RDLR, RDHR; } RXM[2];   /* 0x1B0 */
    volatile uint32_t RESERVED1[12];          /* 0x1D0..0x1FF */
    volatile uint32_t FMR, FM1R, RESERVED2, FS1R, RESERVED3, FFA1R,
        RESERVED4, FA1R;                       /* 0x200..0x21C */
    volatile uint32_t F[28][2];                /* F0R1@0x240 .. F13R2@0x2AC */
} CAN_TypeDef;

typedef struct {   /* ref.json peripherals.DAC: CR@0x00 .. DOR2@0x30 */
    volatile uint32_t CR, SWTRIGR, DHR12R1, DHR12L1, DHR8R1, DHR12R2,
        DHR12L2, DHR8R2, DHR12RD, DHR12LD, DHR8RD, DOR1, DOR2;
} DAC_TypeDef;

typedef struct {   /* ref.json peripherals.RTC: CRH@0x00 .. ALRL@0x24 */
    volatile uint32_t CRH, CRL, PRLH, PRLL, DIVH, DIVL, CNTH, CNTL,
        ALRH, ALRL;
} RTC_TypeDef;

typedef struct {   /* ref.json peripherals.PWR: CR@0x00 CSR@0x04 */
    volatile uint32_t CR, CSR;
} PWR_TypeDef;

/* BKP: ref.json peripherals.BKP base=0x40006C04 (DR1 记在偏移 0)。
 * 本头按外设基址 0x40006C00 表示, DR1 = +0x04 — 与 ref.json 绝对地址
 * 0x40006C04 相等, 仅表达口径不同 (GAP-D-2 已记账)。 */
typedef struct {   /* DR1@0x04 .. DR42@0xB8, RTCCR@0x2C, CR@0x30, CSR@0x34 */
    volatile uint32_t RESERVED0;
    volatile uint32_t DR[42];
    volatile uint32_t RESERVED1[2];
    volatile uint32_t RTCCR, CR, CSR;
} BKP_TypeDef;

typedef struct {   /* ref.json peripherals.SDIO: POWER@0x00 .. FIFO@0x80
                     (0x40/0x44 与 0x4C..0x7C 为保留区间) */
    volatile uint32_t POWER, CLKCR, ARG, CMD, RESPCMD, RESP1, RESP2,
        RESP3, RESP4, DTIMER, DLEN, DCTRL, DCOUNT, STA, ICR, MASK;
    volatile uint32_t RESERVED0[2];
    volatile uint32_t FIFOCNT;
    volatile uint32_t RESERVED1[13];
    volatile uint32_t FIFO;
} SDIO_TypeDef;

typedef struct {   /* ref.json peripherals.FSMC — 样例仅用 BCR1/BTR1;
                     PCR/SR/PMEM/ECC/BWTR 区 (0x60..0x11C) 未在本头定义,
                     需要时按 ref.json 偏移另行扩展 */
    volatile uint32_t BCR1, BTR1, BCR2, BTR2, BCR3, BTR3, BCR4, BTR4;
} FSMC_TypeDef;

/* ── 外设实例指针 (基地址逐项 = ref.json peripherals.<P>.base) ── */
#define RCC     ((RCC_TypeDef *)     0x40021000UL)  /* ref.json peripherals.RCC */
#define GPIOA   ((GPIO_TypeDef *)    0x40010800UL)  /* ref.json peripherals.GPIOA */
#define GPIOB   ((GPIO_TypeDef *)    0x40010C00UL)  /* ref.json peripherals.GPIOB */
#define GPIOC   ((GPIO_TypeDef *)    0x40011000UL)  /* ref.json peripherals.GPIOC */
#define GPIOD   ((GPIO_TypeDef *)    0x40011400UL)  /* ref.json peripherals.GPIOD */
#define GPIOE   ((GPIO_TypeDef *)    0x40011800UL)  /* ref.json peripherals.GPIOE */
#define GPIOF   ((GPIO_TypeDef *)    0x40011C00UL)  /* ref.json peripherals.GPIOF */
#define GPIOG   ((GPIO_TypeDef *)    0x40012000UL)  /* ref.json peripherals.GPIOG */
#define USART1  ((USART_TypeDef *)   0x40013800UL)  /* ref.json peripherals.USART1 */
#define USART2  ((USART_TypeDef *)   0x40004400UL)  /* ref.json peripherals.USART2 */
#define USART3  ((USART_TypeDef *)   0x40004800UL)  /* ref.json peripherals.USART3 */
#define TIM1    ((TIM_TypeDef *)     0x40012C00UL)  /* ref.json peripherals.TIM1 */
#define TIM2    ((TIM_TypeDef *)     0x40000000UL)  /* ref.json peripherals.TIM2 */
#define TIM3    ((TIM_TypeDef *)     0x40000400UL)  /* ref.json peripherals.TIM3 */
#define TIM4    ((TIM_TypeDef *)     0x40000800UL)  /* ref.json peripherals.TIM4 */
#define TIM5    ((TIM_TypeDef *)     0x40000C00UL)  /* ref.json peripherals.TIM5 */
#define TIM6    ((TIM_TypeDef *)     0x40001000UL)  /* ref.json peripherals.TIM6 */
#define TIM7    ((TIM_TypeDef *)     0x40001400UL)  /* ref.json peripherals.TIM7 */
#define TIM8    ((TIM_TypeDef *)     0x40013400UL)  /* ref.json peripherals.TIM8 */
#define TIM9    ((TIM_TypeDef *)     0x40014C00UL)  /* ref.json peripherals.TIM9 */
#define TIM10   ((TIM_TypeDef *)     0x40015000UL)  /* ref.json peripherals.TIM10 */
#define TIM11   ((TIM_TypeDef *)     0x40015400UL)  /* ref.json peripherals.TIM11 */
#define TIM12   ((TIM_TypeDef *)     0x40001800UL)  /* ref.json peripherals.TIM12 */
#define TIM13   ((TIM_TypeDef *)     0x40001C00UL)  /* ref.json peripherals.TIM13 */
#define TIM14   ((TIM_TypeDef *)     0x40002000UL)  /* ref.json peripherals.TIM14 */
#define ADC1    ((ADC_TypeDef *)     0x40012400UL)  /* ref.json peripherals.ADC1 */
#define ADC2    ((ADC_TypeDef *)     0x40012800UL)  /* ref.json peripherals.ADC2 */
#define ADC3    ((ADC_TypeDef *)     0x40013C00UL)  /* ref.json peripherals.ADC3 */
#define I2C1    ((I2C_TypeDef *)     0x40005400UL)  /* ref.json peripherals.I2C1 */
#define I2C2    ((I2C_TypeDef *)     0x40005800UL)  /* ref.json peripherals.I2C2 */
#define SPI1    ((SPI_TypeDef *)     0x40013000UL)  /* ref.json peripherals.SPI1 */
#define SPI2    ((SPI_TypeDef *)     0x40003800UL)  /* ref.json peripherals.SPI2 */
#define SPI3    ((SPI_TypeDef *)     0x40003C00UL)  /* ref.json 无 SPI3 条目 (GAP-G-1);
                                                基址 = RM0008 高密度映射, 见 GAPREPORT */
#define IWDG    ((IWDG_TypeDef *)    0x40003000UL)  /* ref.json peripherals.IWDG */
#define WWDG    ((WWDG_TypeDef *)    0x40002C00UL)  /* ref.json peripherals.WWDG */
#define CRC     ((CRC_TypeDef *)     0x40023000UL)  /* ref.json peripherals.CRC */
#define CAN     ((CAN_TypeDef *)     0x40006400UL)  /* ref.json peripherals.CAN */
#define DAC     ((DAC_TypeDef *)     0x40007400UL)  /* ref.json peripherals.DAC */
#define RTC     ((RTC_TypeDef *)     0x40002800UL)  /* ref.json peripherals.RTC */
#define AFIO    ((AFIO_TypeDef *)    0x40010000UL)  /* ref.json peripherals.AFIO */
#define PWR     ((PWR_TypeDef *)     0x40007000UL)  /* ref.json peripherals.PWR */
#define BKP     ((BKP_TypeDef *)     0x40006C00UL)  /* ref.json peripherals.BKP (见结构体注) */
#define EXTI    ((EXTI_TypeDef *)    0x40010400UL)  /* ref.json peripherals.EXTI */
#define DMA1    ((DMA_TypeDef *)     0x40020000UL)  /* ref.json peripherals.DMA1 */
#define DMA2    ((DMA_TypeDef *)     0x40020400UL)  /* ref.json peripherals.DMA2 */
#define SDIO    ((SDIO_TypeDef *)    0x40018000UL)  /* ref.json peripherals.SDIO */
#define FSMC    ((FSMC_TypeDef *)    0xA0000000UL)  /* ref.json peripherals.FSMC */
#define FLASH   ((FLASH_TypeDef *)   0x40022000UL)  /* ref.json peripherals.FLASH */
#define SysTick ((SysTick_Type *)    0xE000E010UL)  /* Cortex-M3 核心 */
#define NVIC    ((NVIC_Type *)       0xE000E100UL)  /* ref.json peripherals.NVIC */

/* ── 时钟使能位 (位名/位号逐项 = ref.json RCC.APB2ENR / APB1ENR / AHBENR bits) ── */
/* APB2ENR: 0=AFIOEN 2=IOPA 3=IOPB 4=IOPC 5=IOPD 6=IOPE 7=IOPF 8=IOPG
             9=ADC1 10=ADC2 11=TIM1 12=SPI1 13=TIM8 14=USART1 15=ADC3
             19=TIM9 20=TIM10 21=TIM11 */
#define RCC_APB2ENR_AFIOEN    (1UL << 0)
#define RCC_APB2ENR_IOPAEN    (1UL << 2)
#define RCC_APB2ENR_IOPBEN    (1UL << 3)
#define RCC_APB2ENR_IOPCEN    (1UL << 4)
#define RCC_APB2ENR_IOPDEN    (1UL << 5)
#define RCC_APB2ENR_IOPEEN    (1UL << 6)
#define RCC_APB2ENR_IOPFEN    (1UL << 7)
#define RCC_APB2ENR_IOPGEN    (1UL << 8)
#define RCC_APB2ENR_ADC1EN    (1UL << 9)
#define RCC_APB2ENR_ADC2EN    (1UL << 10)
#define RCC_APB2ENR_TIM1EN    (1UL << 11)
#define RCC_APB2ENR_SPI1EN    (1UL << 12)
#define RCC_APB2ENR_TIM8EN    (1UL << 13)
#define RCC_APB2ENR_USART1EN  (1UL << 14)
#define RCC_APB2ENR_ADC3EN    (1UL << 15)
#define RCC_APB2ENR_TIM9EN    (1UL << 19)
#define RCC_APB2ENR_TIM10EN   (1UL << 20)
#define RCC_APB2ENR_TIM11EN   (1UL << 21)
/* APB1ENR: 0=TIM2 1=TIM3 2=TIM4 3=TIM5 4=TIM6 5=TIM7 6=TIM12 7=TIM13
             8=TIM14 11=WWDG 14=SPI2 15=SPI3 17=USART2 18=USART3
             19=UART4 20=UART5 21=I2C1 22=I2C2 23=USB 25=CAN 27=BKP
             28=PWR 29=DAC */
#define RCC_APB1ENR_TIM2EN    (1UL << 0)
#define RCC_APB1ENR_TIM3EN    (1UL << 1)
#define RCC_APB1ENR_TIM4EN    (1UL << 2)
#define RCC_APB1ENR_TIM5EN    (1UL << 3)
#define RCC_APB1ENR_TIM6EN    (1UL << 4)
#define RCC_APB1ENR_TIM7EN    (1UL << 5)
#define RCC_APB1ENR_TIM12EN   (1UL << 6)
#define RCC_APB1ENR_TIM13EN   (1UL << 7)
#define RCC_APB1ENR_TIM14EN   (1UL << 8)
#define RCC_APB1ENR_WWDGEN    (1UL << 11)
#define RCC_APB1ENR_SPI2EN    (1UL << 14)
#define RCC_APB1ENR_SPI3EN    (1UL << 15)
#define RCC_APB1ENR_USART2EN  (1UL << 17)
#define RCC_APB1ENR_USART3EN  (1UL << 18)
#define RCC_APB1ENR_UART4EN   (1UL << 19)
#define RCC_APB1ENR_UART5EN   (1UL << 20)
#define RCC_APB1ENR_I2C1EN    (1UL << 21)
#define RCC_APB1ENR_I2C2EN    (1UL << 22)
#define RCC_APB1ENR_USBEN     (1UL << 23)
#define RCC_APB1ENR_CANEN     (1UL << 25)
#define RCC_APB1ENR_BKPEN     (1UL << 27)
#define RCC_APB1ENR_PWREN     (1UL << 28)
#define RCC_APB1ENR_DACEN     (1UL << 29)
/* AHBENR: 0=DMA1 1=DMA2 2=SRAM 4=FLITF 6=CRC 8=FSMC 10=SDIO */
#define RCC_AHBENR_DMA1EN     (1UL << 0)
#define RCC_AHBENR_DMA2EN     (1UL << 1)
#define RCC_AHBENR_CRCEN      (1UL << 6)
#define RCC_AHBENR_FSMCEN     (1UL << 8)
#define RCC_AHBENR_SDIOEN     (1UL << 10)
/* BDCR: 0=LSEON 1=LSERDY 2=LSEBYP 8:9=RTCSEL 15=RTCEN 16=BDRST
 *       (ref.json RCC.BDCR bits) — RTC 选择域 10b=LSE (RM 语义, GAP-D-4) */
#define RCC_BDCR_LSEON        (1UL << 0)
#define RCC_BDCR_LSERDY       (1UL << 1)
#define RCC_BDCR_RTCSEL_LSE   (2UL << 8)
#define RCC_BDCR_RTCEN        (1UL << 15)
/* PWR.CR: 8=DBP (ref.json peripherals.PWR.registers.CR bits) */
#define PWR_CR_DBP            (1UL << 8)

/* ── SysTick CTRL 位 (Cortex-M3 核心架构, 与 test_gen_syntax_smoke 契约同源) ── */
#define SysTick_CTRL_ENABLE    (1UL << 0)
#define SysTick_CTRL_TICKINT   (1UL << 1)
#define SysTick_CTRL_CLKSOURCE (1UL << 2)

/* ── USART CR1 位 (ref.json peripherals.USART1.registers.CR1 bits) ── */
#define USART_CR1_TE (1UL << 3)
#define USART_CR1_RE (1UL << 2)
#define USART_CR1_UE (1UL << 13)

/* ── host mock 重定向 (按样例选用; F103_MOCK_<外设> 置位后该实例落 host 内存) ── */
#ifdef F103_MOCK_REGS
#ifdef F103_MOCK_RCC
static RCC_TypeDef f103_mock_RCC __attribute__((unused));
#undef RCC
#define RCC (&f103_mock_RCC)
#endif
#ifdef F103_MOCK_GPIOA
static GPIO_TypeDef f103_mock_GPIOA __attribute__((unused));
#undef GPIOA
#define GPIOA (&f103_mock_GPIOA)
#endif
#ifdef F103_MOCK_GPIOB
static GPIO_TypeDef f103_mock_GPIOB __attribute__((unused));
#undef GPIOB
#define GPIOB (&f103_mock_GPIOB)
#endif
#ifdef F103_MOCK_GPIOC
static GPIO_TypeDef f103_mock_GPIOC __attribute__((unused));
#undef GPIOC
#define GPIOC (&f103_mock_GPIOC)
#endif
#ifdef F103_MOCK_IWDG
static IWDG_TypeDef f103_mock_IWDG __attribute__((unused));
#undef IWDG
#define IWDG (&f103_mock_IWDG)
#endif
#ifdef F103_MOCK_WWDG
static WWDG_TypeDef f103_mock_WWDG __attribute__((unused));
#undef WWDG
#define WWDG (&f103_mock_WWDG)
#endif
#ifdef F103_MOCK_CRC
static CRC_TypeDef f103_mock_CRC __attribute__((unused));
#undef CRC
#define CRC (&f103_mock_CRC)
#endif
#ifdef F103_MOCK_DAC
static DAC_TypeDef f103_mock_DAC __attribute__((unused));
#undef DAC
#define DAC (&f103_mock_DAC)
#endif
#ifdef F103_MOCK_CAN
static CAN_TypeDef f103_mock_CAN __attribute__((unused));
#undef CAN
#define CAN (&f103_mock_CAN)
#endif
#ifdef F103_MOCK_TIM2
static TIM_TypeDef f103_mock_TIM2 __attribute__((unused));
#undef TIM2
#define TIM2 (&f103_mock_TIM2)
#endif
#ifdef F103_MOCK_TIM5
static TIM_TypeDef f103_mock_TIM5 __attribute__((unused));
#undef TIM5
#define TIM5 (&f103_mock_TIM5)
#endif
#ifdef F103_MOCK_TIM6
static TIM_TypeDef f103_mock_TIM6 __attribute__((unused));
#undef TIM6
#define TIM6 (&f103_mock_TIM6)
#endif
#ifdef F103_MOCK_TIM7
static TIM_TypeDef f103_mock_TIM7 __attribute__((unused));
#undef TIM7
#define TIM7 (&f103_mock_TIM7)
#endif
#ifdef F103_MOCK_USART1
static USART_TypeDef f103_mock_USART1 __attribute__((unused));
#undef USART1
#define USART1 (&f103_mock_USART1)
#endif
#ifdef F103_MOCK_PWR
static PWR_TypeDef f103_mock_PWR __attribute__((unused));
#undef PWR
#define PWR (&f103_mock_PWR)
#endif
#ifdef F103_MOCK_RTC
static RTC_TypeDef f103_mock_RTC __attribute__((unused));
#undef RTC
#define RTC (&f103_mock_RTC)
#endif
#ifdef F103_MOCK_DMA1
static DMA_TypeDef f103_mock_DMA1 __attribute__((unused));
#undef DMA1
#define DMA1 (&f103_mock_DMA1)
#endif
#ifdef F103_MOCK_TIM1
static TIM_TypeDef f103_mock_TIM1 __attribute__((unused));
#undef TIM1
#define TIM1 (&f103_mock_TIM1)
#endif
#ifdef F103_MOCK_TIM9
static TIM_TypeDef f103_mock_TIM9 __attribute__((unused));
#undef TIM9
#define TIM9 (&f103_mock_TIM9)
#endif
#ifdef F103_MOCK_TIM10
static TIM_TypeDef f103_mock_TIM10 __attribute__((unused));
#undef TIM10
#define TIM10 (&f103_mock_TIM10)
#endif
#ifdef F103_MOCK_NVIC
static NVIC_Type f103_mock_NVIC __attribute__((unused));
#undef NVIC
#define NVIC (&f103_mock_NVIC)
#endif
#ifdef F103_MOCK_AFIO
static AFIO_TypeDef f103_mock_AFIO __attribute__((unused));
#undef AFIO
#define AFIO (&f103_mock_AFIO)
#endif
#ifdef F103_MOCK_EXTI
static EXTI_TypeDef f103_mock_EXTI __attribute__((unused));
#undef EXTI
#define EXTI (&f103_mock_EXTI)
#endif
#endif /* F103_MOCK_REGS */

#endif /* F103_REGS_H */
