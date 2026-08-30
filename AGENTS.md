# AGENTS.md

本仓是嵌入式 AI 工作台的全局工具库（verify 闭环 / 发布门禁 / unittest 回归套件，
版本见 `VERSION` 与 `CHANGELOG.md`）。

- **被请来代管检查本工作台的智能体**：唯一入口是 [`HANDOFF-AGENT.md`](HANDOFF-AGENT.md)，
  从 §1 顺序读完 §1-§5 再开工；权限与禁线以该文为准。
- 日常开发（主控会话）约定见 `README.md` 与 `<工作区根>\CLAUDE.md`。
- 仓根 `machine.json` = 本机工具链路径唯一来源（只读）；测试：`python -m unittest discover -s tests`。
