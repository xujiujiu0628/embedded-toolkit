# embedded-toolkit

嵌入式 AI 工作台全局工具库。固件工程通过 `.workbench/config.json` 被脚本发现（cwd 向上查找）。

- `scripts/` 工具脚本（verify.py 闭环验证入口）
- `data/` 通用知识库（stm32f103-ref.json / keil-error-db.json 跨工程共享）
- `hooks/` 通用铁律检查（工程特定 hook 留在工程 .claude/hooks/）
- `machine.json` 本机工具链绝对路径（唯一合法硬编码处）
