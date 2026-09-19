/* f103-crc — T2 手写寄存器级样例 (编译级 + host mock)。
 * 用途: CRC 单元复位后逐字喂数, 读 CRC 结果。
 * ref.json anchor: peripherals.CRC (DR@0x00 0:31, IDR@0x04 0:7, CR@0x08
 *                  bit0=RESET); RCC.AHBENR bit6=CRCEN。
 * GAP-D-4: 多项式 0x4C11DB7 与字序为 ST 固定语义, ref.json 未登记
 *          (一期仅断言写序列; 二期 WB-20260920-02 按该固定语义独立
 *          演算已知答案向量, 推导见 host 测试注释)。
 * 硬件验收: 未做（编译级样例）
 */
#include "f103_regs.h"

/* 配置/喂数序列 — target 写真寄存器 / host(F103_MOCK_REGS) 写重定向结构, 两态共用 */
static void crc_init(void)
{
    RCC->AHBENR |= RCC_AHBENR_CRCEN;     /* ref.json RCC.AHBENR bit6=CRCEN */
    __DSB();
    CRC->CR = (1UL << 0);                /* RESET 位 (ref.json CRC.CR bit0) */
}

static uint32_t crc_feed(const uint32_t *words, uint32_t n)
{
    if (words == 0) {                    /* 二期防御: 空指针不触碰 DR */
        return CRC->DR;
    }
    for (uint32_t i = 0; i < n; i++) {
        CRC->DR = words[i];              /* ref.json CRC.DR bits 0:31 */
    }
    return CRC->DR;
}

#ifndef F103_SAMPLE_HOST_TEST
int main(void)
{
    static const uint32_t payload[4] = {0x12345678u, 0x9ABCDEF0u,
                                        0x0F1E2D3Cu, 0x4B5A6978u};
    crc_init();
    for (;;) {
        /* 最小使用场景: 复位 → 喂 4 字 → 读结果 */
        CRC->CR = (1UL << 0);
        (void)crc_feed(payload, 4);
        __WFI();
    }
}
#else
#include <stdio.h>
static int failures;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s\n", #cond); \
                                        failures++; } } while (0)

/* ST CRC 硬件语义模型 (host-only): GAP-D-4 — ref.json 无多项式/初值,
 * 按本样例头注声明的固定语义独立实现: poly=0x04C11DB7, 初值 0xFFFFFFFF,
 * MSB-first, 无反射, 无输出异或。下方已知答案常数由独立演算脚本按
 * 同一算法逐位推得 (非运行本程序所得); 简报示例数字 0xCBF43926 属
 * 反射族 zlib 算法, 与 ST 硬件语义不同族, 不采。 */
static uint32_t st_crc32_model(const uint32_t *w, uint32_t n)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < n; i++) {
        crc ^= w[i];
        for (int b = 0; b < 32; b++) {
            crc = (crc & 0x80000000u) ? ((crc << 1) ^ 0x04C11DB7u)
                                      : (crc << 1);
        }
    }
    return crc;
}

int main(void)
{
    static const uint32_t payload[4] = {0x12345678u, 0x9ABCDEF0u,
                                        0x0F1E2D3Cu, 0x4B5A6978u};
    uint32_t before;
    /* 组1 已知答案-可手证向量: 初值异或 0xFFFFFFFF 后余数=0, 32 轮
     * 移位保持 0 → 喂单字 0xFFFFFFFF 结果恒 0 (无需逐轮演算);
     * n=0 → 返回纯初值 0xFFFFFFFF (模型复位态语义) */
    CHECK(st_crc32_model(payload, 0) == 0xFFFFFFFFu);
    {
        static const uint32_t one[1] = {0xFFFFFFFFu};
        CHECK(st_crc32_model(one, 1) == 0x00000000u);
    }
    /* 组2 已知答案-单字: '1234' 大端组字 0x31323334 → 0xA695C4AA
     * (独立演算脚本按上述算法逐位推得) */
    {
        static const uint32_t word[1] = {0x31323334u};
        CHECK(st_crc32_model(word, 1) == 0xA695C4AAu);
    }
    /* 组3 已知答案-场景向量: 真机走完"复位+喂 payload"后 DR 应读得
     * 0x376454AF (独立演算) */
    CHECK(st_crc32_model(payload, 4) == 0x376454AFu);
    /* 组4 寄存器写序列 + 复位/宽度语义 (一期既有断言保持) */
    crc_init();
    CHECK(f103_mock_RCC.AHBENR & RCC_AHBENR_CRCEN);
    CHECK(f103_mock_CRC.CR == 1u);            /* 复位脉冲已发 */
    (void)crc_feed(payload, 4);
    CHECK(f103_mock_CRC.DR == payload[3]);    /* mock 无运算, DR=最后一字 */
    CRC->IDR = 0xFFu;                         /* ref.json CRC.IDR bits 0:7 满档 */
    CHECK(f103_mock_CRC.IDR == 0xFFu);
    CRC->CR = (1UL << 0);                     /* 再复位 */
    CHECK(f103_mock_CRC.CR == 1u);
    /* 组5 边界+非法输入防御 (n=0 / 空指针均不触碰 DR) */
    before = f103_mock_CRC.DR;
    CHECK(crc_feed(payload, 0) == before);
    CHECK(f103_mock_CRC.DR == before);
    CHECK(crc_feed(0, 4) == before);          /* 二期新增空指针防御 */
    CHECK(f103_mock_CRC.DR == before);
    if (failures) {
        printf("MOCK FAILED (%d)\n", failures);
        return 1;
    }
    printf("MOCK PASS\n");
    return 0;
}
#endif
