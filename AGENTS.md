# AGENTS.md

本仓是嵌入式 AI 工作台的全局工具库（verify 闭环 / 发布门禁 / unittest 回归套件，
版本见 `VERSION` 与 `CHANGELOG.md`）。

- **被请来代管检查本工作台的智能体**：唯一入口是 [`HANDOFF-AGENT.md`](HANDOFF-AGENT.md)，
  从 §1 顺序读完 §1-§5 再开工；权限与禁线以该文为准。
- 日常开发（主控会话）约定见 `README.md` 与 `<工作区根>\CLAUDE.md`。
- 仓根 `machine.json` = 本机工具链路径唯一来源（本机文件不入库，模板
  `machine.example.json`，缺失时回退占位并警告）；测试：`python -m unittest discover -s tests`。
## 工程纪律速查（成文 F-035；权威文本在 `.github/CONTRIBUTING.md` 对应小节，两文分歧以 CONTRIBUTING 为准）

- import 只许沿 Layer 0→2 单向：`wb_common` → `runtime_common` → 族 runtime → 工具脚本；`scripts/legacy/**` 冻结，禁 import `runtime_common`。
- "脚本自含"已退役：复用一律 import 共享层符号，禁复制粘贴；真分叉留份 docstring 写 `独立契约：<差异一句话>——见 F-029 裁决，勿"统一"`。
- 行为保持型重构三步：先钉（特征测试钉死 wire 形态）→ 后拆（每 commit 只搬一族符号）→ 留份裁决；重构与行为变更不同 commit。
- 没见过红的测试不算测试；钉类测试须过变异验证一次。
- 契约（`.workbench/` schema / 工具 JSON 输出结构）变更：同 commit 契约钉 + CHANGELOG 契约变更段 + `toolkit_min_version` 评估。
- 文档：状态类事实只进 CHANGELOG；"真实可回放"实录段不可变（重采整段替换）；例数以实跑为准不写死。
- 生产脚本禁 `import verify`（Layer 2 编排主体；import 期副作用已于 F-054 清除）。
- 推送纪律（F-062）：Agent 不直接 push 远端；本地 commit → 维护者审核 → 维护者推送或明确授权。

## Agent skills

### Issue tracker

GitHub Issues on `xujiujiu0628/embedded-toolkit`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels (`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
