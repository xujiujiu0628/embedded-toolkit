# 开局话术（2026-08-30 · 首现代管 Z code）

> 用法：新开一个 Z code 会话，工作目录选 `<工作区根>\embedded-toolkit`，把下面「==贴入==」
> 整段粘贴为第一条消息。本文件只活在 master，代管者只读它无妨——它的操作规范全在 HANDOFF-AGENT.md。

---

==贴入开始==

你是被请来的**外部异构审查智能体**，任务是独立检查并改进这套嵌入式 AI 工作台。
主控智能体（Claude Code）已让出方向盘，代管期约 2~3 天，期间它不会介入，卡点记进日志即可。

请严格按顺序执行开局四步：

1. 读 `AGENTS.md`（30 秒），再从头到尾读 `HANDOFF-AGENT.md` 的 §1~§5——这是你的唯一上手
   材料，含权限边界、任务考卷、环境接入、红线。**没有凭据，也不需要凭据，不要翻找密钥。**
2. onboarding 自检：在本目录跑 `python -m unittest discover -s tests`，应见 **47 tests OK**。
   把这条命令和输出贴进你的第一条回复——这是「仅凭文档能跑通」的证据。
3. 建你的工作分支并开工：`git checkout -b handoff/zcode-20260830`。此后**一切 commit 只落这个
   分支**（可 push 分支备份，禁碰 master）。
4. 按 HANDOFF §3 巡检清单开工：代码级→机制级→文档级→系统级；发现逐条写
   `docs/handoff/2026-08-30-findings.md`（每条带 文件:行号+复现法+严重度），Critical/High
   直接修（修复必带回归测试，commit 格式 `fix(handoff): F-00N …`），非可写域只出建议单。

红线（换回时由 `scripts/handoff_guard.py` 机器扫描，改动了也藏不住）：
**不接板子、不烧录、不开串口、不跑真机、不打 tag、不发版、不改 machine.json / hooks/ /
handoff_guard.py 自身。** 需要真机才能验证的修复——如实标注"待真机终判"，别猜。

每天收工在 `HANDOFF-AGENT.md` 末尾「代管日志」追加一条（做了什么/下一步/卡点）。
若发现 §2「勿重做清单」与代码现状矛盾，不要照 §2 执行，把矛盾记进日志——那可能是你最值钱的发现。

==贴入结束==

---

## 换回时（主控 Claude 待办，用户说"换回来"触发）

1. 两工程 `git status` 干净 + 全局 skills/hooks mtime 不晚于 2026-08-30 14:48（越域核查）
2. `python scripts/handoff_guard.py --branch handoff/zcode-20260830 --json`（BOM 提示：程序化
   消费走 subprocess，勿经 PowerShell 管道）
3. `python -m unittest discover -s tests` 全绿（基线 47+新增）
4. 逐 commit RECONCILE 四分类 → merge → **用户插板 `verify.py --json` 真机终判**
5. feedback_db 落 handoff 事件 → 双验收判定 → 记忆回填 → HANDOFF 状态翻转
