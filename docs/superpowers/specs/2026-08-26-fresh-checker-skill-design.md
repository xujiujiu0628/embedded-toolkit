# 设计文档：fresh-checker skill（无上下文对抗审核的结构化）

- 日期：2026-08-26
- 状态：设计已获用户批准（对话内呈现），待实施
- 落点：`%USERPROFILE%\.claude\skills\fresh-checker\SKILL.md`（单文件，零新代码）
- 渊源：Harness 借鉴 #5 的轻量替代——本日两轮实战（harness-borrow 设计审 11 发现、
  实现审 3M+6L）证明了模式有效，本文将其从"临场手艺"固化为可复用剧本

## 1. 问题与价值

gate 的 Harness 原义是"新 checker 核查而非作者自查"。完整协议（多审核员/租赁仲裁）
对单人工作流过重，但"派一个无对话上下文的全新 agent、读盘核实、对抗找茬"这个最小
内核已被验证两次。不结构化的代价：每次靠临场组织提示词，质量随状态波动、经验不留存。

结构化收益：一键召唤、维度清单沉淀（含本次审计发现的探针手法）、落 feedback 库
积累流水线统计。

## 2. 载体形态

纯 SKILL.md（用户已确认），与 review-code / review-hardfault 同构：
frontmatter（name/description）→ When to Use → Instructions 分步。

## 3. 四步流程（skill 正文骨架）

1. **界定对象**：编排者只收集材料指针——spec 文件路径 / diff 范围（git 区间）/
   实现产物路径 / 可运行的验证命令；**明确禁止附带编排者自己的结论与立场**。
2. **派发**：Agent 工具，general-purpose，`run_in_background=false`，全新会话；
   按 `--mode` 取 §5 对应内嵌提示词模板。
3. **结果处置**：向用户转述分级报告 → `feedback_db.py --log '<json>'` 落账 →
   对 Critical/High 逐条给修复建议。
4. **回归样例**：2026-08-26 两轮审核的提示词与本 skill 的模板同源，可作对照。

## 4. 共同铁律（两套模板共有）

1. 只读审计：禁改文件，但允许运行测试与只读命令取证；
2. 职责是找问题不是背书；没有证据的猜测必须标注为推测；
3. 每条发现必须落到 `文件:行号` 或命令输出；
4. 输出格式固定：总体结论一句话（通过/通过但有保留/需返工）→ 分级发现
   （Critical/High/Medium/Low × 问题+证据+建议）→ 确认合格清单 → 关键验证命令摘要。

## 5. 双模式维度

### --mode design（审规格/方案）

| 维度 | 探针要求 |
|------|----------|
| 假设核实 | 设计中的每条事实性声称到磁盘/代码核实，不许凭空评 |
| 边界与缺口 | schema 盲区、错误路径、时序窗口、并发/竞态 |
| YAGNI 反向审查 | 有没有被忽略的更简单做法；是否过度工程 |
| 安全与数据丢失 | 自动化动作的回滚路径、误删/覆盖风险 |
| 前提漂移 | 分析时的前提现在是否仍成立（如工具链更换） |

### --mode impl（审实现）

| 维度 | 探针要求 |
|------|----------|
| 规格符合度 | 规格逐条对照实现，列出无任务对应的条款 |
| 代码正确性 | 写边界探针实测（非法输入/异常路径/组合语义），引用运行输出 |
| 测试充分性 | 高风险路径 vs 已测集合的差集；漏测即发现 |
| 产物可信度 | 哈希重算、tag 指向核对、commit 叙事一致性 |
| 文档债 | checkbox/README/spec 与实现有无漂移 |

## 6. feedback 落账 schema

```json
{"pipeline": "fresh_check", "mode": "design|impl",
 "target": "<spec 路径或 commit 区间>",
 "verdict": "pass|pass_with_reservations|rework",
 "findings": "C:<n> H:<n> M:<n> L:<n>", "outcome": "reported"}
```

事件写入 `feedback_db.py` 的**事件流**（`<工程>/.workbench/feedback/events/*.json`，
落账须在被审工程根目录执行；审核 toolkit 自身等无 `.workbench` 对象时约定落到
活跃工程并在 target 注明）。注意语义（2026-08-26 首轮自审计 H-1 修正）：
`--stats` 只聚合修复循环校准（calibration.json），fresh_check 记录在 stats 中
不可见属预期——审计记录的检索走 events 目录与完整 JSON，不走成功率聚合。
"发现准确率"回填（findings 是否被后续证实）列为未来增强，本期不做。

## 7. 验收标准

下次任一设计/实现完成后触发本 skill，能严格走完四步且 feedback 库出现
fresh_check 记录；两套模板与今日两轮实战提示词同源可比对。

## 8. 非目标（YAGNI）

脚本化清单渲染、多审核员投票、发现准确率自动校准、租赁仲裁、跨机调度。
