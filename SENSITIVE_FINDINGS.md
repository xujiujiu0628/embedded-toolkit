# 敏感信息扫描报告（SENSITIVE_FINDINGS）

> 扫描日期：2026-09-01 ｜ 扫描人：Claude Code（开源化准备步骤 2）
> 范围：工作树 86 个受跟踪文件 + **全部 git 历史**（75 commits × 4 分支）
> 本报告初版只登记发现；F-1/F-2 的处置经维护者另行拍板于同日执行（filter-repo
> 两轮历史重写，结果见各节"处置结果"），代码逻辑未动（守卫判据适配为唯一例外）。

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
| 14 | **个人标识**：Windows 用户名（`Users<分隔符>` 形态） | 全仓 | 0（已中性化） | ~~⚠ 命中~~ → **0**（✅ F-1 重写完成） |
| 15 | **机器路径**：工作区盘符路径（单反斜杠 / JSON 双写 / msys 三形态） | 全仓 | ~~47 处~~ → **0**（✅ 2026-09-01 重写） | ~~同量级~~ → **0** |

**结论：无凭证级泄漏（密码/密钥/token/私钥/连接串全零）。** 两项
**PII / 信息暴露级**发现（F-1/F-2）已于 2026-09-01 经维护者拍板完成历史重写处置，
终验零残留；F-3/F-4 为登记在册的存量事项。

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

**处置结果（2026-09-01，方案 2 已执行）**：filter-repo 两轮重写。**关键坑**：
`--replace-text` 只作用于 blob 与文件名，**不作用于 commit/tag message**——
首轮漏掉清洗 commit 正文中的 1 处明文，二轮以 `--message-callback` /
`--tag-callback`（hex 转义 bytes）补齐。终验（log -p + 全部 %B + tag contents）：
明文零残留；唯一 `\claude` 形态残留为 legacy 代码中 `~\AppData\Local\...`
（`~` 可移植路径，无用户名，不构成 PII）。三个 `handoff/*` 分支已随写，仍未推送。

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

**处置结果（2026-09-01，已执行）**：随历史重写完成——盘符形态（含 JSON 双反斜杠
转义）与 msys 形态统一映射为 `<工作区根>` 占位，HEAD 与全部历史一次洗清。
本表行号引用仍有效（替换均为行内，不增减行数）。

### F-3（低危）：测试代码硬编码兄弟工程路径

`tests/test_expectations_lint.py:18` 的 `ADC_OLED = r"<工作区根>\stm32f103-adc-oled"`
被用作"真实档案冒烟"数据源。路径缺失时测试会跳过（CI 181/181 绿即证），
但对陌生人克隆而言该测试**永远静默跳过**，冒烟价值只在维护者本机存在。

**处置建议**（属代码改动，尚未拍板）：改用 `tempfile` 造最小工程目录，
或在 PR 里讨论后维持现状并在文件头注释其"仅本机全效"。
**联动现状**：历史重写已将字面量洗为占位符——本机真档冒烟现亦恒跳过
（skipped+1），tempfile 化之前该冒烟保护对所有人（含维护者）失效。

### F-4（存量环境缺陷，对照实验证明与重写无关）

`tests/test_expectations_lint.py::test_cli_exit_codes_and_json` 在 Windows
非 UTF-8 控制台下失败：`expectations_lint.py` 输出中文错误时子进程用 GBK 字节，
测试父进程按 `encoding="utf-8"` 解码崩溃（0xce @132）。
**对照证据**：从重写前 bundle（f12b5b3）克隆复现完全相同失败 → 存量缺陷，
在本终端环境下才暴露；CI（ubuntu）恒绿，维护者终端环境未受影响则未见。
建议修（后补轮）：脚本 stdout 强制 `reconfigure(encoding="utf-8")`，
或测试对 subprocess 附 `PYTHONIOENCODING=utf-8` 环境。

### F-5（时间线事实，处置执行后补记 2026-09-01）

GitHub Events API 记录 `PublicEvent 2026-08-26T12:59:48Z`：本仓库**曾于 8/26
公开过一次**（之后转回 Private——转私不产生公开事件，具体时点不可考；9/1 再次
转 Public 亦未产生第二条 PublicEvent）。两点含义：

1. F-1 所述明文形态在 8/26 起即有过真实公开窗口（当时仓库几乎零关注，暴露面
   仅为一个 5 位数字用户名、无邮箱/手机号/凭证语义——实际危害有限，但账本如实记）；
2. 9/1 的转 Public 发生在 06:4x–07:1xZ 之间，与脱敏 force push（CI 接收于
   07:13Z）几乎同刻——最坏情况存在约 20 分钟的旧图可见窗口；且旧 commit 对象
   在 GitHub 下次 GC 前可能仍按 SHA 直链短暂可达。

**处置决定**：判断为低危残留，不向 GitHub support 提 purge 申请；仅登记本节。
若日后发现该用户名被关联到真实身份造成困扰，再议。

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
