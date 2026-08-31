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
- commit 规约：`type(scope): 中文描述`（feat/fix/refactor/docs/test/chore/ci），
  一次改动 = 一个可辩护的理由；禁止顺手重构与无关格式化
- 涉及 `verify.py` / `release.py` 的改动必须同 commit 携带 `tests/` 伴随改动

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
