<!-- 一次 PR = 一个可辩护的理由；禁止顺手重构与无关格式化（见 CONTRIBUTING）。 -->

## 描述与动机

<!-- 这个 PR 改了什么、为什么改。背景多写一层永远比少写一层好。 -->

## 关联 Issue

Closes #(没有关联 issue 请写 `无`，并说明理由)

## 改动类型

- [ ] feat（新工具/新能力）
- [ ] fix（缺陷修复）
- [ ] docs / test / refactor / chore / ci

## 测试证据（必填）

- [ ] `python -m unittest discover -s tests` 本地全绿，并在下方粘贴尾部统计行
- [ ] 修 bug 必带回归测试（本仓传统：没有复现测试的修复不算修完）
- [ ] 涉及 `verify.py` / `release.py` 的改动，同 commit 携带 `tests/` 伴随改动
- [ ] 涉及期望契约的改动，跑过 `python scripts/expectations_lint.py --project <工程根>`

```text
粘贴测试输出尾部，例如: Ran 181 tests in 12.3s / OK
```

## fresh-checker 复审门禁（F-035 流程必走，F-069c 起强制）

PR 在合并前**必须**经 fresh-checker 复审 (派无上下文审计 agent, 跑实测取证
+ 分级发现, 详见 `~/.claude/skills/fresh-checker/SKILL.md`)。

- [ ] 已派 fresh-checker 审计, 报告已附在本 PR 评论或关联 issue 中
- [ ] 报告中 Critical/High 数量: C:___ H:___ M:___ L:___
- [ ] Critical/High 已修完, 或已在评审中显式说明接受风险 (含理由)
- [ ] **如选择「维护者直合豁免」** (CONTRIBUTING.md §"F-035 流程例外条款"):
  在下方「例外理由」段说明, 并勾选此框: [ ]

> 例外理由 (不超过 200 字, 说明为什么本 PR 跳过 fresh-checker):

## 检查清单

- [ ] commit 符合 `type(scope): 中文描述` 规约
- [ ] 未混入 `machine.json`、个人绝对路径或用户名（diff 自查一遍）
- [ ] 行为变更已同步 `CHANGELOG.md` / `VERSION`（或在此说明为何不需要）
- [ ] 涉及 schema / 工具 JSON 输出结构变更（公共 API）的，契约三件套已齐：
      ① 同 commit 契约钉 ② CHANGELOG 契约变更段 ③ `toolkit_min_version` 已评估
      （不适用请勾选并注明；细则见 CONTRIBUTING「契约变更三件套」）
- [ ] 未触碰禁区（`hooks/`、`scripts/handoff_guard.py`），或已在关联 issue 中单独论证
- [ ] **commit 署名符合 9-02 拍板 push 规则** (`xujiujiu0628` 用户主名, 详见
      `~/.claude/projects/D--claude/memory/push-user-identity-rule.md`)
- [ ] commit message 的 `Co-Authored-By` trailer 是否包含 Claude Code:
      如含, 在下方说明是否违反 push 规则 (默认应不含, 9-01 历史重写成本即消 AI 痕迹)

## 破坏性变更

<!-- 若有：列出对 .workbench/config.json、expectations.json、machine.example.json
四键结构等公共契约的影响与迁移路径。没有就写"无"。 -->
