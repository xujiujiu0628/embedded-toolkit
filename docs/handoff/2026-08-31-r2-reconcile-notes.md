# 2026-08-31 R2 代管换回对账记录（主控）

> 对账依据：主控派发 fresh-check 无上下文对抗核查（对象 `aae9084..18561d1` +
> `2026-08-30-findings-r2.md`，2026-08-31，结论 **通过但有保留**：C0/H1/M1/L2，
> 落账 `fc_20260831_122115+0800`）。本文记录 High-1 处置、编号重排映射与换回遗留；
> R2 报告与代管日志正文保留作者原貌、不改写历史，修正一律以本文为准。

## 1. 根因确认（High-1）

- **磁盘事实**：`git rev-parse 34a96e5^` = `9997ac2`；`git merge-base 18561d1 master`
  = `9997ac2`。R2 分支父链起点为首轮旧终点，缺 master 侧 8 个 commit（含考卷刷新
  `2bd0c17` 与上岗戳 `aae9084`）。
- **reflog 时间线**：18:57:45 master 落 aae9084（宣告"基线 2bd0c17"）→ 18:59:20
  检出回 `handoff/zcode-20260830` → 18:59:35 切入 `handoff/zcode-r2-20260830`
  （该分支彼时**已存在且指向 9997ac2**）。
- **创建者**：推测（无盘证）。首轮 `6608be2` 已记录"ZCode UI 预建分支（从当时检出
  的分支切出）"先例，与本轮"从旧检出点预建"形态吻合。
- **影响链与处置**：§〇"主控文档未落盘"系过期树误判 → 本文更正；
  F-015/016/017 与 `1819e18` 撞号 → §2 重排；§2 #10/#11 覆盖主控版 → §4 合并；
  "155 全绿"仅本分支口径 → 合入后新基线见 §5。

## 2. 编号重排映射（作者编号 → 全仓编目编号）

| R2 报告原编号 | 重排后 | 内容 | 落点 |
|---|---|---|---|
| F-015 | **F-018** | 发布记录绑定契约哈希（verify `contract_hashes` → release `contracts` → release_audit **R7**） | 代码/测试注释、CHANGELOG 0.2、findings-r2 节标题 |
| F-016 | **F-019** | state.json 原子写（.tmp+os.replace）+ 损坏隔离 .corrupt 重建 | 同上 |
| F-017 | **F-020** | 写回型"损坏→清空"家族守卫（三份 runtime + gcc_build + error_db_grow） | 同上 |

占用依据：master `1819e18` 已编目 F-015/016/017（workspace 跟随 / 采集窗进契约 /
gcc 段读取双重错误），HANDOFF-AGENT.md、findings.md、gcc_build.py、test_gcc_build.py
四处引用在案；F-018~F-020 经全仓 grep 确认空闲。

## 3. 外部核查发现处置表

