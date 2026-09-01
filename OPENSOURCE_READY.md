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
**修改**：`.gitignore`（追加规则） ｜ `README.md`（徽章 + 贡献章节）
以上改动**尚未 commit**（工作树待处理），建议拆分：

```bash
git add .gitignore README.md CODE_OF_CONDUCT.md SECURITY.md .github/PULL_REQUEST_TEMPLATE.md
git commit -m "chore(opensource): 社区文件补全 — CoC2.1/SECURITY/PR 模板 + gitignore 全清单 + README 徽章与贡献入口"
git add SENSITIVE_FINDINGS.md OPENSOURCE_READY.md
git commit -m "docs(security): 敏感信息扫描报告与开源就绪清单"
```

## 三、公开前待你拍板的事项（按序）

1. **F-1 历史重写**：Windows 个人用户名残留 git 历史约 22 处（HEAD 已中性化）。
   处置方案见 `SENSITIVE_FINDINGS.md`。**一旦公开再改，旧历史已被爬取即不可逆。**
   ✅ **2026-09-01 维护者已拍板执行**（filter-repo 定向替换 + 机器路径映射，
   全历史重写后 force push；重写前 commit 图已 bundle 归档）。
2. ~~HEAD 的 47 处机器路径是否替换~~ ✅ 随重写一并处理：filter-repo 规则同时
   映射 `盘符:\claude` 与 `<工作区根>` 两形态 → `<工作区根>`，HEAD 与历史一次洗清。
3. **F-3 测试硬编码**：`tests/test_expectations_lint.py:18` 维持现状还是改 tempfile。
4. **本地 3 个 `handoff/*` 分支**：是否推送/合并/留本地（内容含同类路径信息）。

## 四、需要你在 GitHub 网页端手动完成

- [ ] 完成上述 F-1 处置并推送后：**Settings → Danger Zone → Change visibility → Public**
- [ ] **仓库描述（About）**：建议
  `AI 写嵌入式固件的闭环验证工作台：代码可以由 AI 生成，但"算不算对"由真机说了算。STM32F103 / GCC / OpenOCD / RTT`
- [ ] **Topics**：`stm32` `embedded` `firmware` `gcc` `openocd` `rtt` `ai-coding`
  `claude-code` `ci` `hardware-in-the-loop`
- [ ] **发布第一个 Release**：按 VERSION 如实取 **`v0.3`**（任务模板写 v1.0.0，
  但本仓 VERSION=0.3、CHANGELOG 0.3 节证据齐全——建议版本号与账本一致，
  v1.0.0 留给真机全链路跨平台验证后）；正文可从 CHANGELOG 0.3 节复制
- [ ] （可选）Settings → Security → **Private vulnerability reporting** 打开，
  让 SECURITY.md 的报告表单链接生效
- [ ] （可选）仓库开启 Discussions，引导使用问答离开 issue 区

## 五、现状核验（写本报告时实测）

- `master` 与 `origin/master` 同步于 `f12b5b3`（无未推送 commit；**本次新文件除外**）
- CI 徽章已解锁（ubuntu × Python 3.10/3.12 双绿）
- 工作树 86 个受跟踪文件，无 .env / 无私钥 / 无凭证
- 本次准备未触碰任何脚本逻辑（任务约定），测试基线以 CI 与本地实跑为准
