# F-029 三 runtime 契约统一与去重 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 wb_runtime / openocd_runtime / serial_runtime 三份同源分叉的公共符号收敛为单一事实源 `scripts/runtime_common.py`，在**不改任何工具 JSON 输出（wire 兼容）**的前提下净删 ≈300+ 行重复。

**Architecture:** 新建 `runtime_common.py` 作为共享层（wb_runtime 已 import wb_common，同目录共分发，无自含性约束破坏）；三 runtime 逐符号改为 `from runtime_common import X` 再导出，保持 `mod.X` 可解析（test_writeback_guards 的 `RUNTIMES=[wb, ocd, ser]` 参数化因此全程免改）。真分叉符号不强行合并（实测修正：serial `make_result` 只是**入参签名**分叉、输出同为 status 族→薄适配器收编；`parameter_context`/`make_timing` 才是**同名异物**→保本地+docstring 钉）；配置读写族以参数注入路径策略；`update_state_entry` 以 hook 参数注入 wb 的序列化机制。

**Tech Stack:** Python ≥3.10（`str | None` 语法在用）、unittest、无新增第三方依赖。

> **实施记录（2026-09-02，代管整车）**: 6 Task 全部完成，215 全绿。相对本计划登记期
> 分桶的三处订正（特征钉 T1 阶段按现实重钉）: ① 状态读写族非"纯 docstring 差"——
> **wb==serial 序列化 / ocd 原样**是真语义分叉，Task 4 表述"无 hook=ocd/serial 现状"
> 有误（serial 也走序列化钩子）；② serial `normalize_path` 非超集（相对输入不 resolve）
> → 裁决留本地；③ Task 5"缺失者补守卫"经实测撤销（环境级整写不读旧档，无风险）。
> `resolve_param` 终判=三份整组留份（源标签/层级/锚定/异常策略均不同形）。
> 净账：同形重复行浪费 195→4。处置全录见 CHANGELOG「F-029 处置」。

## 前期侦察结论（2026-09-01，AST 两两比对实测）

22 个三处同名符号 + wb/ocd 私有共享 5 个（`build_artifacts` `compact_dict` `default_config_path` `get_state_entry` `hidden_subprocess_kwargs`），分桶：

| 桶 | 符号 | 处置 |
|---|---|---|
| ALL3 字节同 (5) | `_first_resolved` `is_missing` `load_json_strict` `now_iso` `workspace_root` | 原样上提 |
| 仅 docstring/换行差 (7) | `load_json_file` `save_json_file` `JSONCorruptError` `load_workspace_state` `load_workspace_state_for_update` `output_json` `save_workspace_state` | 语义同→上提（取最详 docstring 版）；serial 的 `save_workspace_state` 亦仅 docstring 差 |
| wb=ocd 严格同、serial 分叉 (4) | `make_result` `make_timing` `parameter_context` `normalize_path` +（wb/ocd 私有助手随迁） | wb/ocd 上提。实测分叉性质不一：`make_result` serial 版**仅入参签名分叉**（`success: bool` 位置参），输出仍是 `status: "ok"/"error"` 同形 → serial 侧可收成薄适配器（签名冻结、体内转调规范版）；`make_timing`/`parameter_context` 是**同名异物**（ser: `start_time`→现算耗时 / `name,value,source` 三元组 vs wb: `started_at,elapsed_ms`→格式化 / provider context dict）→ serial 保本地 + docstring 钉"非漏改"；`normalize_path` 见 Task 3 裁决步骤 |
| 路径策略真分叉 (4) | `load_local_config` `save_local_config` `load_project_config` `save_project_config` | 上提为骨架 + `config_file_resolver` 参数注入 |
| 机制真分叉 (2) | `update_state_entry`（wb 多 `_serialize_state_value`） `resolve_param`（34-42r 三份各不同） | update 族 hook 化；resolve_param **调查后判**：可参数化则收，语义真不同则显式留份并销账 |

消费者地图（wire 冻结依据）：serial_* 六工具→serial_runtime；openocd_* 五工具→openocd_runtime；gcc_build→wb_runtime。测试引用形态为 `mod.save_json_file(...)`，再导出即兼容。

## Global Constraints

