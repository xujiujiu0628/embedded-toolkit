/* demo_sensor.h — 样例模块的接口（F-251 模板） */
#ifndef DEMO_SENSOR_H
#define DEMO_SENSOR_H

#include <stdint.h>

#define DEMO_OK          0
#define DEMO_ERR_NACK    1
#define DEMO_ERR_TIMEOUT 2
#define DEMO_ERR_RANGE   3

/* 读一个 16 位寄存器。返回 0 成功, 非 0 见上面的 DEMO_ERR_*。 */
int Demo_ReadReg16(uint8_t reg, int16_t *out);

#endif /* DEMO_SENSOR_H */
