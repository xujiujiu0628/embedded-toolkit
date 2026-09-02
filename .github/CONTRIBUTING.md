# 贡献指南

## 环境准备

- **Python 3.10+**（verify/hardfault/feedback_db 等使用 PEP 604 联合类型语法）
- 克隆后**无需任何配置**即可跑测试与离线工具（`load_machine` 会回退到
  `machine.example.json` 并提示）
- 真机构建/烧录/采集前：复制 `machine.example.json` 为 `machine.json`，
  填入本机 arm-none-eabi-gcc / make / OpenOCD 绝对路径
  （**machine.json 是本机文件，已在 .gitignore，勿提交**）
- 可选：`pip install -r requirements.txt`（仅 `serial_*` 串口工具族需要 pyserial）

## 平台支持现状

- **Windows 为主要开发/真机平台**（gcc_build 预检按 `arm-none-eabi-gcc.exe`
  探测；控制台 GBK 编码有专门处理）
- ubuntu 上回归套件与离线工具全量可跑（CI 即证）；Linux 真机构建路径未验证，
  欢迎带报告的 PR 补这一格

## 测试与 PR 纪律

- 提交前：`python -m unittest discover -s tests` 全绿（例数以实跑为准，勿在
  文档写死数字）
- **修 bug 必带回归测试**——本仓传统：没有复现测试的修复不算修完
  （两轮外部审查反复兑现了这条）
- **没见过红的测试不算测试**（先红后绿，建仓 fix commit 一贯执行，F-035 成文）：
  新增回归测试的 commit 须能演示 临时回退修复→测试转红→还原→转绿；
  钉类（静态扫描）测试同样要求变异验证一次
- 注释可追溯：引用事故/裁决历史的注释必须带 F 编号或日期（如
  "修复 2026-08-12"）；注释解释 why，过程史交给 `git log` 与 CHANGELOG 回放
- commit 规约：`type(scope): 中文描述`（feat/fix/refactor/docs/test/chore/ci），
  一次改动 = 一个可辩护的理由；禁止顺手重构与无关格式化
- 涉及 `verify.py` / `release.py` 的改动必须同 commit 携带 `tests/` 伴随改动

## 分层与复用（import 方向是契约）

依赖方向固定单向，下层禁知上层：

```
Layer 0    wb_common.py          路径解析/机器配置/版本契约 —— 不 import 项目内任何模块
Layer 0.5  runtime_common.py     状态/配置/JSON 契约/结果构造 —— 只许 import Layer 0（防环，docstring 自述）
Layer 1    wb_runtime / openocd_runtime / serial_runtime
                                 再导出 + 薄壳 + 真分叉留份 —— 只许 import Layer 0/0.5
Layer 2    其余工具脚本           只许 import ≤Layer 1，禁被下层 import
Layer L    scripts/legacy/**     冻结区：不再新增，禁 import runtime_common
```

三条可机检禁令（违者拒收）：

1. Layer 0 / 0.5 / 1 import 任何 Layer 2 脚本——防依赖倒置；
2. 生产脚本 `import verify`——verify.py 现有模块级副作用（import 期读
   machine.json），`tests/` 4 例历史豁免待副作用清除后收编，本禁令防其扩散；
3. `scripts/legacy/**` 新增 `runtime_common` import——防退役区越活越大。

**"脚本自含"惯例自 F-029 起退役**（根因实证：三 runtime 曾按此惯例各存一份
同源实现，22 个同名符号皆由该惯例而生，其 docstring 自述见
`runtime_common.py` 头）。新脚本一律 `import` `wb_common` / `runtime_common`
（及所属族 runtime），禁止把 `save_json_file` / `make_result` /
`output_json` / `resolve_param` 等已有符号复制进脚本体。确有理由走独立
实现的（真分叉），必须在定义处 docstring 写明留份理由，统一模板：
`独立契约：<差异一句话>——见 F-029 裁决，勿"统一"`（防未来顺手统一）。

新代码落层决策表：

| 要写的东西 | 落点 | 反例 |
|---|---|---|
| 多脚本共用的状态/JSON/参数链 | `runtime_common` | 复制进新脚本 |
| 单族专用 helper | 所属族 runtime（如 `serial_runtime`） | 塞进 `runtime_common`（族无关层不知族细节） |
| 新独立工具 CLI | `scripts/<名>.py`，import 下层 | 复制一份自含 runtime |
| 只服务 verify 的一步 | 拆出后入拆分件；未拆前可暂入 verify.py 主体 | 永远堆向主体 |

## 行为保持型重构：先钉后拆

拆大文件（典型：verify.py）、合并同源实现，按三步执行（F-029 六 Task 是
完整模板，实证零破绽）：

1. **先钉**：为现行为落特征测试（对 wire 形态逐字节断言，宁多勿漏），
   全绿才动手术；
2. **后拆**：每次 commit 只搬一族符号，钉全程保持全绿；
3. **留份裁决**：同名异形不强行统一——docstring 写明差异理由（模板见上节），
   并落测试钉防未来"顺手统一"。

禁止 重构 + 行为变更 同 commit；行为变更另行成 commit，自带可辩护理由。

## 契约变更三件套

各工具 JSON 输出结构与 `.workbench/` schema（config.json /
expectations.json / machine.example.json 四键结构）是本仓公共 API。改动
其中任何结构，同一 PR 内完成三件事：

1. 同 commit 改/加契约钉（`test_runtime_contract` 一类字节级断言）；
2. CHANGELOG 记**契约变更**段——不当普通账目，外部消费方按它找破坏点；
3. 评估是否上调 `toolkit_min_version`（工程侧兼容闸门已存在，别让它空转）。

## 文档同步（单一事实源）

F-034 的教训：同一事实存在两个权威副本必然漂移。规则：

- **状态类事实**（遗留项是否闭合）以 CHANGELOG 为唯一权威；README 路线图
  只登记未闭合项、链接不复制处置细节；
- **历史实录不可变**：README 中标注"真实可回放"的输出段是工件，版本号/
  哈希/数值永不随手更新；要反映新版本须真实重跑后整段替换，旧段留注
  （F-034 保留加注即示范）；
- 例数/时长类以实跑为准，文档指向命令不写死数字（本仓已有），
  状态/进度类事实同此理；
- 新事实落笔前先认归属：状态→CHANGELOG / 结构→README / 治理史→
  `docs/handoff/` / 纪律→本文件。

## 禁区

- `hooks/`（固件工程侧三条 C 代码铁律的机器检查）、`scripts/handoff_guard.py`
  （代管禁线判据本体）——改动需在 issue 中单独论证
- `machine.json` 不入库；`machine.example.json` 的四键结构是契约
  （消费方按下标取键）

## 判据方法论（历史教训浓缩）

- 写回型工具的**默认参数路径**必须有测试（显式传参的主干无恙≠安全）
- 版式/查找类判据拿**真实档案冒烟**，勿只喂理想样本
- "文件不存在所以没发生"之前，先核对**自己看到的树是否正确**
  （`git merge-base` / `git ls-files`）

完整治理史见 `docs/handoff/`（两轮外部异构智能体代管的发现报告与对账记录）。