- **调用面字节兼容**：任何工具的 `--json` 输出结构不变（Task 1 特征钉锁死）；serial `make_result` 的 `success: bool` **入参签名**冻结，其输出实测本就是 `status` 族（非 wire 分叉）。
- 每 Task 结束跑 `python -m unittest discover -s tests` 全绿才 commit；commit message 带 F-029 与符号清单。
- 基线数字：Task 0 起 `Ran 192 OK (skipped=1)`（skipped 为 F-026 opt-in 活跳）。
- Windows-only 常量守 F-027/F-031 双钉惯用法。
- `runtime_common.py` 不 import 三 runtime 中任何一个（防环）；仅 stdlib。
- 上提符号取"最详 docstring + 最新守卫（F-019/020/021/023 记号）"版本为规范版。

---

### Task 1: 特征钉 — wire 契约与再导出面冻结

**Files:**
- Create: `tests/test_runtime_contract.py`

**Interfaces:**
- Consumes: 三 runtime 现状（未改）
- Produces: `RUNTIMES`、`wire_shape(obj)` 工具函数，后续所有 Task 靠它证明"搬完输出不变"

- [x] **Step 1: 写特征钉测试**（这些测试在改代码前就该全绿——它们是安全网，不是红测试）

```python
"""F-029 前置特征钉: 三 runtime 的 wire 契约在去重全程必须字节不变。

侦察结论 (2026-09-01 实测): serial make_result 入参 success:bool / 输出仍
status 族 —— 签名冻结、输出可并轨; parameter_context/make_timing 是同名异物。
再导出面 (mod.X 可解析) 是 test_writeback_guards RUNTIMES 参数化的前提, 一并钉。
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import wb_runtime, openocd_runtime, serial_runtime  # noqa: E402

RUNTIMES = [wb_runtime, openocd_runtime, serial_runtime]

# 去重后仍必须可从每个 mod 解析到的公共名 (再导出义务)
REEXPORT_NAMES = [
    "is_missing", "now_iso", "workspace_root", "load_json_file",
    "load_json_strict", "save_json_file", "JSONCorruptError",
    "load_workspace_state", "save_workspace_state",
    "load_workspace_state_for_update", "update_state_entry",
    "output_json", "normalize_path",
    "load_local_config", "save_local_config",
    "load_project_config", "save_project_config",
    "make_result", "make_timing", "parameter_context",
]


def wire_shape(obj):
    """递归取 JSON 结构形状: dict→{key: shape}, list→[shape], 标量→type name"""
    if isinstance(obj, dict):
        return {k: wire_shape(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [wire_shape(x) for x in obj[:1]]
    return type(obj).__name__


class ReexportSurfaceTests(unittest.TestCase):
    def test_all_public_names_resolvable(self):
        for mod in RUNTIMES:
            for name in REEXPORT_NAMES:
                with self.subTest(mod=mod.__name__, name=name):
                    self.assertTrue(callable(getattr(mod, name, None))
                                    or isinstance(getattr(mod, name, None), type),
                                    f"{mod.__name__}.{name} 必须保持可解析")


class WireContractTests(unittest.TestCase):
    def test_serial_make_result_input_frozen_output_status_family(self):
        # 实测 (2026-09-01): serial 版入参 success:bool, 输出 status 族且空键省略
        r = serial_runtime.make_result(success=True, action="scan", summary="ok")
        self.assertEqual(r, {"status": "ok", "action": "scan", "summary": "ok"})
        e = serial_runtime.make_result(success=False, action="a", summary="s",
                                       error={"code": "x"})
        self.assertEqual(e["status"], "error")
        self.assertEqual(set(e), {"status", "action", "summary", "error"})

    def test_wb_ocd_make_result_status_str(self):
        for mod in (wb_runtime, openocd_runtime):
            with self.subTest(mod=mod.__name__):
                r = mod.make_result(status="ok", action="run", summary="s")
                self.assertEqual(r["status"], "ok")
                self.assertNotIn("success", r)

    def test_serial_parameter_context_is_name_value_source(self):
        d = serial_runtime.parameter_context("port", "COM3", "cli")
        self.assertEqual(sorted(d), ["name", "source", "value"])

    def test_wb_ocd_parameter_context_is_provider_shape(self):
        for mod in (wb_runtime, openocd_runtime):
            with self.subTest(mod=mod.__name__):
                d = mod.parameter_context(provider="p", workspace=None)
                self.assertIn("provider", d)
                self.assertIn("workspace", d)
                self.assertNotIn("name", d)

    def test_make_timing_is_name_collision_not_dup(self):
        # 实测: ser.make_timing(start_time) 现算耗时; wb.make_timing(started_at,
        # elapsed_ms) 做格式化 —— 同名异物, 各自的钉分别锁形状
        # 注: start_time 用近期真实时间戳 —— epoch 秒 1000 在 Windows 上
        # astimezone() 直接 OSError (pre-epoch 边界, 计划编写时实测撞出)
        t_ser = serial_runtime.make_timing(start_time=time.time() - 1.0)
        self.assertEqual(set(t_ser), {"started_at", "finished_at", "elapsed_ms"})
        t_wb = wb_runtime.make_timing("2026-09-01T00:00:00+08:00", 123)
        self.assertIsInstance(t_wb, dict)
```

