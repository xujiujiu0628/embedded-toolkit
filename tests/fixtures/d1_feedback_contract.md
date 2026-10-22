# D1 双字段契约（feedback-log skill 契约的仓内锚）

落库事件同时记两个独立维度，不是二选一：

- `"verify_result"`：**验证结果**，取值 `"pass"` / `"fail"`——这一次验证过没过。
- `"outcome"`：**修复归宿**，取值 `"fixed"` / `"still_broken"` /
  `"false_positive"`——这一次修复处置成什么样。

因此一次「验证通过 + 修复成功」的完整记录是：

    "verify_result": "pass", "outcome": "fixed"

`pass` / `fail` 可以不参与校准（`update_calibration` 只认三个归宿类取值），
但不得因此把两个字段合并成一个。

> 本文件是 2026-10-22 **F-229** 引入的仓内契约锚（三号复审 L-3）：原钉读
> `~/.claude/skills/feedback-log/SKILL.md`，CI/干净克隆上该路径不存在 →
> 永久 skip，等于没钉。判据载体改到仓内后，门禁才有咬合面。
