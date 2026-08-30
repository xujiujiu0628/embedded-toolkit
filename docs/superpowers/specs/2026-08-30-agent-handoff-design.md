# 设计文档：外部智能体代管机制（HANDOFF + 守门脚本）

- 日期：2026-08-30
- 状态：设计经用户逐节讨论批准（plan 文件 ai-stateful-newell），随首批实施
- 范围：为 AI+嵌入式工作台建立"异构智能体代管检查+改进"的可复用协议；首轮 Z code 实战
- 落点：embedded-toolkit（新增 HANDOFF-AGENT.md / scripts/handoff_guard.py / AGENTS.md / README 指针）

## 1. 背景

工作台的审查层目前是"我派自家无上下文的 Claude 子代理查我自己"：fresh-checker 已实跑
两轮（1H+5M+4L 闭环 5ffeb3a；深度审计 M1-M3 修复 9594dbb/d2c572a），修的都是真缺陷——
但审查者与建造者同源，盲区重叠无法排除。缺一个**没参与过工作台演进的异构智能体**，
独立来看、独立来改。

参照物：competition-prep 的 Z code 代管已跑通（HANDOFF-ZCODE.md 六节骨架 + 代管日志 +
换回协议），本次把同档机制带给嵌入式工作台，并针对其特殊性加固：
**有真机（克隆 ST-Link 脆弱链路）、有机器裁判（36 测试）、多 git 仓（仅 toolkit 可写）**。

## 2. 决策记录（用户逐条拍板，2026-08-30）

| 维度 | 决策 | 弃选项与理由 |
|---|---|---|
| 检查者形态 | 交互式智能体代管，首现 = Z code | Codex 非交互巡检→作第二梯队后议；同源子代理→盲区重叠 |
| 权限边界 | 沙盒写权限：只码不碰硬件（不烧录/不真机 verify/不开串口） | 全权代管→克隆 ST-Link 与门禁误操作风险；只读→"改进"落不了地 |
| 范围 | 全系统只读可评，**仅 toolkit 仓可写**，余者交建议单 | 含工程可写→发布受控状态不该被代管期搅动 |
| 物理布局 | 不建聚合文件夹，HANDOFF §4 绝对路径地图指路 | junction 视图/物理迁移→违背禁区规则，收益不值路径风险 |
| 验收 | 双验收：①机制跑通 ②审计有货（数量不作硬指标） | 纯数量导向→逼凑数提交 |
| 时机 | 现在就并行开（与 competition-prep 代管同时） | |
| 机制形态 | 方案 A：文档+守门脚本 | B findings.jsonl→协议过重 YAGNI；C 纯文档→硬件禁线无机器判据 |

## 3. 机制组成

```
Z code（异构代管者）
  │ 仅凭 HANDOFF-AGENT.md 上岗
  ▼
handoff/<agent>-<YYYYMMDD> 分支 ←— 唯一写入面（toolkit 仓，master 不动）
  │ 每发现一 commit；发现报告落 docs/handoff/<日期>-findings.md
  ▼
换回协议（主控 Claude 五步）
  1. handoff_guard.py 全分支 diff 扫描（机器禁线）+ 越域核查
  2. python -m unittest discover -s tests（36 基线）+ gcc_build 编译
  3. 逐 commit RECONCILE（契约误读/有效可行动/有效权衡/噪声）
  4. merge → 用户插板跑一次 verify --json 真机终判
  5. 落账：feedback_db 事件 + 记忆回填 + HANDOFF 状态翻转
```

## 4. HANDOFF-AGENT.md 六节（智能体无关写法）

1. **工作台是什么**：五流水线一页图（需求→生成[review-code]→构建[gcc_build/verify]→
   真机[RTT/semihosting]→门禁[release G0-G3]→落账[feedback_db]）+ 目录地图 + 现役状态。
2. **已验证勿重做清单**（每条带证据 commit/测试名）：四态判定、XPASS 强制红、门禁回滚、
   退出码纪律（ad9c625）、36 套件。**特意收录有意决策**（如 UART 串口门禁脆弱性 08-27
   评估后主动搁置）——防止代管者把深思过的取舍当 bug 报。
