# 设计文档：xfail 期望清单 + 发布门禁（Embedded-AI-Harness 借鉴第一批）

- 日期：2026-08-26
- 状态：设计已经用户批准并经独立对抗评审修订，待实施计划
- 范围：Embedded-AI-Harness 五项借鉴中的两项 —— xfail/WILL_FAIL 机制、发布字节复跑门禁
- 落点：embedded-toolkit（verify.py 扩展 + 新增 release.py）

## 1. 背景

Embedded-AI-Harness（AICLP 方法论，克隆于 <工作区根>\Embedded-AI-Harness）的五项借鉴中，
FSD 规格层已于 2026-08-20 落地。本次落地剩余两项高优先级借鉴：

1. **xfail/WILL_FAIL**：测试先于代码——需求对应的可执行验证先写并标"预期失败"，
   套件保持绿；功能实现后测试转 PASS（XPASS），即落地信号。
2. **发布门禁**：打 tag 前，以干净重建的字节完整重跑验证旅程，全绿才允许发版。

现状断层：blink（工业架构时代）有 host 测试；adc-oled / button-toggle（GCC+HAL 新工作流）
没有任何可执行测试，验证靠 config.json 里少量字符串期望和 `--require-tgl` 等 CLI 参数，
需求→测试无结构化链接。且这两个工程没有 git 版本控制。

## 2. 解决的问题与价值

| # | 问题（含历史实例） | 机制 |
|---|---|---|
| 1 | OLED init 参数列从未发送→面板全黑一月余；无可执行断言盯"屏幕真的显示了" | 每条需求挂期望，每次 verify 全量重验 |
| 2 | 假 PASS（RTT 陈旧控制块事件）；AI 临场挑弱断言自证成功 | 证据标准前置固定在清单里，无法临场放水 |
| 3 | "这条需求做完了吗"靠对话争论 | XPASS=机械落地信号；四态判定机器说了算 |
| 4 | 改线/重构后老功能是否健在靠人工确认 | 清单覆盖历史需求 = 免费回归网 |
| 5 | adc-oled / button-toggle 无版本控制，误改无回退 | 落地过程补建 git |
| 6 | 板子上烧的哪版固件、发版时是否全绿，答不上来 | 发布记录：clean rebuild→烧的字节→验的字节→哈希入档→tag 互锁 |
| 7 | AI 驱动流程下"打个版"可能跳步 | 门禁把纪律从约定变成机制 |

诚实成本面：不能抓所有字节级 bug（定位仍靠 hardfault/review-code）；每个新需求多几分钟
写期望；过渡期多格式并存（见第 12 节）。

一句话：**xfail 把"验证什么"从 AI 临场决定变成规格前置，release 门禁把"算不算完成"
从口头承诺变成机器互锁。**

## 3. expectations.json 规格

位置：`<project>/.workbench/expectations.json`。

```json
{
  "version": "1.0",
  "expectations": [
    {
      "id": "FR-ADC-01",
      "desc": "上电 ADC 初始化成功",
      "patterns": ["\\[init\\] ADC OK"],
      "xfail": false
    },
    {
      "id": "FR-OLED-03",
      "desc": "刷新率行出现且数值 ≥2Hz",
      "patterns": ["OLED refresh (\\d+(?:\\.\\d+)?) Hz"],
      "capture_group": 1,
      "min": 2,
      "xfail": true,
      "xfail_reason": "刷新率上报功能未实现"
    }
  ]
}
```

字段规则：

- **匹配字段二选一**：`texts`（字面子串数组）或 `patterns`（正则数组）。数组内**所有**
  条目都必须命中，该期望才算匹配——单条模式只能表达存在性，数组用于消除"期望剧场"
  （例：`"OLED refresh \d+ Hz"` 会放行 "refresh 0 Hz"，数值约束必须靠 capture_group 断言）。
- **可选数值断言**：`capture_group` 指定 `patterns[0]` 的捕获组（从 1 计），提取值须满足
  `min` 和/或 `max`（可只给一边）。未给 capture_group 时忽略。
- `id`：必填、唯一。**本地稳定标识符**（命名沿用 FSD 风格如 FR-xxx-nn 是惯例而非强制；
  与 FSD 文档的对账校验列为非目标）。试点工程暂无 FSD，不虚构对应关系。
- `desc`：必填，人读描述。**诚实规则**：不得承诺匹配机制验证不了的性质。
- `xfail`：布尔，缺省 false。`xfail_reason`：`xfail: true` 时**必填**
  （No code without a clause 的对应物：无理由的预期失败不允许存在）。校验失败视为
  清单非法，verify 直接报错拒跑（id 重复、texts 与 patterns 并存、两者皆缺同理）。

