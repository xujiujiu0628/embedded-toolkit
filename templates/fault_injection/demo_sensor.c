/*
 * demo_sensor.c — 一个"被测模块"的样例（F-251 模板）
 *
 * 真实工程里把本文件换成自己的模块（MyI2C / mpu6050 / dht11 ...），垫片不用改。
 * 这里刻意保留三条容易漏的错误路径:
 *   1. 传输返回值不检查 → 从机不应答被当成功
 *   2. 软 I2C 等高只写 while → 线被钳低就永远等
 *   3. 超时只依赖时基 → 时基冻结时再大的 timeout 也不超时
 *
 * 编译时定义 DEMO_NO_ERROR_HANDLING 会得到一个"只写 happy path"的版本,
 * 用来证明 test_fault_paths.c 真的会红（见 README 的自检配方）。
 */
#include "demo_sensor.h"
#include "fault_shim.h"

#define SENSOR_ADDR8   (0x68u << 1)

/* 两道判据: 时基超时 + 自旋上限。只靠时基的实现, 时钟冻结时永远等不出来。 */
#define SCL_TIMEOUT_TICKS  10u
#define SCL_MAX_SPINS      20000u

static I2C_HandleTypeDef s_i2c;
static GPIO_TypeDef      s_port;

static int wait_scl_high(void)
{
    uint32_t t0 = HAL_GetTick();
    uint32_t spins = 0;
#ifdef DEMO_NO_ERROR_HANDLING
    (void)t0;                                     /* 时基取了但没用: 账就是这样漏的 */
    while (HAL_GPIO_ReadPin(&s_port, 1) == 0) {
        if (++spins > SCL_MAX_SPINS) { break; }   /* 只保命, 不看结果 */
    }
    return DEMO_OK;
#else
    while (HAL_GPIO_ReadPin(&s_port, 1) == 0) {
        if (++spins > SCL_MAX_SPINS) return DEMO_ERR_TIMEOUT;
        if ((HAL_GetTick() - t0) > SCL_TIMEOUT_TICKS) return DEMO_ERR_TIMEOUT;
    }
    return DEMO_OK;
#endif
}

int Demo_ReadReg16(uint8_t reg, int16_t *out)
{
    uint8_t cmd = reg;
    uint8_t buf[2] = { 0, 0 };

#ifdef DEMO_NO_ERROR_HANDLING
    (void)wait_scl_high();
    HAL_I2C_Master_Transmit(&s_i2c, SENSOR_ADDR8, &cmd, 1, 10);
    (void)wait_scl_high();
    HAL_I2C_Master_Receive(&s_i2c, SENSOR_ADDR8, buf, 2, 10);
    *out = (int16_t)((buf[0] << 8) | buf[1]);
    return DEMO_OK;
#else
    if (wait_scl_high() != DEMO_OK) return DEMO_ERR_TIMEOUT;
    if (HAL_I2C_Master_Transmit(&s_i2c, SENSOR_ADDR8, &cmd, 1, 10) != HAL_OK) {
        return DEMO_ERR_NACK;
    }
    if (wait_scl_high() != DEMO_OK) return DEMO_ERR_TIMEOUT;
    if (HAL_I2C_Master_Receive(&s_i2c, SENSOR_ADDR8, buf, 2, 10) != HAL_OK) {
        return DEMO_ERR_NACK;
    }
    /* 0xFFFF 是总线被拉高 / 器件未接的典型读数, 当无效值处理 */
    if (buf[0] == 0xFF && buf[1] == 0xFF) return DEMO_ERR_RANGE;
    *out = (int16_t)((buf[0] << 8) | buf[1]);
    return DEMO_OK;
#endif
}
