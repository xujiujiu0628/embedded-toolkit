# 敏感信息扫描报告（SENSITIVE_FINDINGS）

> 扫描日期：2026-09-01 ｜ 扫描人：Claude Code（开源化准备步骤 2）
> 范围：工作树 86 个受跟踪文件 + **全部 git 历史**（75 commits × 4 分支）
> 本报告只登记发现，**不修改任何文件**（按任务约定）。

## 一、扫描模式与结果总览

| # | 模式 | 对象 | 工作树命中 | 历史命中 |
|---|---|---|---|---|
| 1 | `password/passwd [:=] "..."` 赋值 | 全仓 | 0 | 0 |
| 2 | `api_key / apikey / secret / token [:=] "..."` 赋值 | 全仓 | 0 | 0 |
| 3 | 含 `user:pass@` 的数据库/消息 URI（mongodb/mysql/postgresql/redis/amqp/ftp） | 全仓 | 0 | 0 |
| 4 | AWS 密钥 `AKIA[0-9A-Z]{16}` | 全仓 | 0 | 0 |
| 5 | 私钥文件 `*.pem *.key *.p12 *.pfx *.jks` | 文件清单 | 0 | 0 |
| 6 | 常见 token 前缀（`sk-*` `ghp_*` `github_pat_*` `xox*` JWT `eyJ*`） | 全仓 | 0 | 0 |
| 7 | `Bearer <token>` / Authorization 头硬编码 | 全仓 | 0 | 0 |
| 8 | 文档叙述式凭证（`密钥/密码/token：xxx`） | *.md | 0 | — |
| 9 | IP / 主机地址（排除 localhost） | 全仓 | 0 | 0 |
| 10 | 邮箱 / 手机号 | 全仓 | 0 | 0 |
| 11 | 配置文件核查（.json/.yml 共 18 个 + requirements.txt） | 逐个查看 | 无硬编码凭证 ✓ | — |
| 12 | CI workflow 中 `secrets.*` 引用 | .github/workflows | 0（纯离线测试） | 0 |
| 13 | 本机凭证文件被跟踪（machine.json/.env/.mcp.json） | git ls-files | 0（均在 ignore） | — |
| 14 | **个人标识**：Windows 用户名 / `C:\Users\<真实名>` | 全仓 | 0（已中性化） | **⚠ 命中，见 F-1** |
| 15 | **机器路径**：`<工作区根>\...` / `<工作区根>/...` | 全仓 | **47 处，见 F-2** | 同量级 |

**结论：无凭证级泄漏（密码/密钥/token/私钥/连接串全零）。** 但存在两项
**PII / 信息暴露级**发现，且仓库仍为 PRIVATE、历史未扩散，处置成本最低的窗口就是现在。

## 二、发现明细

### F-1（中危）：个人 Windows 用户名（5 位数字，本报告不复述明文）残留在 git 历史中

commit `chore(security): 历史文档个人用户目录中性化` 只清洗了**文件内容**
（HEAD 已替换为 `%USERPROFILE%` / `/c/Users/<用户名>` 占位符），但旧 blob 与
**该清洗 commit 的 message 本身**仍含明文（约 22 处），仓库转 Public 后
任何人 `git log -p` / GitHub commit 搜索即可见。

**处置建议（三选一，按成本升序）：**

1. **接受**：该用户名不含邮箱/手机号语义，单独暴露危害有限，直接公开；
2. **历史重写**：`git filter-repo --replace-text`（`Users\<用户名>` 定向映射，
   含 commit message）后 `push --force`。PRIVATE 期操作，全量分支重写，
   一次性成本；实测历史中该数字 27 处**全部**以 `Users[\/]` 前缀形态出现，
   定向规则零误伤；
3. **历史清零**：开源首发以单个 squash 的 `init` commit 开新历史（CHANGELOG.md
   已承担账本职能，可注明"历史自 v0.3 起可回放"）。治理史是本项目卖点之一，
   此法会丢掉 commit 级证据链——**不推荐，列此仅为完整**。

> 推荐方案 2。注意：重写后本地 `handoff/*` 两分支也需同步（`filter-repo` 默认处理全 ref）。

### F-2（低危）：本机绝对路径 `<工作区根>\...` 47 处（工作树）

非凭证，但暴露个人目录布局与兄弟工程存在性（`stm32f103-adc-oled` 等）。
分布（文件：行号）：

| 文件 | 处数 | 行号 |
|---|---|---|
| `docs/superpowers/plans/2026-08-26-harness-borrow.md` | 14 | 34 1030 1045 1046 1047 1070 1143 1159 1165 1195 1203 1223 1224 1234 |
| `docs/superpowers/plans/2026-08-26-fresh-checker-skill.md` | 13 | 17 133 155 164 165 166 173 174 183 226 233 235 236 |
| `HANDOFF-AGENT.md` | 8 | 24 25 26 28 149 246 314 316 |
| `docs/handoff/2026-08-30-findings.md` | 3 | 24 28 201 |
| `docs/handoff/2026-08-30-advice.md` | 2 | 3 35 |
| `docs/handoff/2026-08-31-r2-reconcile-notes.md` | 2 | 46 67 |
| `docs/handoff/2026-08-30-kickoff-zcode.md` | 1 | 3 |
| `AGENTS.md` | 1 | 8 |
| `docs/superpowers/specs/2026-08-26-harness-borrow-design.md` | 1 | 10 |
| `skills/fresh-checker/SKILL.md` | 1 | 105 |
| `tests/test_expectations_lint.py` | 1 | **18（见 F-3）** |

**处置建议**：历史重写（F-1 方案 2）时顺带 `<工作区根>\` → `<工作区根>\` 映射，
一次解决 F-1+F-2 的历史维度；若接受历史，则只需对**HEAD 的 .md 文档**做占位符
替换（文档性引用，不影响运行）。

### F-3（低危）：测试代码硬编码兄弟工程路径

`tests/test_expectations_lint.py:18` 的 `ADC_OLED = r"<工作区根>\stm32f103-adc-oled"`
被用作"真实档案冒烟"数据源。路径缺失时测试会跳过（CI 181/181 绿即证），
但对陌生人克隆而言该测试**永远静默跳过**，冒烟价值只在维护者本机存在。

**处置建议**（属代码改动，本次未动）：改用 `tempfile` 造最小工程目录，
或在 PR 里讨论后维持现状并在文件头注释其"仅本机全效"。

### 提示：本地未推送分支

`handoff/zcode-20260830`、`handoff/zcode-r2-20260830`、`handoff/r2-reconcile-20260831`
三个分支仍在本地。将来若推送，其内容含与 F-1/F-2 同类信息，且属过程性治理记录——
建议先决定是否需要公开，或推之前并入 F-1 的历史重写。

## 三、通过项（已核查、干净）

- `config/keil.json` / `openocd.json` / `serial.json`：仅默认端口与空串占位，无机器路径、无凭证；
- `machine.example.json`：全部为 `<尖括号占位符>` ✓；
- `data/*.json` 知识库、`.github/*` 模板与 CI：无命中；
- `machine.json`、`.mcp.json`、`.superpowers/`、`__pycache__/` 均未被跟踪且已在 `.gitignore`。

---
*本报告与 `OPENSOURCE_READY.md` 配套；F-1~F-3 处置决定权在维护者。*
