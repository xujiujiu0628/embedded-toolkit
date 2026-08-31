# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

## 0.2 — 2026-08-30（代管 R2，分支 handoff/zcode-r2-20260830）

- **F-018**（原报告编号 F-015，换回对账重排，见
  `docs/handoff/2026-08-31-r2-reconcile-notes.md`）发布记录绑定契约哈希: verify 输出 `contract_hashes`
  （config/expectations 字节级 sha256），release 写入发布记录，
  release_audit 新增 **R7**（对照 `git show <git_head>:` 重算比对，
  错位=fail，R7 之前旧记录=warn）——关闭"G1 期间改契约再还原"的取证盲区
  （34a96e5）。
- **F-019/F-020**（原报告编号 F-016/F-017，换回对账重排）写回型工具损坏清空家族修复（三份 runtime 拷贝同修）:
  `save_project_config` 损坏**拒绝写回**；`update_state_entry` /
  serial_mux 读改写损坏**隔离 .corrupt 后重建**；`save_json_file` 改
  **原子写**（.tmp + os.replace，杜绝并发撕裂读）；error_db_grow 知识库
  损坏明确拒绝写入；gcc_build config 写回抽 `merge_gcc_config`
  （351e021）。
- 新工具 **expectations_lint.py**（D 项）: verify.load_expectations 规则
  离线化 E1~E9，含 verify 不查的 E9 `min>max` 结构矛盾；两现役工程真档
  冒烟 CLEAN（10507bd）。
- **C 项** 零覆盖模块补测 21 例: phase_minus_one / rm_lookup /
  token_stats / svd_to_json（cc54e45）。
- 文档对齐: 本 CHANGELOG 新建；AGENTS.md / HANDOFF-AGENT.md 过期计数
  （47 测试/28 脚本）改为动态表述；HANDOFF-AGENT.md §2 补 #10/#11
  防重报条目。

## 0.1.x — 2026-08-30（代管 R1，分支 handoff/zcode-20260830）

- **F-001**（Critical）feedback_db 首次落账死锁——button-toggle 建成以来
  反馈零落账（4866fb5）。
- **F-002** config 容错 / **F-003** 采集超时诚实化（部分输出回收+失败
  现场落盘，待真机终判）/ **F-004** 落账三态留痕 / **F-005** hardfault
  默认 map 自动发现（1baeed2、11eb319）。
- **F-014** 校准库损坏容错（.corrupt 隔离 + 空库重建）（afc7265）。
- **F-006/007/008/012** Low 清理组；F-009/010/011/013 记录不修（fa5efb4）。
- 新工具 **release_audit.py**（M-3）: 发布记录事后审计 R1~R6（eb1e4c9）。
