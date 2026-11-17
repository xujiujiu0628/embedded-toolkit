/*
 * fault_shim.c — 故障注入垫片的实现（F-251 模板）
 */
#include "fault_shim.h"

static uint32_t s_tick;
static uint32_t s_tick_step = 1;
static int s_clock_frozen;
static int s_nack_after = -1;   /* -1 = 永不 NACK */
static int s_scl_stuck;
static int s_garbage;
static int s_transfers;
static int s_scl_level = 1;     /* 没有 stuck 时 SCL 恒高 */

void fault_shim_reset(void)
{
    s_tick = 1000;              /* 非零起点: 抓 "t0 未初始化" 这类错 */
    s_tick_step = 1;
    s_clock_frozen = 0;
    s_nack_after = -1;
    s_scl_stuck = 0;
    s_garbage = 0;
    s_transfers = 0;
    s_scl_level = 1;
}

uint32_t HAL_GetTick(void)
{
    if (!s_clock_frozen) {
        s_tick += s_tick_step;
    }
    return s_tick;
}

void HAL_Delay(uint32_t ms)
{
    if (!s_clock_frozen) {
        s_tick += ms;
    }
}

void fault_shim_advance(uint32_t ms) { s_tick += ms; }
void fault_shim_set_tick_step(uint32_t ms) { s_tick_step = ms; }
void fault_shim_set_clock_frozen(int on) { s_clock_frozen = on ? 1 : 0; }
void fault_shim_set_nack_after(int n) { s_nack_after = n; }
void fault_shim_set_scl_stuck(int on) { s_scl_stuck = on ? 1 : 0; }
void fault_shim_set_garbage(int on) { s_garbage = on ? 1 : 0; }
int fault_shim_transfer_count(void) { return s_transfers; }

HAL_StatusTypeDef HAL_I2C_Master_Transmit(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                          uint8_t *data, uint16_t size,
                                          uint32_t timeout)
{
    (void)hi2c; (void)dev; (void)data; (void)size; (void)timeout;
    s_transfers++;
    if (s_nack_after >= 0 && s_transfers > s_nack_after) {
        return HAL_ERROR;       /* 从机不应答 */
    }
    return HAL_OK;
}

HAL_StatusTypeDef HAL_I2C_Master_Receive(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                         uint8_t *data, uint16_t size,
                                         uint32_t timeout)
{
    (void)hi2c; (void)dev; (void)timeout;
    s_transfers++;
    if (s_nack_after >= 0 && s_transfers > s_nack_after) {
        return HAL_ERROR;
    }
    for (uint16_t i = 0; i < size; i++) {
        data[i] = s_garbage ? 0xFF : (uint8_t)(0x12 + i);
    }
    return HAL_OK;
}

HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                        uint32_t trials, uint32_t timeout)
{
    (void)hi2c; (void)dev; (void)trials; (void)timeout;
    return (s_nack_after == 0) ? HAL_ERROR : HAL_OK;
}

void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, int state)
{
    (void)port; (void)pin;
    if (s_scl_stuck && state) {
        return;                 /* 想拉高, 但线被钳住 */
    }
    s_scl_level = state ? 1 : 0;
}

int HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin)
{
    (void)port; (void)pin;
    return s_scl_stuck ? 0 : s_scl_level;   /* 钳低时读回恒 0 */
}
