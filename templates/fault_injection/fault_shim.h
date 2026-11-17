/*
 * fault_shim.h — 故障注入垫片（F-251 模板）
 *
 * 用途: 在 PC 上跑固件模块的故障路径。HAL 形状的接口与真实 HAL 同名同签名,
 *       被测模块一行不用改, 只把垫片链接进去。
 *
 * 四个旋钮对应四类真机故障:
 *   从机不应答 (NACK)  /  SCL 被钳低  /  时基冻结  /  数据全 0xFF
 *
 * 用法: 见同目录 README.md 与 test_fault_paths.c
 */
#ifndef FAULT_SHIM_H
#define FAULT_SHIM_H

#include <stdint.h>

typedef enum {
    HAL_OK = 0, HAL_ERROR = 1, HAL_BUSY = 2, HAL_TIMEOUT = 3
} HAL_StatusTypeDef;

typedef struct { int id; } I2C_HandleTypeDef;
typedef struct { int id; } GPIO_TypeDef;

/* ---- 时基 ----
 * 默认每次 HAL_GetTick() 前进 1ms; 也可 fault_shim_advance 手动推。
 * clock_frozen=1 时 tick 恒定 —— 用来暴露"超时只依赖 tick"的实现:
 * 时基不动, 再大的 timeout 也永远不超时。 */
void     fault_shim_reset(void);
uint32_t HAL_GetTick(void);
void     HAL_Delay(uint32_t ms);
void     fault_shim_advance(uint32_t ms);
void     fault_shim_set_tick_step(uint32_t ms);
void     fault_shim_set_clock_frozen(int on);

/* ---- 故障旋钮 ---- */
void fault_shim_set_nack_after(int n);      /* 前 n 次传输正常, 第 n+1 次起 NACK */
void fault_shim_set_scl_stuck(int on);      /* SCL 恒低: 软 I2C 等高会卡住 */
void fault_shim_set_garbage(int on);        /* 读回字节全 0xFF */
int  fault_shim_transfer_count(void);       /* 观测实际发生了多少次传输 */

/* ---- HAL 形状的接口 ---- */
HAL_StatusTypeDef HAL_I2C_Master_Transmit(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                          uint8_t *data, uint16_t size,
                                          uint32_t timeout);
HAL_StatusTypeDef HAL_I2C_Master_Receive(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                         uint8_t *data, uint16_t size,
                                         uint32_t timeout);
HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *hi2c, uint16_t dev,
                                        uint32_t trials, uint32_t timeout);
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, int state);
int  HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin);

#endif /* FAULT_SHIM_H */
