# 故障注入模板（fault_injection）

给固件模块在 **PC 上**跑故障路径用：不插板、不烧录，几秒钟看到"从机不应答 /
总线被钳死 / 时基冻结 / 数据全 0xFF"时模块到底报不报错。

配套静态闸：`scripts/fault_lint.py`（R1-R3 查"没写错误恢复"，R4 查"没有故障用例"）。

## 四个旋钮

| 旋钮 | 模拟的真机故障 | 典型现象 |
|---|---|---|
| `fault_shim_set_nack_after(n)` | 从机不应答 | HAL 返回 HAL_ERROR，happy path 实现会把它当成功 |
| `fault_shim_set_scl_stuck(1)` | SCL 被钳低 / 上拉丢失 | 软 I2C 等高死循环 |
| `fault_shim_set_clock_frozen(1)` | 时基冻结（SysTick 停 / 中断被屏蔽） | 只靠 tick 的超时永远不超时 |
| `fault_shim_set_garbage(1)` | 器件未接 / 总线被拉高 | 读回全 0xFF，被当成有效值 |

## 接进工程

1. 拷 `fault_shim.c/.h` 到工程的 `tests/`（或 `tools/`）。
2. 拷 `test_fault_paths.c`，把 `Demo_ReadReg16` 换成自己模块的调用。
3. host 编译（MSYS2 gcc 需先 `export PATH="/c/msys64/mingw64/bin:$PATH"`）：

```bash
gcc -std=c99 -Wall -Wextra -I. tests/test_fault_paths.c tests/fault_shim.c \
    User/MyI2C.c User/mpu6050/mpu6050.c -o build/test_fault_paths
./build/test_fault_paths
```

若模块里直接调真实 HAL 头，把 `fault_shim.h` 里的同名声明与真实 HAL 冲突的地方
用 `-DFAULT_SHIM_NO_HAL_TYPES` 之类隔离，或只在 host 侧做 `#include "fault_shim.h"` 替换。

## 自检：证明这套用例真的会红

模板自带一个"只写 happy path"的编译变体：

```bash
gcc -std=c99 -Wall -Wextra -DDEMO_NO_ERROR_HANDLING -I. \
    test_fault_paths.c demo_sensor.c fault_shim.c -o build/fault_bad
./build/fault_bad     # 期望 RED: 4 failure(s)，exit 1
```

2026-11-17 实测（MSYS2 gcc 16.1.0）：

```
好实现:      GREEN 5/5 pass  (nack / scl_stuck / frozen_clock / garbage / happy)
happy-only:  RED   4 failure(s)   ← 正常路径仍 PASS，说明不是"全红"
```

## 用例写法上的两条硬经验

1. **断言"报没报错"，不要断言"挂没挂"**。挂住的用例不会自己失败，只会让 CI
   超时；所以 SUT 里的等待必须有自旋上限，超时判据不能只有 tick（旋钮 3 就是
   用来钉这条的）。
2. **留一条 happy path 用例**。否则闸写歪了也不知道——全红和全绿一样没有信息量。

## 接进 CI

静态闸单独就能当门禁用（非零退出）：

```yaml
- name: 故障路径静态闸
  run: python embedded-toolkit/scripts/fault_lint.py --project "$PWD" --strict
```

`--strict` 把 R4（"有通信模块但没有故障注入用例"）从告警升级为错误。
**注意**：新接这个闸的工程第一轮一定会红——先看清是"真有洞"还是"闸太粗"，
再决定改代码还是加 `fault-lint:ignore <规则> — <理由>`（理由必填，空的算违规）。