3. **代管期任务**：巡检清单四级 + 交付三档（分级报告/严重项直接修/非可写域建议单）。
   - 代码级：subprocess 超时与返回码纪律、cwd 依赖、GBK/UTF-8 编码、JSON 加载器容错
     （M1 四连坑模式）、try/finally 完整性
   - 机制级：--gate-run/--allow-xfail 旁路、xfail 翻转完备性、落账静默跳过、
     release 无哈希静默落档（M2 同类）
   - 文档级：README 承诺 vs 实际漂移、blink 退役后的失效引用
   - 系统级（只出建议单）：四全局 skill 重叠、fresh-checker 双份镜像同步、
     两工程 .workbench 契约格式兼容
4. **环境接入**：物理地图（绝对路径 + 可写性标注）、测试命令、machine.json 只读、
   无凭据需求、**显式印出将被 guard 捕获的硬件命令模式**（与 guard L2 常量同源）。
5. **交接规矩**：handoff 分支纪律、`fix(handoff): F-00N …` commit 格式、改行为码必带
   回归测试、禁改区列表、禁止顺手重构/批量改名、每日代管日志（做了什么/下一步/卡点）。
6. **换回协议**（给主控 Claude）：第 3 节五步 + 越域核查细则。

## 5. handoff_guard.py 判据

输入 `git diff master...<branch>`（文件清单 + patch 全文），输出 JSON
`{verdict: clean|blocked, violations:[{commit,file,rule,evidence-line}]}`，退出码 0/1。

- **L1 文件禁线（硬阻断）**：machine.json、hooks/、scripts/handoff_guard.py 自身
- **L2 硬件模式（阻断，归属到 commit）**：openocd 调用含 flash/verify/init 类参数、
  烧录命令、serial.Serial/pyserial、RTT 端口 19021、gdb 连硬件目标
- **L3 警告（不阻断）**：改 verify.py/release.py 主流程但 tests/ 无新增 → 人审清单
- **误杀防御**：tests/、fixtures 内字符串走 allowlist；判据内容导向（向 L2 命中要求
  行内含调用语境而非裸词），吸取 swd_probe 关键词误判教训。
- **双向自测纪律**（xfail 式）：clean 样例必须过、埋雷样例必须拦、allowlist 样例不误杀。

## 6. 双验收（首轮成功判据）

- ①机制跑通：Z code 仅凭文档完成 onboarding（贴 36 套件输出）、提交全在 handoff 分支、
  guard 绿、日志连续 ≥2 天
- ②审计有货：分级报告覆盖巡检四级（每级至少"查了+结论"，"无发现"算结论）、
  Critical/High 有复现法、修复带回归测试
- 终判：合入后用户插板 verify --json 真机绿才算闭环

## 7. 边界与风险处置

- 代管期 master 动了 → 换回前 rebase 再扫；guard 与越域核查只认最终 diff
- 违规直提 master → 换回第一步 `git log master` 核对，未走协议 commit 一律 revert
- 会话中断无日志 → `git log handoff/*` 倒推为事实源 + 全量 diff 人审
- guard 误杀 → L2 命中可提异议，仲裁写进日志；事后修 allowlist 且同类进测试

诚实成本面：guard 拦不住"故意绕编码/拆字符串"的恶意规避——本协议威胁模型是**善意的
陌生智能体犯糊涂**，不是对抗攻击者；真机路径的最终防线仍是换回后的人工 diff + 用户插板。

一句话：**把"另一个智能体能安全地改这个工作台"从信任问题变成机器可验的分支纪律。**

## 8. 明确不做（本设计外）

- Codex CLI 非交互巡检（第二梯队，首轮实战后再议）
- findings.jsonl 结构化交付（落账自动化需求出现时再启）
- 三平面文档 / CI 容器借鉴（状态不变：YAGNI / 挂起）
