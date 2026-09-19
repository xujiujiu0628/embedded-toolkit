# 母本: examples/sim-demo/Makefile — 旗标按任务简报收紧 (-O2 -Werror)
TARGET  = f103-timer-int-tim4
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
