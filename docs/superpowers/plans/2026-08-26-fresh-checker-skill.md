# fresh-checker Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"无上下文对抗审核"固化为可一键召唤的个人 skill：双模式提示词模板 + feedback 落账。

**Architecture:** 单文件 SKILL.md（与 review-code 同构：frontmatter → When to Use → 四步 Instructions，内嵌两套完整审核员提示词模板），外加一份 tracked 镜像进 toolkit 仓做版本控制。落账复用现有 feedback_db.py。

**Tech Stack:** Markdown（Claude Code 个人 skill 格式）、feedback_db.py（已存在）。

## Global Constraints

- 规格文件：`docs/superpowers/specs/2026-08-26-fresh-checker-skill-design.md`（本仓 e96718b 系列）
- 规范路径：canonical = `C:\Users\<用户名>\.claude\skills\fresh-checker\SKILL.md`；镜像 = 本仓 `skills/fresh-checker/SKILL.md`；两处必须逐字节一致（同一次提交内同时更新）
- frontmatter 惯例沿 review-code：`name:` 小写连字符、`description:` 含触发词的英文长句
- 反馈管道名固定 `fresh_check`；schema 见规格 §6，字段名不得改动
- SKILL.md 内引用 toolkit 脚本用字面路径 `<工作区根>\embedded-toolkit\scripts\feedback_db.py`（文档性引用，不违反"机器路径只在 machine.json"——该铁律约束脚本运行期取径）
- 提示词模板必须包含规格 §4 四条共同铁律原文

---

### Task 1: 创建 canonical SKILL.md

**Files:**
- Create: `C:\Users\<用户名>\.claude\skills\fresh-checker\SKILL.md`

**Interfaces:**
- Produces: 可被 Claude Code 调度的个人 skill `fresh-checker`；Step 4 的落账 JSON 字段（Task 2 冒烟依赖）：
  `{"pipeline":"fresh_check","mode":"design|impl","target":"<str>","verdict":"pass|pass_with_reservations|rework","findings":"C:x H:y M:z L:w","outcome":"reported"}`

- [x] **Step 1: 写入以下全文**

````markdown
---
name: fresh-checker
description: MUST USE when the user asks for a deep/adversarial review of a finished design or implementation — e.g. 深度审核 / 审计一下 / 再审一遍 / fresh checker / second-opinion audit. Dispatches a context-free reviewer agent that verifies claims against disk, probes boundaries, and returns severity-ranked findings; logs the verdict to the feedback database. Use AFTER work is complete (spec approved, code committed), NOT for debugging or open-ended exploration.
---

# /fresh-checker — 无上下文对抗审核（Fresh Checker）

## When to Use

一项设计或实现**已完成**（规格获批 / 代码已提交）之后，用户要求深度审核时。
本质是 Harness "gate 由新 checker 核查而非作者自查"的最小内核：派一个没有任何
对话上下文的全新 agent，只给它材料指针和对抗指令，让它读盘核实、实测探针、分级报告。

**不要用于**：调试中的排障（用 systematic-debugging）、开放探索、还没写完的东西。

## How It Works

1. 界定对象：收集材料指针，不带结论
2. 派发：Agent 工具，general-purpose，`run_in_background: false`，全新会话
3. 处置：向用户忠实转述分级报告（agent 最终文本用户看不到，必须由你转达），
   对 Critical/High 给修复建议
4. 落账：feedback_db.py 记一条 fresh_check 流水线事件

## Instructions

### Step 1: 界定审核对象

收集并填入派发提示词的材料区（只有指针，没有结论）：

- **--mode design**：spec 文件路径、被声称的事实所在的代码/目录路径、可运行的
  核实命令示例
- **--mode impl**：规格文件路径、实现 diff 的 git 区间（如 `d174acc..HEAD`）、
  工程产物路径（tag/记录/哈希文件）、测试运行命令

⚠️ 你对这次工作的全部了解、立场、"应该没问题吧"的预感——一个字都不许进入提示词。
审核员的价值恰恰在于它不知道你知道什么。

### Step 2: 派发审核 agent

用 Agent 工具（subagent_type=general-purpose，run_in_background=false），
提示词 = 下面与 mode 对应的模板 + Step 1 的材料区。

#### 模板 · 共同铁律（两套都以此开头）

```text
你是资深审计员，此前从未接触本项目，以全新怀疑视角做对抗性评审。
你的职责是找问题，不是背书。

铁律：
1. 只读审计——禁止修改/创建/删除任何文件；但允许运行测试和只读命令取证；
2. 没有证据支撑的猜测必须显式标注为推测；
3. 每条发现必须落到 文件:行号 或你实际运行的命令输出；
4. 输出格式（中文）：总体结论一句话（通过/通过但有保留/需返工）→
   分级发现【Critical/High/Medium/Low】×N 条（问题+证据+建议）→
   确认合格清单（简短）→ 关键验证命令及结果摘要表。
直接给报告，不要寒暄。你的最终回复就是报告本身。
```

#### 模板 · --mode design 追加段

```text
# 待评审设计（全文照录）
<设计文档全文或路径列表>

# 你的评审任务
1. 先到磁盘核实设计中的每条事实性假设（引用你读到的文件:行号），不许凭空评；
2. 对抗性找茬，至少覆盖：
   - 假设核实：哪些声称与现状不符？
   - 边界与缺口：schema 盲区、错误路径、时序窗口、并发竞态；
   - YAGNI 反向审查：有没有被忽略的更简单做法？是否过度工程？
   - 安全与数据丢失：自动化动作有没有回滚路径？误删/覆盖风险？
   - 前提漂移：分析时的前提现在还成立吗？（工具链/环境是否变过）
```