## 4. 四态判定

| 状态 | 条件 | 含义 | 对套件判定的影响 |
|------|------|------|------------------|
| ✅ PASS | 匹配 & 非 xfail | 需求有证据 | 绿 |
| 🟡 XFAIL | 未匹配 & xfail | 预期红 | 绿（计入 xfail 数） |
| 🔴 XPASS | 匹配 & xfail | 落地信号 | **红（严格模式）** |
| ❌ FAIL | 未匹配 & 非 xfail | 缺证据 | 红 |

XPASS 采用严格模式：功能落地而清单未翻转 = 清单与现实不一致 = 未完成。输出走**专属
提示**（"🔴 <id> XPASS → 功能已落地，请翻转 xfail 后重跑"，复用 _save_failure_context
时不得套用 missing-patterns 的排查 hint——那是给 FAIL 用的）。

总判定：所有非 xfail 全 PASS **且**所有 xfail 全 XFAIL → 绿；否则红。

已知限制（文档明示，不建机制）：周期性输出在固定采集窗内的存在性匹配有天然抖动，
偶发 FAIL 属正常，重跑即可。

## 5. verify.py 扩展

1. **新增纯函数** `evaluate_expectations(capture_text, expectations) -> {results[], verdict}`：
   无 IO，四态判定 + 聚合全在里面；verify.py 调用它，release.py 经由 --json 间接消费，
   单测直接测它。
2. **加载顺序**：`.workbench/expectations.json` > config.json `verify.expect` /
   `expect_patterns`（legacy 回退，行为逐字节不变，blink 零影响）。
3. **CLI 叠加断言**（`--require-tgl` 等）继续有效，在 results 中合成为保留 ID 行
   （前缀 `CLI-`，如 `CLI-REQUIRE-TGL`），保证 --json 消费者看到完整门禁证据。
4. **新增旗标**：
   - `--rebuild`：构建步骤向 gcc_build 传 `action="rebuild"`（先 clean 再编译），
     日常默认仍为增量 build。
   - `--gate-run`：声明本运行由发布门禁发起——跳过 feedback_db 落账（避免门禁失败/
     豁免运行污染校准统计），_save_failure_context 保留。
5. **`--json` 输出**增加 `"results": [{"id", "status"}]` 数组（加法变更，现有字段不动）。

## 6. release.py 发布门禁

位置：toolkit `scripts/release.py`。**不复用 import verify.py**（其编排内联于 main()，
import 有副作用，工具库明文"按脚本不做共享模块"）——G1 以 subprocess 调
`python verify.py --json --rebuild --gate-run` 并解析返回。门禁验证的就是开发者日常
那条命令，公信力更强。

```
python <toolkit>/scripts/release.py --tag vX.Y.Z [--project <dir>] [--dry-run] [--allow-xfail]
```

门禁序列（任一失败即中止）：

| 门 | 检查 | 失败动作 |
|----|------|----------|
| G0 | 是 git 仓；工作树 clean；本地无同名 tag；无 git_head 相同的既有记录 | 提示先 commit / 换 tag 名 |
| G0.5 | SWD 连通性预检（秒级，复用现有 OpenOCD 机制） | 区分"环境未备"与"固件真坏"，免分钟级白等 |
| G1 | subprocess 完整重跑 verify（clean rebuild + 清单判定），退出码绿 | 报告红的条目 |
| G2 | results 中无 xfail 状态条目 | 列出条目；`--allow-xfail` 显式豁免并入档 |
| G3 | 发布记录落盘成功 | — |

发布记录 `<project>/.workbench/releases/<tag>.json`：

```json
{
  "tag": "vX.Y.Z",
  "git_head": "<sha>",
  "branch": "<branch>",
  "timestamp": "<ISO8601>",
  "build_mode": "clean_rebuild",
  "artifacts": {"hex": {"path": "...", "sha256": "..."},
                 "elf": {"path": "...", "sha256": "..."}},
  "results": [{"id": "FR-ADC-01", "status": "pass"}],
  "xfail_waived": [],
  "tools": {"gcc": "<version>", "verify": "<version>"}
}
```

**tag 安全序列**（消除"记录已写、tag 失败"死区与 TOCTOU）：

1. 写 releases/<tag>.json；
2. 复核 HEAD == record.git_head 且工作树仍 clean（防检查后被并发改动）；
3. 打 annotated tag（message 引用记录路径）;
4. 任一步失败 → 回滚删除刚写的记录文件。

