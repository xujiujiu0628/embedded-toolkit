# T2 手写寄存器级样例 — 母本 examples/sim-demo/Makefile (旗标按任务简报收紧)
TARGET  = f103-tim9-14
BUILD_DIR = build

CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE    = arm-none-eabi-size
CFLAGS  = -mcpu=cortex-m3 -mthumb -O2 -Wall -Werror -ffreestanding -nostdlib
INC     = -I../f103-common

$(BUILD_DIR)/$(TARGET).elf: main.c ../f103-common/link.ld ../f103-common/startup.c ../f103-common/f103_regs.h
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) $(INC) -T ../f103-common/link.ld ../f103-common/startup.c main.c -o $@
	$(OBJCOPY) -O ihex $@ $(BUILD_DIR)/$(TARGET).hex
	-$(SIZE) $@

.PHONY: all clean
all: $(BUILD_DIR)/$(TARGET).elf
clean:
	rm -rf $(BUILD_DIR)

# host mock 测试: F103_MOCK_REGS 把寄存器实例重定向到 host 内存,
# F103_SAMPLE_HOST_TEST 只编译纯逻辑/序列断言, 断言全过 exit 0。
# CC_HOST 可在命令行覆盖 (工厂测试注入解析到的 host gcc 绝对路径)。
CC_HOST ?= gcc
MOCK_DEFS = -DF103_MOCK_TIM9 -DF103_MOCK_TIM10 -DF103_MOCK_RCC

test:
	@mkdir -p $(BUILD_DIR)
	$(CC_HOST) -O1 -Wall -Werror -DF103_MOCK_REGS -DF103_SAMPLE_HOST_TEST $(MOCK_DEFS) $(INC) main.c -o $(BUILD_DIR)/host_test.exe
	$(BUILD_DIR)/host_test.exe
	@echo MOCK PASS

.PHONY: all clean test