注：`make_timing`/`make_result` 的确切入参以**跑通为准**——写测试时先 `inspect.signature` 核一遍现状入参形态，若上面示例与现状签名冲突，按现状改写测试（特征钉的原则是"记录现实"，不是"我希望的形状"）。

- [x] **Step 2: 运行确认全绿**

Run: `python -m unittest tests.test_runtime_contract -v`
Expected: 全 OK（194 例左右：192 + 本文件若干）

- [x] **Step 3: 全量绿 + commit**

```bash
python -m unittest discover -s tests   # 192+ 全绿 skipped=1
git add tests/test_runtime_contract.py
git commit -m "test(F-029 前置): runtime wire 特征钉+再导出面冻结——serial success:bool 与 wb/ocd status:str 双契约字节级锁定, 去重全程不得变形"
```

---

### Task 2: 建 `runtime_common.py` — ALL3 五符号 + docstring-only 七符号上提

**Files:**
- Create: `scripts/runtime_common.py`
- Modify: `scripts/wb_runtime.py`（12 处 def → import）、`scripts/openocd_runtime.py`（12 处）、`scripts/serial_runtime.py`（12 处）
- Test: 既有全套（再导出面保护，不改测试）

**Interfaces:**
- Consumes: Task 1 的钉
- Produces: `runtime_common.{is_missing, now_iso, workspace_root, load_json_file, load_json_strict, JSONCorruptError, save_json_file, output_json, normalize_path}` 规范实现；三 runtime `from runtime_common import ...` 再导出

- [x] **Step 1: 建模块头 + 搬运 12 个符号**（`_first_resolved` 作为私有 helper 一并搬）

```python
"""runtime 共享层 (F-029): wb/openocd/serial 三 runtime 的单一事实源。

背景: 三 runtime 曾按"脚本自含"惯例各存一份同源实现, 实测 22 个同名符号中
12 个仅 docstring/换行差异 —— 本模块收编规范版, runtime 侧 import 再导出,
保持 `mod.X` 调用面不变 (test_writeback_guards 的 RUNTIMES 参数化直接受益)。
真分叉符号 (make_result 双契约 / 配置读写族 / resolve_param) 按 F-029 计划
Task 3-5 处理, 不强行合并。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
```

搬运顺序与来源（取"最详 docstring 版"为规范版，函数体逐字不改）：
`JSONCorruptError`(wb 版，docstring 全) → `is_missing` → `now_iso` → `workspace_root` → `_first_resolved` → `load_json_strict` → `load_json_file` → `save_json_file` → `output_json`(wb 版) → `normalize_path`(wb/ocd 版)。

注意：`save_json_file`/`output_json` 等若引用 `STATE_DIR_NAME` 之类模块常量，把常量参数化或随迁——先 grep `STATE_DIR_NAME` 确认引用链，有则在本模块声明同名常量由各 runtime 传值，**不引入 runtime 反向 import**。

- [x] **Step 2: 三 runtime 各删本地 def，改再导出**

每个 runtime 文件头加：

```python
from runtime_common import (  # noqa: F401  (再导出: 保持 mod.X 调用面, F-029)
    JSONCorruptError, _first_resolved, is_missing, load_json_file,
    load_json_strict, normalize_path, now_iso, output_json, save_json_file,
    workspace_root,
)
```

