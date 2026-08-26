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

⚠️ **必须在被审工程根目录下执行**（feedback_db 按 cwd 向上找 `.workbench/config.json`
定位库；在 toolkit 根或任意非工程目录跑都会 exit 1）。审核 toolkit 自身这类
无 `.workbench` 的对象时，约定落到任一活跃工程（如 stm32f103-adc-oled），
并在 `target` 里写明真实审核对象。

```powershell
cd <被审工程根>
python <工作区根>\embedded-toolkit\scripts\feedback_db.py --log '{"pipeline":"fresh_check","mode":"design","target":"docs/superpowers/specs/xxx.md","verdict":"pass_with_reservations","findings":"C:0 H:3 M:4 L:6","outcome":"reported"}'
```

字段固定：pipeline 恒为 `fresh_check`；verdict ∈ pass|pass_with_reservations|rework；
findings 用 `C:x H:y M:z L:w` 计数串。

**判级判据**（落账可比性的锚）：Critical = 数据丢失/安全漏洞/主流程不可用；
High = 声称与实现不符、或核心场景必现错误；Medium = 边界缺陷、文档债、
可静默劣化的缺口；Low = 措辞、风格、推演性理论风险。

已知语义（2026-08-26 首轮自审计确认）：白名单校验**仅告警不拦截**；
`--stats` 只聚合修复循环校准——fresh_check 事件存于事件流（`events/*.json`），
stats 查不到属预期，不是丢数据。落账失败不影响审核结论交付，事后补记即可。
