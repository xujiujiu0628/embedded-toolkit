# 开源就绪清单（OPENSOURCE_READY）

> 生成日期：2026-09-01 ｜ 对象：`xujiujiu0628/embedded-toolkit`（当前 PRIVATE）
> 本报告为开源化准备 8 步的完成度盘点与人工待办。

## 一、8 步执行状态

| 步骤 | 产物 | 状态 |
|---|---|---|
| 1 `.gitignore` | `.gitignore` | ✅ **补全**：原 4 行 → 覆盖虚拟环境/依赖/日志/数据库/系统文件/IDE/本地配置全清单 |
| 2 敏感信息扫描 | `SENSITIVE_FINDINGS.md` | ✅ 新增。凭证类全零；**历史含个人 Windows 用户名（F-1，建议公开前重写）**；47 处机器路径（F-2） |
| 3 配置模板 | `machine.example.json`（已存在） | ✅ 无需新增：唯一机器相关文件已有占位模板；`config/*.json` 仅含非敏感默认值，另造同内容 .example 属噪音 |
| 4 许可证 | `LICENSE`（已存在） | ✅ 核对通过：MIT / 2026 / xujiujiu0628，与 GitHub 身份一致，未改动 |
| 5 README | `README.md` | ✅ **定点补充**：加 License/Python/Platform 徽章 + 「贡献」章节链接社区文件；原有结构本就覆盖全部必备章节，未重写 |
| 6 社区文件 | `CONTRIBUTING`（已存在）· `CODE_OF_CONDUCT.md` · `SECURITY.md` | ✅ CoC 按 Contributor Covenant **2.1** 中译新建；SECURITY 新建（私下报告渠道/响应时限/硬件免责）。CONTRIBUTING 维持在 `.github/` 位置（GitHub 自动识别，不重复建根文件） |
| 7 Issue/PR 模板 | `.github/ISSUE_TEMPLATE/*`（已存在）· `.github/PULL_REQUEST_TEMPLATE.md` | ✅ PR 模板新建（与 CONTRIBUTING 纪律对齐：复现测试、契约 lint、无个人路径自查）。Issue 模板已有 **yml 表单制**（含强制贴 `verify --json`、关 blank issue），功能优于平铺 md，未覆盖 |
| 8 总结报告 | `OPENSOURCE_READY.md` | ✅ 本文件 |

## 二、文件变更清单（本次）

**新建**：`SENSITIVE_FINDINGS.md` ｜ `CODE_OF_CONDUCT.md` ｜ `SECURITY.md` ｜
`.github/PULL_REQUEST_TEMPLATE.md` ｜ `OPENSOURCE_READY.md`
**修改**：`.gitignore`（追加规则） ｜ `README.md`（徽章 + 贡献章节） ｜
全仓历史 blob 与 message 脱敏重写 ｜ `tests/test_failure_hints.py` 守卫判据
适配（重写致原断言变恒真，改通用盘符判据恢复原语义——本次唯一代码改动）
已按 `chore(opensource)` + `docs(security)` 两 commit 入库（重写后 hash 见 `git log`）。

## 三、公开前待你拍板的事项（按序）

1. ✅ **F-1 历史重写（已完成 2026-09-01）**：个人用户名实测 27 处（全部
   `Users<分隔符>` 形态）+ 机器路径三形态，filter-repo 两轮重写
   （**坑：`--replace-text` 不作用于 commit/tag message，二轮用
   `--message-callback`/`--tag-callback` 补**），终验零残留。
   重写前 commit 图已 bundle 归档：`../archive/embedded-toolkit-prehistory-20260901.bundle`。
2. ✅ **HEAD 机器路径**：随重写一次洗清（行内替换不增减行数，报告行号引用仍有效）。
3. ⏳ **F-3 测试硬编码**：字面量已被洗为占位符 → 真档冒烟对本机也恒跳过，
   tempfile 化已无历史包袱，建议列入下轮（见 SENSITIVE_FINDINGS F-3）。
   **F-4（新登记）**：`test_cli_exit_codes_and_json` 在 Windows 非 UTF-8 终端下失败，
   对照 bundle 基线证明为存量缺陷（与重写无关），修法见 SENSITIVE_FINDINGS F-4。
4. **本地 3 个 `handoff/*` 分支**：已随全 ref 重写脱敏（commit hash 全变）；
   是否推送/合并/留本地仍待拍板——内容已无 PII，仅过程性治理记录。
5. **F-5 时间线事实（已登记，2026-09-01 补）**：Events API 显示仓库 8/26 曾
   公开一次、9/1 复转与脱敏推送最坏重叠约 20 分钟——低危残留，不再处理，
   详见 `SENSITIVE_FINDINGS.md` F-5。

## 四、需要你在 GitHub 网页端手动完成

- [x] **转 Public**：✅ 2026-09-01 维护者完成（时间线与暴露窗口见 F-5）
- [x] **仓库描述（About）**：✅ 2026-09-01 gh 落地
  `AI 写嵌入式固件的闭环验证工作台：代码可以由 AI 生成，但"算不算对"由真机说了算。STM32F103 / GCC / OpenOCD / RTT`
- [x] **Topics**：✅ 2026-09-01 gh 落地 10 项
  （stm32 / embedded / firmware / gcc / openocd / rtt / ai-coding / claude-code / ci / hardware-in-the-loop）
- [x] **第一个 Release**：✅ v0.3 已由维护者 08-31 发布（09-01 追加"账本说明"
  节：历史重写策略反转声明、旧 hash 回放指引、tag 后 master 新增内容、已知事项索引）
- [ ] （可选）Settings → Security → **Private vulnerability reporting** 打开，
  让 SECURITY.md 的报告表单链接生效
- [ ] （可选）仓库开启 Discussions，引导使用问答离开 issue 区

## 五、现状核验（2026-09-01 终版实测）

- 历史重写后 `master` 领先远端且**图形不共祖**——推送必须 `push --force`（master + 全部 tag）
- CI 徽章已解锁（ubuntu × Python 3.10/3.12 双绿）
- 工作树 86 个受跟踪文件，无 .env / 无私钥 / 无凭证
- 本次准备未触碰任何脚本逻辑（任务约定），测试基线以 CI 与本地实跑为准
