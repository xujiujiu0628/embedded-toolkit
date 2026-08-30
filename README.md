# embedded-toolkit

> **外部智能体代管请先读 [`HANDOFF-AGENT.md`](HANDOFF-AGENT.md)**（权限边界/巡检任务/换回协议）。

嵌入式 AI 工作台全局工具库。固件工程通过 `.workbench/config.json` 被脚本发现（cwd 向上查找）。

- `scripts/` 工具脚本（verify.py 闭环验证入口；默认构建后端 GCC）
- `scripts/legacy/keil/` AI↔Keil 自动化桥（**已退役留门区**，见该目录 README）
- `data/` 通用知识库（stm32f103-ref.json / keil-error-db.json 跨工程共享）
- `hooks/` 通用铁律检查（工程特定 hook 留在工程 .claude/hooks/）
- `machine.json` 本机工具链绝对路径（唯一合法硬编码处；uv4_exe 仅供 legacy 桥）

> **2026-08-28 Keil 退役定案**：AI 工作台链路 100% GCC 默认（新工程 verify 不再依赖
> `builder` 显式配置）；Keil 软件保留供非 AI 项目手工使用，AI 侧桥脚本移入
> `scripts/legacy/keil/`，工程 config 显式 `"builder": "keil"` 即可按需唤起。
> 注意：`error_db_grow.py` / `keil-error-db.json`（双工具链共用错误库）与
> `cube_to_keil.py`（CubeMX USER CODE 备份/恢复工具，**与 Keil 无关**，GCC 工程通用）
> 均在主干，不属退役范围。

## 期望清单与发布门禁 (2026-08-26)

- 工程存在 `.workbench/expectations.json` → verify 走清单四态判定
  ([PASS]/[XFAIL]/[XPASS]/[FAIL]，XPASS 判红强制翻转)；不存在 → 回退
  config.json `verify.expect*` legacy 行为，老工程零影响。
- 规则：id 唯一必填；texts/patterns 二选一（数组内全命中）；xfail:true 必须
  xfail_reason；可选 capture_group+min/max 数值断言。
- 新旗标：`--rebuild`（clean 后重建，仅 gcc 后端）、`--gate-run`（门禁发起，
  不落 feedback 库）。
- 发布：`python scripts/release.py --tag vX.Y.Z [--dry-run] [--allow-xfail]`
  — clean rebuild 全绿才打 annotated tag，记录落 `.workbench/releases/<tag>.json`。
- `.workbench/` 版控策略：config.json / expectations.json / releases/ 入库；
  build/ 与 state.json 忽略。