拒绝键统一：**本地 tag 已存在 或 存在 git_head 相同的记录** → 拒绝。push 由用户自行执行。

## 7. 版本控制策略（.gitignore）

新工程 git init 时同步落盘：

- **入库**：`.workbench/config.json`、`.workbench/expectations.json`、`.workbench/releases/`
  ——tag 冻结的不只是代码字节，还有决定这个 tag 能否打出来的验收契约与门禁证据。
- **忽略**：`.workbench/build/`、`.workbench/state.json` 及各类失败现场转储。

## 8. 落地路径

1. **adc-oled（试点主战场）**：git init + 第 7 节 gitignore 策略 → 将 config.json 现有
   4 条 expect/pattern 迁移为 expectations.json → 故意加一条 xfail 未来需求走通闭环。
2. **button-toggle（排在 adc-oled 验收剧本全绿之后）**：注意它是**全量引导而非迁移**——
   该工程目前连 .workbench 都没有。内容：git init + gitignore + 新建最小 config.json
   （参照 adc-oled 形态）+ expectations.json（TGL 检查转为清单条目）。
3. **blink 不动**：legacy 回退继续服务；机会性迁移，迁移前回归项必须实际执行。

## 9. 验收剧本（完成定义）

adc-oled 上端到端：

1. 新增需求 → 先写 xfail 期望 → verify 红（XFAIL 生效）。
2. 实现功能 → verify 报 XPASS（专属翻转提示）→ 翻转 → 全绿。
3. `release.py --tag vX.Y.Z --dry-run`：G0~G2 全过，不出档不打 tag。
4. 正式 `release.py --tag vX.Y.Z`：clean rebuild 证据 + 记录落盘 + annotated tag 成功。
5. 反向 A：改动不 commit 直接跑 release → 被 G0 拦截。
6. 反向 B：留一条 xfail 打 tag → 被 G2 拦截；加 `--allow-xfail` 后 xfail_waived 留痕。
7. 回归：blink legacy 模式 verify **实际执行**一遍，照常 PASS。

## 10. 测试策略

- **单测**（unittest，沿 toolkit tests/ 惯例）：evaluate_expectations 四态各自命中、
  总判定组合边界、patterns 数组全命中语义、capture_group/min/max 边界（恰等阈值）、
  CLI 合成行合并、非法清单校验（id 重复 / xfail 缺 reason / text+pattern 并存 /
  两者皆缺）。
- **门禁矩阵**（临时 git 仓夹具）：G0 各失败路径、G0.5 预检失败、tag 失败回滚、
  HEAD 变动复核触发、拒绝键两分支、--dry-run 零副作用。
- **真机 E2E**：第 9 节剧本（需调试器在位）。

## 11. 非目标（YAGNI，留给后续立项）

host 测试平面、prohibited_outcomes、CI 容器构建、Method/手册平面、fresh-checker 协议
结构化、多板租赁仲裁、**FSD 对账校验**、FAIL 自动重测机制。

## 12. 有意偏离与风险

### 对 Harness 原典的有意偏离（记录在案）

Harness 规定"tag 永远是用户动作，CI 验证已 tag 的字节"；本设计反转为脚本验证工作树后
代打 tag，且 fresh-checker 未引入（自验自）。理由：单人工作流无 CI；
`release.py --tag vX.Y.Z` 的**调用本身**即用户发版意志的表达，脚本只是执行代理；
机械门禁 + 记录留痕补位 checker 缺位。

### 风险与缓解

| 风险 | 缓解 |
|------|------|
| verify.py 工作树已有未提交改动，叠加改造易冲突 | 实施第 0 步：先单独提交存量改动或与用户确认基线 |
| 固定采集窗内周期输出存在性匹配有抖动 | 第 4 节已明示限制；重测机制列非目标 |
| 三种状态并存（blink legacy / adc-oled 清单 / toggle 待引导）认知负担 | 判别规则写进 README（有 expectations.json 用清单，否则回退）；两个工程落地后评估 blink 收编 |

## 13. 评审记录

2026-08-26 由无对话上下文的独立对抗评审 agent 完成（读盘核实设计假设，非背书式评审）：
High×3 / Med×4 / Low×4 共 11 项发现**全部采纳**并体现于本文——High 三条（subprocess
替代 import 复用、patterns 数组+数值断言、强制 rebuild）使设计比初稿更简单；
同时确认：verify() 判定核心已是近纯函数、legacy 回退与 blink 现状吻合、四态语义与
Harness 原文一致。