删除对应本地 def。serial 侧 `normalize_path` 是 8 行 wb 版 4 行的超集（多盘符归一逻辑）→ **serial 该符号暂留本地**，import 行不含 normalize_path，Task 3 一并裁决。

- [x] **Step 3: 红/绿验证 + 咬合抽检**

```bash
python -m unittest discover -s tests        # 全绿
python -m unittest tests.test_runtime_contract tests.test_writeback_guards -v
```
Expected: 全 OK。再抽一钉自证等价：`python -c "import sys; sys.path.insert(0,'scripts'); import runtime_common, wb_runtime; print(runtime_common.now_iso.__module__ == 'runtime_common')"` → True。

- [x] **Step 4: CHANGELOG 记一行进度 + commit**

```bash
git add -A
git commit -m "refactor(F-029 T2): runtime_common 建层——ALL3 五符号+docstring-only 族上提再导出, wire 面零变更"
```

---

### Task 3: wb↔ocd 结果构造族上提（make_result / make_timing / parameter_context + 5 私有 helper）

**Files:**
- Modify: `scripts/runtime_common.py`（追加）、`scripts/wb_runtime.py`、`scripts/openocd_runtime.py`
- Test: 既有 + Task 1 特征钉

**Interfaces:**
- Produces: `runtime_common.make_result(*, status, action, summary, details=None, context=None, ...)`（wb/ocd 现状签名逐字）、`make_timing`、`parameter_context`、`compact_dict`、`build_artifacts`、`get_state_entry`、`hidden_subprocess_kwargs`

- [x] **Step 1:** wb/ocd 两份逐字节相同的 `make_result`(30r)/`make_timing`(2r)/`parameter_context`(7r)/`compact_dict`/`build_artifacts`/`get_state_entry`/`hidden_subprocess_kwargs` 上提进 runtime_common（wb 版原文），wb/ocd 改再导出。
- [x] **Step 2:** `normalize_path` 裁决：diff wb(4r) vs serial(8r)——serial 若为功能超集（多一层 base 归一），把超集上提为 `normalize_path(path, base=None)`，wb 版退化为 `base=None` 默认行为；若语义不等价（返回值不同）则 serial 留本地 + docstring 声明。**先写一个两版行为对照测试再决定**，不许凭行数猜。
- [x] **Step 3:** serial 的 `make_result` 改**薄适配器**（入参签名逐字冻结——六个 serial 工具调用点零改动，体内转调规范版）：

```python
def make_result(success: bool = True, action: str = "", summary: str = "",
                details: dict | None = None, error: dict | None = None) -> dict:
    """serial 家族入口签名 (F-029): success:bool 位置参冻结不变, 输出 status 族
    转调 runtime_common 规范实现 — 空键省略行为由规范版 details if/error if 保证。"""
    return _common_make_result(
        status="ok" if success else "error", action=action, summary=summary,
        details=details, error=error)
```

（适配器落地前先跑 Task 1 特征钉确认输出等价；若规范版对空 details 的处理与 serial 现状不同——如总是带键——则以**特征钉为准**微调规范版条件键，不许迁就 wb 现状变形 serial 输出。）
- [x] **Step 3b:** serial 的 `parameter_context`/`make_timing` 保本地，docstring 首行加：`"""serial 家族独立契约 (F-029 裁决): 与 wb/ocd 同名异物 (入参/返回均不同形), 非漏改, 勿'统一'。"""`
- [x] **Step 4:** 全绿 + commit `refactor(F-029 T3): wb/ocd 结果构造族上提, serial 同名异物显式留份`

---

### Task 4: 状态读写族收口（state 三件套 + update_state_entry hook 化）

**Files:**
- Modify: `scripts/runtime_common.py`、三 runtime
- Test: `tests/test_writeback_guards.py` 的 UpdateStateEntry/LoadStateForUpdate 类是现成安全网

**Interfaces:**
- Produces: `runtime_common.update_state_entry(category, record, workspace=None, *, serialize=None)`（无 hook 时 = ocd/serial 现状行为；wb 传 `serialize=_serialize_state_value`）；`load_workspace_state`/`save_workspace_state`/`load_workspace_state_for_update` 上提（三份语义已实测同）

