# f103-common

F103 样例工厂共享件 — 裸偏移寄存器层（`f103_regs.h`）、最小启动桩
（`startup.c`：向量表槽位逐项注明 ref.json 来源 + data/bss 初始化）、
链接脚本（`link.ld`，母本 examples/sim-demo，映像改 C8T6 64K/20K），
供各 `f103-*` 样例经 `-I../f103-common` 相对引用。

- 生成方式: 共享件（手写；寄存器数据逐项锚定 data/stm32f103-ref.json，
  详见 `docs/specs/2026-09-19-sample-factory-status.md` GAPREPORT）
- 硬件验收: 未做（编译级样例）
- 本目录不参与逐样例巡检（`tests/test_sample_factory.py` 显式排除
  `f103-common`）；寄存器层的 host mock 重定向口与 gen_periph 契约
  垫片（error_chain_t）说明见文件头注释。
