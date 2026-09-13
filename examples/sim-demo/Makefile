TARGET = sim-demo
BUILD_DIR = build

CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
CFLAGS  = -mcpu=cortex-m3 -mthumb -O0 -ffreestanding -nostdlib -Wall

$(BUILD_DIR)/$(TARGET).elf: main.c link.ld
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -T link.ld main.c -o $@
	$(OBJCOPY) -O ihex $@ $(BUILD_DIR)/$(TARGET).hex

.PHONY: all clean
all: $(BUILD_DIR)/$(TARGET).elf
clean:
	rm -rf $(BUILD_DIR)
