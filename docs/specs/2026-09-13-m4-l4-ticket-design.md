# M-4/L-4 验证缺口小工单设计

> 日期：2026-09-13 ｜ 分支：0912 ｜ 状态：已获维护者批准
> 来源：总工单 v2 终审遗留（README「已知遗留」M-4 / L-4 两条），
> 记忆账本：`embedded-toolkit-ticket-2026-09-13`。

## 目标

销掉两笔登记在册的验证缺口，各自带 CHANGELOG F 号记账与 README 遗留条目改写：

1. **M-4**：`--junit-xml` 产物从未被任何 GitHub Actions test reporter 消费
   （单测层 XML 可解析性已过，缺的是"reporter 实吃"）。
2. **L-4**：`verify.step_flash` 直连 openocd `program`，不经 N-3 构造性标记链
   ——高频真机路径缺"构造性证据优先于退出码"。

## 范围外（明确不做）

- D-2 分发形态 spike、arXiv 引用核实——留待后续工单。
- `openocd_run.py` 自身的 N-3 语义不改（现有 `test_openocd_n3_marker.py`
  是全量回归钉）。
- step_flash 的 timeout（30s）、WORKSPACE 相对 hex 路径语义、hw_lease
  锁归属（上游持有，不二次抢锁）全部不动。

## 第 1 节 M-4：JUnit reporter 实吃（决策：方案 A，第三方 Action + SHA 锁定）

### 改动

`ci.yml` 的 `sim-demo` job：

1. 现有 verify 步骤追加旗标：
   `python scripts/verify.py --project examples/sim-demo --json --junit-xml build/junit-sim.xml --timeout 20 | tee verify-result.json`
   （`junit_xml.py` 与 verify 的 `--junit-xml` 接线在 F-147 已存在，零新代码。）
2. 新增消费步骤：
   - `uses: dorny/test-reporter@<40位SHA>`
   - `if: always()` —— 失败运行的 XML 也要被 reporter 吃过才算验证。
   - `continue-on-error: true` —— reporter 红了不掩盖 verify 真因；销账
     验证那一跑由人盯 PR 确认摘要在场。
   - `with: name: Sim Verify Results`、`path: build/junit-sim.xml`、
     `reporter: java-junit`。

### 供应链纪律

- `dorny/test-reporter`（MIT，JUnit XML 消费事实标准）以
  `owner/repo@<SHA>` 锁定；SHA 用
  `gh api repos/dorny/test-reporter/git/ref/tags/<tag>` 解析并核验对应
  tag，workflow 注释记 `# vX.Y.Z = <SHA>`。
- 升级只走 CHANGELOG 记账，锁只升不降。
- 该 Action 运行时自带打包，无新增 pip 依赖。

### 验收

一次 PR 触发 CI 后，PR 页面出现 test-reporter 发布的检查结果
（测试摘要/评论）= 首个外部 reporter 实吃。README 已知遗留 M-4 条目
改写为"已闭合"，CHANGELOG 记 F-162（实施时以 HEAD 实际下一号为准）。

## 第 2 节 L-4：step_flash 接入 N-3 构造性标记（决策：方案 A，共享判据模块）

### 改动

1. `openocd_run.py`：`_ACTION_DONE_CMD`、`ACTION_DONE_MARKER` 与
   "rc=0 且标记缺席 → action_incomplete" 判定抽为模块级可导入共享件
   （常量 + `check_action_marker(combined_output) -> bool` 一类纯函数；
   openocd_run 自身行为零变更）。
2. `verify.py:step_flash`：
   - openocd `-c` 串尾追加同一条标记 echo 命令；
   - `run_cmd` 返回 rc==0 后过共享校验器：标记缺席 →
     `{"status": "error", "message": "... action_incomplete ..."}`；
     rc≠0 维持既有 error 路径优先。
   - 不引入 hw_lease 调用（锁由 verify main 上游持有）。
3. 测试（host 层，`tests/test_verify_failure_paths.py` 扩或新钉文件）：
   - rc=0 + 标记在场 → ok；
   - rc=0 + 标记缺席 → error（action_incomplete 措辞钉）；
   - rc≠0 → 旧 error 路径不变；
   - 现有 step_flash 两例（空 hex / 文件不存在）保持绿。

### 行为风险声明

高频真机路径判定收紧：理论上"OpenOCD rc=0 但 program 串未跑完"从静默
放行变报错。这是 N-3 立法原意（克隆 ST-Link 半截成功场景前移拦截），
不是回归。

### 验收

1. host：全量 unittest 绿 + ruff 门禁过 + coverage 棘轮不降。
2. 真机（按 [[verify-with-real-project]] 规矩）：adc-oled 板在位跑一次
   完整 `verify`，flash 步骤带标记仍 PASS、`evidence=hardware_validated`。
3. 常态化通道：`hw-smoke.yml`（workflow_dispatch + HW_RUNNER_READY）后续
   真机冒烟自动覆盖本路径，不新增通道。
4. README 已知遗留 L-4 条目改写为"已闭合"，CHANGELOG 记 F-163
   （实施时以 HEAD 实际下一号为准）。

## 提交与版本纪律

- 全部提交在 0912 分支，不 push（Executor 不 push 惯例）；F 号在
  CHANGELOG 连续记账。
- spec 本身作为首个 commit 入档（`docs(F-16x-pre): M-4/L-4 小工单设计`）。
- 销账后记忆账本 `embedded-toolkit-ticket-2026-09-13` 的遗留清单同步
  勾销两条。
