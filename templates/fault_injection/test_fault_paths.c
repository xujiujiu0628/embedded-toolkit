/*
 * test_fault_paths.c — 故障路径用例模板（F-251）
 *
 * 五个用例: 从机不应答 / SCL 钳低 / 时基冻结 / 数据全 0xFF / 正常路径。
 * 最后一条是防呆: 闸不能把好实现一起判红。
 *
 * 关键点: 用例断言的是"模块有没有把错误报出来", 而不是"有没有挂"。
 * 挂住的用例不会自己失败, 只会让 CI 卡住超时——所以 SUT 里必须有自旋上限。
 */
#include <stdio.h>

#include "demo_sensor.h"
#include "fault_shim.h"

static int failures;

static void check(const char *name, int cond, const char *detail)
{
    if (cond) {
        printf("PASS %s\n", name);
    } else {
        printf("FAIL %s — %s\n", name, detail);
        failures++;
    }
}

int main(void)
{
    int16_t v = 0;

    /* 1. 从机不应答: 必须报错, 不能把 0 当有效值 */
    fault_shim_reset();
    fault_shim_set_nack_after(0);
    check("nack_returns_error", Demo_ReadReg16(0x3B, &v) == DEMO_ERR_NACK,
          "NACK 被当成成功");

    /* 2. SCL 被钳低: 等高必须超时退出 */
    fault_shim_reset();
    fault_shim_set_scl_stuck(1);
    check("scl_stuck_times_out", Demo_ReadReg16(0x3B, &v) == DEMO_ERR_TIMEOUT,
          "等高没有超时退出");

    /* 3. 时基冻结 + SCL 钳低: 只靠 tick 的实现会等死, 必须有第二道判据 */
    fault_shim_reset();
    fault_shim_set_scl_stuck(1);
    fault_shim_set_clock_frozen(1);
    check("frozen_clock_does_not_hang", Demo_ReadReg16(0x3B, &v) == DEMO_ERR_TIMEOUT,
          "时基冻结时没有退出");

    /* 4. 数据全 0xFF: 无效读数必须被识别 */
    fault_shim_reset();
    fault_shim_set_garbage(1);
    check("garbage_rejected", Demo_ReadReg16(0x3B, &v) == DEMO_ERR_RANGE,
          "无效读数被当成有效值");

    /* 5. 正常路径: 防呆, 别把好实现判红 */
    fault_shim_reset();
    check("happy_path_ok", Demo_ReadReg16(0x3B, &v) == DEMO_OK && v == 0x1213,
          "正常读数被判错");

    printf("%s: %d failure(s)\n", failures ? "RED" : "GREEN", failures);
    return failures ? 1 : 0;
}