- [x] **Step 1:** state 三件套上提。`load_workspace_state_for_update` 的 wb↔ocd 差异已核实**纯 docstring**，取 wb 全文版。
- [x] **Step 2:** `update_state_entry` 先写行为对照测试钉住现状三分叉（wb 序列化 extra keys vs ocd/ser 原样存）→ 骨架上提 + hook 参数注入 → 对照测试仍绿即证等价。
- [x] **Step 3:** 全绿 + commit `refactor(F-029 T4): 状态读写族上提, update_state_entry 序列化 hook 化保 wb 行为`

---

### Task 5: 配置读写族裁决 + `resolve_param` 终判（本计划的硬决策位）

**Files:**
- Modify: `scripts/runtime_common.py`、三 runtime；可能 Modify: `docs/`（若裁决留份）

- [x] **Step 1: 配置四函数族**（`load/save_local_config`、`load/save_project_config`）。三分叉根源是**路径策略**（wb=多 skill 参数、ocd=script_file 反推、serial=SKILL_DIR 锚定）与 wb 新加的 F-020/021 守卫。上提骨架：

```python
def save_project_config_common(config_file: Path, values: dict, skill: str,
                               *, reject_corrupt: bool = True) -> "Path | None":
    """读改写族规范实现 (F-020/F-021 契约): 损坏拒绝写回返回 None"""
    if config_file.exists():
        try:
            data = load_json_strict(config_file)
        except JSONCorruptError as e:
            print(f"Warning: 拒绝写回 {config_file} 以免清空其他段, "
                  f"请手工修复后重试: {e}", file=sys.stderr)
            return None
    else:
        data = {}
    data[skill] = {**(data.get(skill, {})), **values}
    save_json_file(config_file, data)
    return config_file
```

各 runtime 的 `save_project_config(workspace=None, values=None, skill=...)` 变薄壳：算好自己的 `config_file` 后调用之。ocd/serial 现状**无** F-020 守卫的本地变体（其 F-020 版实现已同步存在——写测试核实各家现状守卫有无，缺失者**本次一并补齐守卫**并记入 CHANGELOG 行为变更：损坏时拒绝写回，属 fail-closed 增强，wire 正常路径不变）。
- [x] **Step 2: `resolve_param` 终判**。三分叉 39/42/34 行——先写三版**行为对照表测试**（同输入→各版输出），语义差若只在参数源清单（machine/config/env 顺序），上提为 `resolve_param(value, cli, source_map, precedence)` 参数化；若发现真语义冲突（如 serial 允许 int 转换而 wb 拒绝），**裁决=留三份 + 各 docstring 声明契约归属**，CHANGELOG 销账"F-029 部分收口"。禁止为凑去重率强改行为。
- [x] **Step 3: 收口账目**——重跑本计划开头的 AST 分桶脚本，输出"重复行净变化"进 CHANGELOG；`test_writeback_guards.py` 顶部 docstring"三份 runtime 拷贝同款同修"改为"共享层单一事实源"。
- [x] **Step 4:** 全绿 + commit + CHANGELOG F-029 状态更新（全收口 or 部分收口附裁决记录）

---

### Task 6: 收尾与开源门面

- [ ] CHANGELOG：F-029 处置条目（含净删行数实测、serial 同名异物裁决、resolve_param 终判结果）
- [ ] README：若有"工具目录结构"描述补 `runtime_common.py` 一行
- [ ] 全量 `Ran N OK (skipped=1)`，净行数 `git diff --stat` 报告
- [ ] commit `docs(F-029): 收口账目` → 提醒维护者 push（含全部未推 commit）

---

## 风险与回滚

- 每 Task 独立 commit，任一环全量红且 5 分钟内修不完 → `git revert` 该 Task 即回到上一个全绿态。
- 最大风险点：`save_json_file` 等被 mock 路径的测试（如 `mock.patch.object(mod.os, "replace", ...)`）——上提后 patch 目标是 `runtime_common.os.replace` 而非 `mod.os.replace`。Task 2 Step 3 必须显式跑 `tests.test_writeback_guards` 确认；若红，改测试的 patch 目标（`mock.patch.object(runtime_common.os, "replace", ...)`），并在测试注释记原因。
- F-029 期间不动 verify.py / 不并 wb_common——wb_common 是"路径解析"定位，runtime 行为共享层是 `runtime_common`，两层不许互相渗透。