| 级别 | 发现 | 处置 |
|---|---|---|
| High-1 | 分支起点偏移 → 归因错误 + 编号冲突 + 合入冲突面 | ✅ 本文 + findings-r2 头部增补 + 编号重排 + §4 清单合并；合入演练与复验见 §5 |
| Medium-2a | `wb_runtime.py` `save_local_config`（环境级 `config/*.json`）仍为"损坏当空读→读改写→覆写"，F-020 同族漏网；全仓 grep 无调用方，实害受限；复现=临时副本喂损坏 config 一次写回清空 | ⏸ 登记 **F-021**（待排期） |
| Medium-2b | `error_db_grow.py:188,308`、`release.py:201` 仍裸 `open('w')` truncate 写；release 记录是 R7/M2 取证锚，撕裂即记录报废 | ⏸ 登记 **F-022**（建议并入 `save_json_file` 原子工具） |
| Low-3a | HANDOFF §5-1 残留"跑 47 套件"、§1"30 个脚本"（实际 31）硬编码 | ✅ 随合并改动态表述 |
| Low-3b | 报告/日志引用悬空 hash `a1ae583`/`d7f950c`（reset 重放，reflog 19:39:25 证实） | ✅ §6 对照表，前向引用改用可达 hash |
| Low-3c | `wb_runtime.py:217` docstring `.corrypt` 拼写（代码落盘名正确） | ✅ 已修（与改号同行） |
| Low-4a | `save_json_file` 固定 `<name>.tmp`，双进程并发写同一文件仍可混掺（与已认"lost update 未加锁"相邻） | ⏸ 登记 **F-023**（单操作者+硬件串行纪律下同 F-016 遗留判级） |
| Low-4b | release_audit R7 比对路径硬编码 `.workbench/config.json`，而 `contract_hashes` 认 `.embeddedskills`——该布局工程恒 warn（fail-closed 无假绿，缺口未声明） | ⏸ 登记 **F-024** |
| 待裁决 | 未跟踪 `.mcp.json`（cortex-debug SSE；创建于末次 commit 后 9 分钟；5 commit 均不含；用户确认非本人添加） | ✅ 已移出仓库至 `<工作区根>\archive\mcp-from-toolkit-20260831\`（同盘 move 保留时间戳证据；cortex-debug 全局配置本就存在，无功能损失） |

## 4. §2 勿重做清单合并结果

master 版 #10（首轮遗留 F-015/016/017 已修）、#11（A-02 哈希举证）保持原位；
R2 版 #10/#11（F-001~F-005 组 / F-014+Low 组+release_audit）顺位改 **#12/#13**，
其备注中的 R2 编号同步更新为 F-018/019/020。合并后清单共 13 行。

## 5. 合入演练与合入后全量验证（2026-08-31 实测回填）

- **冲突面**：仅 `HANDOFF-AGENT.md` 一处内容冲突——按 §4 规则重建合并版（考卷/
  清单 13 行/日志含双方全部条目）。`gcc_build.py` / `verify.py` 自动合并成功：
  master 侧 resolve_workspace_mode（F-015）与 R2 侧 merge_gcc_config（F-020）、
  采集窗契约化（F-016）与 contract_hashes（F-018）互不侵占，语义复核=172 例全绿。
- **套件**：merge 后 **Ran 172, OK**（155 ∪ 106，master 净增 17 例零丢失——恰为
  外部核查预估的 ≈172）。
- **guard**：`handoff_guard --branch handoff/r2-reconcile-20260831 --json` →
  verdict clean，6 commits，0 blocked / 0 warnings。
- **expectations_lint**：adc-oled 4 条 CLEAN / button-toggle 2 条 CLEAN（exit 0）。
- **release_audit**：两真档均 WARNED、仅 R7 warn、exit 0——F-018 旧记录缺
  contracts 的预期语义，与 findings-r2 §六-1 一致。
- **越域核查**：两工程 porcelain 全空；skills 与 <工作区根>\.claude 无晚于上岗戳
  （08-30 18:57）的 mtime。仓根曾出现未跟踪 .mcp.json，已按 §3 处置出库。
- **插板回归（用户主动要求，2026-08-31 13:29）**：adc-oled 全链真机 PASS——build
  0e0w / flash Verified OK / RTT 34 行 / 4 条期望全 pass 无 XPASS / 落账
  `bf_20260831_132926+0800`；F-018 的 `contract_hashes` 首次在真机 output 现身。
  首跑因板子未插死于 `OpenOCD init failed`（flash_failed 诚实报错），插好后一次过。

## 6. 重放对照表（悬空 → 可达）

| 重放前悬空 hash | 重放后等价 | 说明 |
|---|---|---|
| `a1ae583`（D 项 docs） | `18561d1` | guard 对 F-016/017 commit 注释措辞误报 openocd_call，未推送分支以历史重放消解（findings-r2 §六-4） |
| `d7f950c`（F-016 修复） | `351e021` | 与 F-017 修复合并为同一 commit |

## 7. 逐 commit RECONCILE 四分类

| Commit | 分类 | 说明 |
|---|---|---|
| `34a96e5` | 有效可行动 | F-018 修复 + 9 例回归；外部核查端到端复现"篡改契约 → R7=fail" |
| `351e021` | 有效可行动 | F-019/F-020 修复 + 17 例回归；其"B 全仓扫其余无发现"结论不完整（F-021/F-022 漏网，登记不返工） |
| `cc54e45` | 有效可行动 | 21 例纯逻辑零覆盖补测 |
| `10507bd` | 有效可行动 | expectations_lint E1~E9；建议采纳：纳入换回协议第 3 步秒检（§6 同步修订） |
| `18561d1` | 部分有效（契约误读） | D 项文档产出有效；§〇 归因误读系过期树所致，已按 §1 更正 |
