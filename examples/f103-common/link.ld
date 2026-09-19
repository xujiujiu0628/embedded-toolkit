/*
 * link.ld — 样例工厂共享链接脚本 (母本: examples/sim-demo/link.ld)
 * 存储器映像按 C8T6: FLASH 64K @ 0x08000000, RAM 20K @ 0x20000000。
 * 栈顶 0x20005000 在 startup.c 向量表 [0] 槽引用。
 */
ENTRY(Reset_Handler)

MEMORY
{
  FLASH(rx)  : ORIGIN = 0x08000000, LENGTH = 64K
  RAM(rwx)   : ORIGIN = 0x20000000, LENGTH = 20K
}

SECTIONS
{
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text       : { *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
  .data       : {
      . = ALIGN(4);
      _sdata = .;
      *(.data*)
      . = ALIGN(4);
      _edata = .;
  } > RAM AT > FLASH
  _sidata = LOADADDR(.data);
  .bss (NOLOAD) : {
      . = ALIGN(4);
      _sbss = .;
      *(.bss*) *(COMMON)
      . = ALIGN(4);
      _ebss = .;
  } > RAM
}