#### 模板 · --mode impl 追加段

```text
# 审计对象
<规格路径> / <diff 区间> / <产物路径> / <测试命令>

# 你的审计维度（逐项给证据）
1. 规格符合度：规格逐条对照实现，指出无对应实现的条款；
2. 代码正确性：写边界探针实测（非法输入/异常路径/组合语义），
   引用运行输出作为证据；
3. 测试充分性：高风险路径与已测集合的差集，漏测即发现；
4. 产物可信度：哈希重算比对、tag 指向核对、commit 叙事一致性；
5. 文档债：checkbox/README/spec 与实现有无漂移。
```

### Step 3: 转述与处置

1. 向用户完整转述报告（总体结论 + 全部分级发现 + 合格确认），不得只报喜；
2. 对每个 Critical/High 给出具体修复建议；
3. 用户决定处置后，修复属于常规开发流程（TDD），不在本 skill 范围内。

### Step 4: feedback 落账

```powershell
python <工作区根>\embedded-toolkit\scripts\feedback_db.py --log '{"pipeline":"fresh_check","mode":"design","target":"docs/superpowers/specs/xxx.md","verdict":"pass_with_reservations","findings":"C:0 H:3 M:4 L:6","outcome":"reported"}'
```

字段固定：pipeline 恒为 `fresh_check`；verdict ∈ pass|pass_with_reservations|rework；
findings 用 `C:x H:y M:z L:w` 计数串。落账失败不影响审核结论交付，事后补记即可。
````

- [x] **Step 2: 结构自检清单**

逐项核对写入的文件：frontmatter 含 name=fresh-checker 且 description 含触发词
（深度审核/审计/fresh checker）；四条共同铁律逐字出现；两套模板各自含五个维度；
Step 4 的 JSON 字段与规格 §6 一致（pipeline/mode/target/verdict/findings/outcome）。

- [x] **Step 3: Commit（镜像随 Task 2 一起提交）**

本任务无 git 操作（~/.claude 非 git 仓）；镜像提交在 Task 2 Step 3。

---

### Task 2: toolkit 镜像 + feedback 管道冒烟

**Files:**
- Create: `<工作区根>\embedded-toolkit\skills\fresh-checker\SKILL.md`（canonical 的逐字节拷贝）
- Test: feedback_db.py 冒烟（运行即测）

**Interfaces:**
- Consumes: Task 1 的 canonical 文件；现有 `scripts/feedback_db.py --log/--stats`。

- [x] **Step 1: 拷贝并校验逐字节一致**

```bash
mkdir -p <工作区根>/embedded-toolkit/skills/fresh-checker
cp /c/Users/<用户名>/.claude/skills/fresh-checker/SKILL.md <工作区根>/embedded-toolkit/skills/fresh-checker/SKILL.md
diff /c/Users/<用户名>/.claude/skills/fresh-checker/SKILL.md <工作区根>/embedded-toolkit/skills/fresh-checker/SKILL.md && echo IDENTICAL
```
Expected: 输出 IDENTICAL。

- [x] **Step 2: feedback 管道冒烟**

```bash
python <工作区根>/embedded-toolkit/scripts/feedback_db.py --log '{"pipeline":"fresh_check","mode":"impl","target":"2026-08-26 harness-borrow batch1","verdict":"pass_with_reservations","findings":"C:0 H:0 M:3 L:6","outcome":"reported"}'
python <工作区根>/embedded-toolkit/scripts/feedback_db.py --stats fresh_check
```
Expected: log 成功；stats 能查到 fresh_check 流水线记录（若 stats 仅支持内置
pipeline 名，以 log 不报错为准并在 commit message 注明）。这条冒烟数据本身就是
今天第二轮真实审计的存证。

- [x] **Step 3: Commit**

```bash
cd <工作区根>/embedded-toolkit
git add skills/fresh-checker/SKILL.md
git commit -m "feat(skill): fresh-checker 无上下文对抗审核剧本（canonical 镜像）

canonical 位于 ~/.claude/skills/fresh-checker/；两处须同 commit 更新。
含 design/impl 双模式提示词模板与 fresh_check feedback 落账 schema，
素材来自 2026-08-26 两轮实战审核。"
```

---

### Task 3: 验收说明（无需执行动作）

skill 的真正调度验证需要 Claude Code 重启后重新扫描个人技能目录——本次会话内
无法端到端点验。验收口径：

- [ ] **结构验收**（本会话）：Task 1 Step 2 清单全过 + Task 2 两步通过
- [ ] **调度验收**（下次会话自然发生）：用户说"深度审核一下"时 skill 出现并被调用；
  若未被自动调度，手动 `/fresh-checker` 应能加载

## Self-Review 结论

- 规格覆盖：§2 载体→T1，§3 四步→T1 正文骨架，§4 铁律→两模板开头，§5 双维度→两模板，§6 schema→T1 Step 4 + T2 Step 2 冒烟，§7 验收→T3，§8 非目标未引入
- 类型一致性：落账 JSON 六字段在 T1 Interfaces、T1 Step 4、T2 Step 2 三处完全一致
- 无占位符：SKILL.md 全文内嵌于计划
