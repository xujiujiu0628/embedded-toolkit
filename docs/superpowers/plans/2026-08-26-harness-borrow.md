# xfail 期望清单 + 发布门禁 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给工作台落地 Harness 借鉴前两项——verify.py 期望清单四态判定（xfail/XPASS）+ release.py 发布门禁（clean rebuild 全绿才许打 tag）。

**Architecture:** 全部新逻辑内聚在 verify.py（加载器+纯函数判定+旗标）与新脚本 release.py（subprocess 复用 verify，不 import）。规格见 `docs/superpowers/specs/2026-08-26-harness-borrow-design.md`（commit e96718b），本计划的行号锚点基于 2026-08-26 的 verify.py（1155 行版）。

**Tech Stack:** Python 3.9+ 纯标准库、unittest、git、OpenOCD、arm-none-eabi-gcc/make。

## Global Constraints

- 工具库铁律"按脚本不做共享模块"：判定逻辑进 verify.py，门禁逻辑进 release.py，release 经 subprocess 调 verify。
- Windows 控制台 GBK：新增人读输出只用 ASCII 标记（[PASS]/[XFAIL]/[XPASS]/[FAIL]），禁止 emoji。
- 测试框架 unittest；文件放 `tests/test_*.py`；头部 `sys.path.insert(0, <repo>/scripts)`（沿 test_wb_common.py 惯例）。
- 运行单文件测试：`python -m unittest discover -s tests -p "<文件名>" -v`（toolkit 根目录执行）。
- 测试 import verify 会触发 import 期 `load_machine()`（verify.py:38）——本机 machine.json 存在，前提成立。
- 每个 Task 一个 commit（conventional commits），只 `git add` 本任务文件。
- Task 1–5 改 toolkit 仓可在 worktree 执行；**Task 6–7 必须在真实工程目录与真机上进行**（worktree 里没有板子也没有 adc-oled）。
- 带 [需板卡] 标记的步骤需要 ST-Link/OpenOCD 在位；板子不在时标注 DEFER 并继续后续非硬件任务。

---

### Task 1: 基线固定

**Files:**
- Modify: 无新文件（提交工作树存量改动）

**Interfaces:**
- Produces: 干净的 git 基线，后续任务的 diff 只含自己的改动。

- [x] **Step 1: 跑存量单测确认现状是绿的**

Run: `cd <工作区根>\embedded-toolkit && python -m unittest discover -s tests -v`
Expected: 全部 PASS。若已有失败，停下来报告用户，不得在其上叠加。

- [x] **Step 2: 提交存量改动为基线 commit**

```bash
git add -A
git commit -m "chore: baseline before harness-borrow work (pending gcc_build/templates/state)"
```

- [x] **Step 3: 确认树干净**

Run: `git status --porcelain`
Expected: 输出为空。

---

### Task 2: 清单加载与校验 load_expectations

**Files:**
- Modify: `scripts/verify.py`（在 verify() 函数之前，约 L527 前插入）
- Test: `tests/test_verify_expectations.py`（新建）

**Interfaces:**
- Produces: `ExpectationError(ValueError)`；`load_expectations(workspace) -> list | None`（不存在返回 None，非法抛 ExpectationError）。Task 4 的 main() 与 Task 3 无关此函数内部实现。

- [x] **Step 1: 写失败测试**

新建 `tests/test_verify_expectations.py`：

```python
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import verify  # noqa: E402  (import 期读 machine.json, 本机存在)


def _write_manifest(ws, expectations):
    wb = os.path.join(ws, ".workbench")
    os.makedirs(wb, exist_ok=True)
    with open(os.path.join(wb, "expectations.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "expectations": expectations}, f,
                  ensure_ascii=False)


class LoadExpectationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_none(self):
        self.assertIsNone(verify.load_expectations(self.tmp))

    def test_valid_minimal(self):
        _write_manifest(self.tmp,
                        [{"id": "FR-A-01", "desc": "d", "texts": ["x"]}])
        exp = verify.load_expectations(self.tmp)
        self.assertEqual(exp[0]["id"], "FR-A-01")

    def test_dup_id_raises(self):
        _write_manifest(self.tmp, [
            {"id": "A", "desc": "d", "texts": ["x"]},
            {"id": "A", "desc": "d", "texts": ["y"]},
        ])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_xfail_without_reason_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "texts": ["x"], "xfail": True}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_texts_and_patterns_both_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "texts": ["x"], "patterns": ["p"]}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_neither_raises(self):
        _write_manifest(self.tmp, [{"id": "A", "desc": "d"}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)

    def test_bad_capture_group_raises(self):
        _write_manifest(self.tmp,
                        [{"id": "A", "desc": "d", "patterns": ["(\\d+)"],
                          "capture_group": 0}])
        with self.assertRaises(verify.ExpectationError):
            verify.load_expectations(self.tmp)
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_verify_expectations.py" -v`
Expected: FAIL/ERROR —— `AttributeError: module 'verify' has no attribute 'ExpectationError'`

- [x] **Step 3: 实现**

verify.py 中 `def verify(...)` 定义之前插入：

```python
class ExpectationError(ValueError):
    """期望清单非法 (id 重复 / 缺 xfail_reason / texts+patterns 并存等)"""


def load_expectations(workspace):
    """加载 .workbench/expectations.json (spec 2026-08-26 §3)。

    文件不存在返回 None (调用方回退 legacy config.verify);
    清单非法抛 ExpectationError, main() 捕获后退出码 1。
    """
    path = os.path.join(workspace, ".workbench", "expectations.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("expectations"), list) \
            or not data["expectations"]:
        raise ExpectationError("须为含非空 expectations 数组的 JSON 对象")
    seen = set()
    for i, item in enumerate(data["expectations"]):
        where = f"expectations[{i}]"
        if not isinstance(item, dict):
            raise ExpectationError(f"{where}: 须为对象")
        eid = item.get("id")
        if not isinstance(eid, str) or not eid.strip():
            raise ExpectationError(f"{where}: id 必填且非空")
        if eid in seen:
            raise ExpectationError(f"id 重复: {eid}")
        seen.add(eid)
        if not isinstance(item.get("desc"), str) or not item["desc"].strip():
            raise ExpectationError(f"{eid}: desc 必填且非空")
        texts = item.get("texts")
        pats = item.get("patterns")
        ok_texts = isinstance(texts, list) and len(texts) > 0 and \
            all(isinstance(t, str) and t for t in texts)
        ok_pats = isinstance(pats, list) and len(pats) > 0 and \
            all(isinstance(p, str) and p for p in pats)
        if ok_texts == ok_pats:  # 并存或皆缺均非法
            raise ExpectationError(f"{eid}: texts 与 patterns 须二选一(非空字符串数组)")
        if item.get("xfail") and (not isinstance(item.get("xfail_reason"), str)
                                  or not item["xfail_reason"].strip()):
            raise ExpectationError(f"{eid}: xfail=true 时 xfail_reason 必填")
        cg = item.get("capture_group")
        if cg is not None and (isinstance(cg, bool) or not isinstance(cg, int) or cg < 1):
            raise ExpectationError(f"{eid}: capture_group 须为正整数")
        for bound in ("min", "max"):
            v = item.get(bound)
            if v is not None and not isinstance(v, (int, float)):
                raise ExpectationError(f"{eid}: {bound} 须为数值")
    return data["expectations"]
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_verify_expectations.py" -v`
Expected: 7 tests PASS

- [x] **Step 5: Commit**

```bash
git add scripts/verify.py tests/test_verify_expectations.py
git commit -m "feat(verify): expectations.json 加载器与合法性校验"
```

---

### Task 3: 四态判定纯函数 evaluate_expectations

**Files:**
- Modify: `scripts/verify.py`（紧跟 Task 2 新增代码之后）
- Test: `tests/test_verify_expectations.py`（追加类）

**Interfaces:**
- Consumes: 无（独立纯函数）。
- Produces:
  - `_expect_matched(item, output) -> (matched: bool, detail: str)`
  - `evaluate_expectations(output, expectations) -> {"results": [{"id","status","detail"?}], "verdict": "ok"|"fail", "xpass_ids": [str]}`
  - `cli_expectations(expect, expect_patterns, require_tgl) -> list[dict]`（保留 ID：`CLI-TEXT-nn` / `CLI-PAT-nn` / `CLI-REQUIRE-TGL`）

- [x] **Step 1: 写失败测试（追加到 test_verify_expectations.py 末尾）**

```python
class EvaluateExpectationsTests(unittest.TestCase):
    def test_pass(self):
        ev = verify.evaluate_expectations("boot ok",
                                          [{"id": "A", "texts": ["ok"]}])
        self.assertEqual(ev["verdict"], "ok")
        self.assertEqual(ev["results"], [{"id": "A", "status": "pass"}])
        self.assertEqual(ev["xpass_ids"], [])

    def test_fail_with_detail(self):
        ev = verify.evaluate_expectations("boot", [{"id": "A", "texts": ["ok"]}])
        self.assertEqual(ev["verdict"], "fail")
        self.assertEqual(ev["results"][0]["status"], "fail")
        self.assertIn("missing texts", ev["results"][0]["detail"])

    def test_xfail_keeps_suite_green(self):
        ev = verify.evaluate_expectations(
            "", [{"id": "A", "texts": ["ok"], "xfail": True}])
        self.assertEqual((ev["verdict"], ev["results"][0]["status"]),
                         ("ok", "xfail"))

    def test_xpass_is_strict_red(self):
        ev = verify.evaluate_expectations(
            "ok", [{"id": "A", "texts": ["ok"], "xfail": True}])
        self.assertEqual((ev["verdict"], ev["results"][0]["status"]),
                         ("fail", "xpass"))
        self.assertEqual(ev["xpass_ids"], ["A"])

    def test_patterns_array_all_must_hit(self):
        item = {"id": "A", "patterns": [r"\d+", r"[a-z]+"]}
        self.assertEqual(
            verify.evaluate_expectations("123", [item])["verdict"], "fail")
        self.assertEqual(
            verify.evaluate_expectations("123 abc", [item])["verdict"], "ok")

    def test_capture_group_threshold_boundary(self):
        item = {"id": "R", "patterns": [r"Hz=(\d+)"], "capture_group": 1,
                "min": 2}
        self.assertEqual(
            verify.evaluate_expectations("Hz=2", [item])["verdict"], "ok")
        self.assertEqual(
            verify.evaluate_expectations("Hz=1", [item])["verdict"], "fail")

    def test_cli_rows_and_tgl(self):
        items = verify.cli_expectations([], [], require_tgl=True)
        self.assertEqual([i["id"] for i in items], ["CLI-REQUIRE-TGL"])
        ev = verify.evaluate_expectations("TGL 3 TGL 4", items)
        self.assertEqual(ev["verdict"], "ok")

    def test_verdict_fails_if_any_fail_among_xfails(self):
        exp = [{"id": "A", "texts": ["a"], "xfail": True},
               {"id": "B", "texts": ["b"]}]
        ev = verify.evaluate_expectations("a c", exp)   # A=XFAIL, B=FAIL
        self.assertEqual(ev["verdict"], "fail")
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_verify_expectations.py" -v`
Expected: 新增 8 个 ERROR —— no attribute 'evaluate_expectations'（原有 7 个仍 PASS）

- [x] **Step 3: 实现（追加在 load_expectations 之后）**

```python
def _expect_matched(item, output):
    """单条期望匹配判定 (spec §3): texts 全命中 且 patterns 全命中;
    capture_group/min/max 数值断言作用于 patterns[0] 首个 match。
    返回 (matched, 失败细节)。"""
    missing = [t for t in item.get("texts", []) if t not in output]
    if missing:
        return False, f"missing texts: {missing}"
    first = None
    for j, pat in enumerate(item.get("patterns", [])):
        m = re.search(pat, output)
        if not m:
            return False, f"pattern 未命中: {pat!r}"
        if j == 0:
            first = m
    cg = item.get("capture_group")
    if cg is not None:
        try:
            value = float(first.group(cg))
        except (IndexError, TypeError, ValueError):
            return False, f"capture_group={cg} 提取失败"
        lo = item.get("min")
        hi = item.get("max")
        if lo is not None and value < float(lo):
            return False, f"值 {value} < min {lo}"
        if hi is not None and value > float(hi):
            return False, f"值 {value} > max {hi}"
    return True, ""


def evaluate_expectations(output, expectations):
    """四态判定纯函数 (spec §4): PASS=匹配&非xfail; XFAIL=未匹配&xfail;
    XPASS=匹配&xfail(严格红); FAIL=未匹配&非xfail。
    verdict="ok" 当且仅当所有 status ∈ {pass, xfail}。无 IO, 可单测。"""
    results = []
    for item in expectations:
        ok, detail = _expect_matched(item, output)
        xfail = bool(item.get("xfail"))
        if ok and not xfail:
            status = "pass"
        elif ok and xfail:
            status = "xpass"
        elif not ok and xfail:
            status = "xfail"
        else:
            status = "fail"
        r = {"id": item["id"], "status": status}
        if detail and status in ("fail", "xpass"):
            r["detail"] = detail
        results.append(r)
    verdict = "ok" if all(r["status"] in ("pass", "xfail") for r in results) else "fail"
    return {"results": results, "verdict": verdict,
            "xpass_ids": [r["id"] for r in results if r["status"] == "xpass"]}


def cli_expectations(expect, expect_patterns, require_tgl):
    """legacy CLI/config 叠加断言 → 合成保留 ID 行 (spec §5.3), 保证
    --json 门禁证据完整。清单模式下 config expect* 不参与, 仅显式 CLI 断言叠加。"""
    items = []
    for i, t in enumerate(expect or []):
        items.append({"id": f"CLI-TEXT-{i:02d}", "texts": [t]})
    for i, p in enumerate(expect_patterns or []):
        items.append({"id": f"CLI-PAT-{i:02d}", "patterns": [p]})
    if require_tgl:
        items.append({"id": "CLI-REQUIRE-TGL", "patterns": [r"TGL \d+"]})
    return items
```

- [x] **Step 4: 跑全部测试确认通过**

Run: `python -m unittest discover -s tests -p "test_verify_expectations.py" -v`
Expected: 15 tests PASS

- [x] **Step 5: Commit**

```bash
git add scripts/verify.py tests/test_verify_expectations.py
git commit -m "feat(verify): 四态判定纯函数 evaluate_expectations + CLI 保留行合成"
```

---

### Task 4: verify.py 集成（清单模式接线 + --rebuild/--gate-run）

**Files:**
- Modify: `scripts/verify.py`（7 处小编辑，锚点行号为基线版）

**Interfaces:**
- Consumes: Task 2/3 的三个函数。
- Produces: CLI `--rebuild`、`--gate-run`；manifest 模式下 steps.verify 含 `results/xpass_ids`；`--json` 顶层含 `expect_mode`。legacy 行为逐字节不变（无 expectations.json 时）。

- [x] **Step 1: argparse 增旗标（L676 后）**

old_string：
```
                             "2026-08-16 review M1 门禁; 纯 boot 验证勿用)")
    args = parser.parse_args()
```
new_string：
```
                             "2026-08-16 review M1 门禁; 纯 boot 验证勿用)")
    parser.add_argument("--rebuild", action="store_true",
                        help="编译前先 clean (仅 builder=gcc; 发布门禁用)")
    parser.add_argument("--gate-run", dest="gate_run", action="store_true",
                        help="发布门禁发起的运行: 跳过 feedback_db 落账")
    args = parser.parse_args()
```

- [x] **Step 2: step_build 支持 rebuild（L286-296）**

old_string：
```
def step_build(config: dict, builder: str = "keil") -> dict:
    """步骤 1: 编译 (按 config.json builder 字段切换后端: keil | gcc)"""
    if builder == "gcc":
```
new_string：
```
def step_build(config: dict, builder: str = "keil",
               rebuild: bool = False) -> dict:
    """步骤 1: 编译 (按 config.json builder 字段切换后端: keil | gcc)"""
    if rebuild and builder != "gcc":
        # YAGNI: keil 后端不接 --rebuild (blink legacy 不用该旗标)
        return {"status": "error", "message": "--rebuild 仅支持 builder=gcc"}
    if builder == "gcc":
```
再改 gcc 分支的 action 行——old_string：
```
        args = ["build", "--project", project,
                "--target", target, "--log-dir", log_dir, "--json"]
        return run_py(GCC_BUILD, args, timeout=300)
```
new_string：
```
        args = ["rebuild" if rebuild else "build", "--project", project,
                "--target", target, "--log-dir", log_dir, "--json"]
        return run_py(GCC_BUILD, args, timeout=300)
```
调用点（L723）——old_string：
```
            build = step_build(config, builder)
```
new_string：
```
            build = step_build(config, builder, rebuild=args.rebuild)
```

- [x] **Step 3: main() 装载清单（L703-705 后）**

old_string：
```
    verify_cfg = config.get("verify", {})
    expect = verify_cfg.get("expect", [])
    description = verify_cfg.get("description", "")
```
new_string：
```
    verify_cfg = config.get("verify", {})
    expect = verify_cfg.get("expect", [])
    description = verify_cfg.get("description", "")

    # 期望清单模式: .workbench/expectations.json 存在则优先,
    # 否则回退 legacy config.verify (blink/toggle 不受影响)
    try:
        expectations = load_expectations(WORKSPACE)
    except ExpectationError as e:
        print(f"错误: 期望清单非法: {e}", file=sys.stderr)
        sys.exit(1)
    expect_mode = "manifest" if expectations is not None else "legacy"
```

result 初始化加字段——old_string：
```
        "toolkit_version": toolkit_version(),
        "expect": expect,
```
new_string：
```
        "toolkit_version": toolkit_version(),
        "expect_mode": expect_mode,
        "expect": expect,
```

- [x] **Step 4: Step 5 判定块插 manifest 分支（L1022 起）**

old_string：
```
    else:
        # 正则断言: 配置键 verify.expect_patterns (缺省空) + CLI --require-tgl 注入
        expect_patterns = list(verify_cfg.get("expect_patterns", []) or [])
        if getattr(args, "require_tgl", False):
            expect_patterns.append(r"TGL \d+")
        verification_result = verify(captured_text, expect, description,
                                     expect_patterns=expect_patterns or None)
        # capture 空兜底: 确实烧录过但无输出且无 HardFault 迹象 → 归因准确
        if capture_empty and flash_ran:
            verification_result["description"] = (
                "程序无输出（无 HardFault 迹象）: "
                + verification_result.get("description", "")
            )
```
new_string：
```
    elif expect_mode == "manifest":
        # 期望清单模式: 四态判定; config expect* 不参与, 仅显式 CLI 断言叠加 (spec §5.3)
        cli_items = cli_expectations([], [], getattr(args, "require_tgl", False))
        ev = evaluate_expectations(captured_text, list(expectations) + cli_items)
        verification_result = {
            "status": ev["verdict"],
            "all_expected_found": ev["verdict"] == "ok",
            "matched": [r["id"] for r in ev["results"] if r["status"] == "pass"],
            "missing": [r["id"] for r in ev["results"] if r["status"] == "fail"],
            "results": ev["results"],
            "xpass_ids": ev["xpass_ids"],
            "description": description,
            "needs_ai_judgement": True,
        }
        # capture 空兜底 (与 legacy 同款归因)
        if capture_empty and flash_ran:
            verification_result["description"] = (
                "程序无输出（无 HardFault 迹象）: "
                + verification_result.get("description", "")
            )
    else:
        # 正则断言: 配置键 verify.expect_patterns (缺省空) + CLI --require-tgl 注入
        expect_patterns = list(verify_cfg.get("expect_patterns", []) or [])
        if getattr(args, "require_tgl", False):
            expect_patterns.append(r"TGL \d+")
        verification_result = verify(captured_text, expect, description,
                                     expect_patterns=expect_patterns or None)
        # capture 空兜底: 确实烧录过但无输出且无 HardFault 迹象 → 归因准确
        if capture_empty and flash_ran:
            verification_result["description"] = (
                "程序无输出（无 HardFault 迹象）: "
                + verification_result.get("description", "")
            )
```

- [x] **Step 5: feedback 落账加门禁静音（L1057-1074）**

old_string：
```
    # 注入点 ③: 自动记录反馈事件（异步，失败不影响主流程）
    try:
        feedback_event = {
            "pipeline": "hardfault" if has_hardfault else "build_fix",
            "error_code": result.get("steps", {}).get("analyze", {}).get("errors", None),
            "fault_type": result.get("steps", {}).get("hardfault", {}).get("fault_type"),
            "build_result": _build_result_str(result),
            "verify_result": "pass" if result["status"] == "ok" else "fail",
            "outcome": "fixed" if result["status"] == "ok" else "still_broken",
        }
        if has_hardfault:
            feedback_event["outcome"] = "still_broken"
        subprocess.run(
            [sys.executable, FEEDBACK_DB, "--log", json.dumps(feedback_event)],
            capture_output=True, timeout=10, cwd=WORKSPACE
        )
    except Exception:
        pass  # 反馈记录失败不影响主流程
```
new_string：
```
    # 注入点 ③: 自动记录反馈事件（异步，失败不影响主流程）。
    # --gate-run 跳过: 门禁重跑/豁免运行不得污染校准统计 (spec 2026-08-26 §5)
    if not getattr(args, "gate_run", False):
        try:
            feedback_event = {
                "pipeline": "hardfault" if has_hardfault else "build_fix",
                "error_code": result.get("steps", {}).get("analyze", {}).get("errors", None),
                "fault_type": result.get("steps", {}).get("hardfault", {}).get("fault_type"),
                "build_result": _build_result_str(result),
                "verify_result": "pass" if result["status"] == "ok" else "fail",
                "outcome": "fixed" if result["status"] == "ok" else "still_broken",
            }
            if has_hardfault:
                feedback_event["outcome"] = "still_broken"
            subprocess.run(
                [sys.executable, FEEDBACK_DB, "--log", json.dumps(feedback_event)],
                capture_output=True, timeout=10, cwd=WORKSPACE
            )
        except Exception:
            pass  # 反馈记录失败不影响主流程
```

- [x] **Step 6: XPASS 专属 agent_hint（L634-640）**

old_string：
```
        else:
            missing = steps.get("verify", {}).get("missing", [])
            ctx["agent_hint"] = (
                f"Semihosting OK but expected patterns missing: {missing}. "
                "Check registry registration order and printf format in "
                "modules/*/registry entries."
            )
```
new_string：
```
        else:
            xpass_ids = steps.get("verify", {}).get("xpass_ids") or []
            if xpass_ids:
                ctx["agent_hint"] = (
                    f"XPASS detected: {xpass_ids}. 功能已落地而清单仍标 xfail — "
                    "把 .workbench/expectations.json 对应条目改为 "
                    "xfail:false 后重跑."
                )
            else:
                missing = steps.get("verify", {}).get("missing", [])
                ctx["agent_hint"] = (
                    f"Semihosting OK but expected patterns missing: {missing}. "
                    "Check registry registration order and printf format in "
                    "modules/*/registry entries."
                )
```

- [x] **Step 7: 人读输出逐条渲染（L1132-1137）**

old_string：
```
        verify_s = steps.get("verify", {})
        print(f"[5] Verify:   {verify_s.get('status', '?').upper()}")
        if verify_s.get("matched"):
            print(f"    Found:     {verify_s['matched']}")
        if verify_s.get("missing"):
            print(f"    Missing:   {verify_s['missing']}")
```
new_string（ASCII 标签，GBK 控制台安全）：
```
        verify_s = steps.get("verify", {})
        mode_tag = "  mode=manifest" if verify_s.get("results") is not None else ""
        print(f"[5] Verify:   {verify_s.get('status', '?').upper()}{mode_tag}")
        if verify_s.get("matched"):
            print(f"    Found:     {verify_s['matched']}")
        if verify_s.get("missing"):
            print(f"    Missing:   {verify_s['missing']}")
        for r in verify_s.get("results") or []:
            label = {"pass": "[PASS]", "xfail": "[XFAIL]", "xpass": "[XPASS]",
                     "fail": "[FAIL]"}.get(r["status"], "[????]")
            extra = f"  ({r['detail']})" if r.get("detail") else ""
            print(f"    {label} {r['id']}{extra}")
        if verify_s.get("xpass_ids"):
            print(f"    >>> XPASS 落地信号: {', '.join(verify_s['xpass_ids'])}"
                  " - 请翻转对应 xfail 后重跑 <<<")
```

- [x] **Step 8: 回归全绿**

Run: `python -m unittest discover -s tests -v && python scripts/verify.py --help`
Expected: 测试全 PASS；help 输出含 --rebuild 与 --gate-run。

- [x] **Step 9: Commit**

```bash
git add scripts/verify.py
git commit -m "feat(verify): manifest 模式接线 (--rebuild/--gate-run, results[] 输出, XPASS hint, gate 静音反馈库)"
```

---

### Task 5: release.py 发布门禁

**Files:**
- Create: `scripts/release.py`
- Test: `tests/test_release.py`（新建）

**Interfaces:**
- Consumes: verify.py CLI（`--json --rebuild --gate-run`）；wb_common 的 TOOLKIT_ROOT/find_project_root/load_machine/toolkit_version；machine.json 的 openocd_exe、gcc_path。
- Produces:
  - `_git(args_, cwd) -> (rc, stdout, stderr)`
  - `g0_checks(ws, tag) -> list[str]`（空=过）
  - `swd_probe(openocd_exe) -> (ok, msg)`
  - `gate1(ws, timeout) -> dict`（verify 的 JSON 结果或 error dict）
  - `run_gates(ws, tag, allow_xfail, timeout, openocd_exe) -> (ok, msg, ctx)`
  - `sha256_file(path) -> str`
  - `build_record(ws, tag, results, waived) -> dict`
  - `finalize(ws, tag, record) -> bool`（写记录→复核→tag→回滚）
  - 退出码：0=通过，1=任一门失败

- [x] **Step 1: 写失败测试**

新建 `tests/test_release.py`：

```python
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import release  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

        def git(*a):
            subprocess.run(["git"] + GIT_ID + list(a), cwd=self.ws,
                           capture_output=True, timeout=30, check=True)
        git("init", "-q")
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("x")
        git("add", "-A")
        git("commit", "-qm", "init")
        self.git = git

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_g0_dirty_tree_fails(self):
        with open(os.path.join(self.ws, "f.txt"), "w") as f:
            f.write("y")
        errs = release.g0_checks(self.ws, "v9.9.9")
        self.assertTrue(any("不干净" in e for e in errs))

    def test_g0_existing_tag_fails(self):
        self.git("tag", "v1.0.0")
        errs = release.g0_checks(self.ws, "v1.0.0")
        self.assertTrue(any("已存在" in e for e in errs))

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_blocks_unflipped_xfail(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok",
            "steps": {"verify": {"results": [
                {"id": "FR-A", "status": "pass"},
                {"id": "FR-B", "status": "xfail"},
            ]}},
        }
        ok, msg, _ = release.run_gates(self.ws, "v1.0.0", allow_xfail=False,
                                       timeout=10, openocd_exe="openocd")
        self.assertFalse(ok)
        self.assertIn("FR-B", msg)

    @mock.patch.object(release, "swd_probe", return_value=(True, "ok"))
    @mock.patch.object(release, "gate1")
    def test_g2_allow_xfail_waives(self, m_gate1, _probe):
        m_gate1.return_value = {
            "status": "ok",
            "steps": {"verify": {"results": [{"id": "FR-B", "status": "xfail"}]}},
        }
        ok, _, ctx = release.run_gates(self.ws, "v1.0.0", allow_xfail=True,
                                       timeout=10, openocd_exe="openocd")
        self.assertTrue(ok)
        self.assertEqual(ctx["waived"], ["FR-B"])

    def test_finalize_success_tags_and_keeps_record(self):
        _, head, _ = release._git(["rev-parse", "HEAD"], self.ws)
        rec = {"tag": "v1.0.0", "git_head": head, "branch": "master"}
        self.assertTrue(release.finalize(self.ws, "v1.0.0", rec))
        _, out, _ = release._git(["tag", "-l", "v1.0.0"], self.ws)
        self.assertEqual(out, "v1.0.0")
        self.assertTrue(os.path.exists(os.path.join(
            self.ws, ".workbench", "releases", "v1.0.0.json")))

    def test_finalize_rolls_back_on_head_change(self):
        rec = {"tag": "v1.0.0", "git_head": "deadbeef", "branch": "master"}
        self.assertFalse(release.finalize(self.ws, "v1.0.0", rec))
        self.assertFalse(os.path.exists(os.path.join(
            self.ws, ".workbench", "releases", "v1.0.0.json")))
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m unittest discover -s tests -p "test_release.py" -v`
Expected: ImportError —— No module named 'release'

- [x] **Step 3: 实现 release.py（完整新建）**

```python
#!/usr/bin/env python3
"""发布门禁 — git tag 前以 clean rebuild 字节完整重跑闭环验证

借鉴 Embedded-AI-Harness #2 (发布字节复跑), spec 2026-08-26 §6。
门禁序列 (任一失败即中止):
  G0   git 仓 + 工作树 clean + 本地无同名 tag + 无同 HEAD 记录
  G0.5 SWD 连通性预检 (秒级, 区分"环境未备"与"固件真坏")
  G1   subprocess 重跑 verify.py --json --rebuild --gate-run, 须全绿
  G2   无未翻转 xfail (--allow-xfail 显式豁免留痕)
  G3   发布记录落盘 -> 复核 HEAD 未变 -> annotated tag -> 失败回滚记录

用法:
  python release.py --tag v1.0.0 [--project DIR] [--dry-run] [--allow-xfail]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wb_common import (TOOLKIT_ROOT, find_project_root,  # noqa: E402
                       load_machine, toolkit_version)

VERIFY = os.path.join(TOOLKIT_ROOT, "scripts", "verify.py")


def _git(args_, cwd):
    r = subprocess.run(["git"] + args_, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30, cwd=cwd)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def g0_checks(ws, tag):
    """G0: 返回违规消息列表 (空 = 通过)。拒绝键: 本地 tag 已存在
    或 存在 git_head 相同的既有记录 (不同 HEAD 的旧记录视为可覆盖)。"""
    rc, out, _ = _git(["rev-parse", "--is-inside-work-tree"], ws)
    if rc != 0 or out != "true":
        return [f"不是 git 仓库: {ws}"]
    errs = []
    rc, dirty, _ = _git(["status", "--porcelain"], ws)
    if rc != 0 or dirty:
        errs.append("工作树不干净 (先 commit; git status --porcelain 非空)")
    rc, out, _ = _git(["tag", "-l", tag], ws)
    if rc == 0 and out:
        errs.append(f"本地 tag 已存在: {tag}")
    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    rec_p = os.path.join(ws, ".workbench", "releases", f"{tag}.json")
    if os.path.exists(rec_p):
        try:
            with open(rec_p, encoding="utf-8") as f:
                old_head = json.load(f).get("git_head", "")
            if old_head == head:
                errs.append(f"同 HEAD 已有发布记录: {rec_p}")
        except Exception:
            errs.append(f"既有发布记录不可解析: {rec_p}")
    return errs


def swd_probe(openocd_exe):
    """G0.5: 秒级 SWD 探测。cfg 与 verify.step_flash 同源 (F103+STLink 舰队假设)。"""
    cmd = [openocd_exe,
           "-f", "interface/stlink.cfg",
           "-f", "target/stm32f1x.cfg",
           "-c", "init", "-c", "targets", "-c", "shutdown"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=15)
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0 and "shutdown command invoked" in (r.stdout or "")
        return ok, out[-200:]
    except subprocess.TimeoutExpired:
        return False, "SWD 探测超时 (15s)"
    except Exception as e:
        return False, str(e)


def gate1(ws, timeout):
    """G1: subprocess 重跑 verify (clean rebuild + 清单判定), 返回 JSON 结果。
    验证的就是开发者日常那条命令 — 门禁公信力所在。"""
    cmd = [sys.executable, VERIFY, "--json", "--rebuild",
           "--gate-run", "--timeout", str(timeout)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=600, cwd=ws)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "verify 重跑超时 (600s)"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        tail = ((r.stderr or "") + (r.stdout or ""))[-300:]
        return {"status": "error", "error": f"verify 输出不可解析: {tail}"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _gcc_version():
    m = load_machine()
    gcc_path = (m.get("gcc_path") or "").strip()
    exe = os.path.join(gcc_path, "arm-none-eabi-gcc.exe") if gcc_path \
        else "arm-none-eabi-gcc"
    try:
        r = subprocess.run([exe, "--version"], capture_output=True,
                           text=True, timeout=10)
        lines = (r.stdout or "").splitlines()
        return lines[0][:80] if lines else "unknown"
    except Exception:
        return "unknown"


def run_gates(ws, tag, allow_xfail, timeout, openocd_exe):
    """跑 G0~G2。返回 (ok, 人读消息, ctx)；ctx 含 verify 结果/results/waived。"""
    errs = g0_checks(ws, tag)
    if errs:
        return False, "G0 失败:\n  " + "\n  ".join(errs), {}
    ok, msg = swd_probe(openocd_exe)
    if not ok:
        return False, f"G0.5 SWD 预检失败 (环境未备?): {msg}", {}
    res = gate1(ws, timeout)
    if res.get("status") != "ok":
        return False, (f"G1 verify 未绿: {res.get('error', res.get('status'))}\n"
                       "  修复后重试; 现场见 .workbench/build/last_failure.json"), {}
    results = (res.get("steps", {}).get("verify", {}) or {}).get("results")
    if results is None:
        return False, "G1 结果缺 results 数组 (该工程是否未建 expectations.json?)", {}
    reds = [r["id"] for r in results if r["status"] == "fail"]
    if reds:
        return False, f"G1 有 FAIL 条目: {', '.join(reds)}", {}
    xfailed = [r["id"] for r in results if r["status"] == "xfail"]
    if xfailed and not allow_xfail:
        return False, ("G2 存在未翻转 xfail: " + ", ".join(xfailed) +
                       "\n  实现并翻转后重试; 或 --allow-xfail 显式豁免 (留痕入档)"), {}
    waived = list(xfailed)
    return True, "G0~G2 全过", {"verify_result": res, "results": results,
                                "waived": waived}


def build_record(ws, tag, results, waived):
    artifacts = {}
    state_p = os.path.join(ws, ".workbench", "state.json")
    arts = {}
    if os.path.exists(state_p):
        try:
            with open(state_p, encoding="utf-8") as f:
                arts = json.load(f).get("last_build", {}).get("artifacts", {})
        except Exception:
            arts = {}
    for key in ("hex_file", "elf_file"):
        rel = arts.get(key, "")
        abs_p = os.path.join(ws, rel) if rel else ""
        if rel and os.path.exists(abs_p):
            artifacts[key.replace("_file", "")] = {
                "path": rel, "sha256": sha256_file(abs_p)}
    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    _, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    return {
        "tag": tag,
        "git_head": head,
        "branch": branch or "?",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "build_mode": "clean_rebuild",
        "artifacts": artifacts,
        "results": results,
        "xfail_waived": waived,
        "tools": {"toolkit": toolkit_version(),
                  "python": sys.version.split()[0],
                  "gcc": _gcc_version()},
    }


def finalize(ws, tag, record):
    """G3+tag 安全序列: 写记录 -> 复核 HEAD 未变且无其他改动 -> 打 annotated
    tag -> 任一步失败回滚删除记录。注意: 记录文件自身造成的 dirty 是预期内的
    (releases/ 入库策略), 只拦截"其他"改动。成功后 git add 记录供用户提交。"""
    rec_dir = os.path.join(ws, ".workbench", "releases")
    os.makedirs(rec_dir, exist_ok=True)
    rec_p = os.path.join(rec_dir, f"{tag}.json")
    with open(rec_p, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    rec_rel = os.path.relpath(rec_p, ws).replace(os.sep, "/")
    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    _, dirty, _ = _git(["status", "--porcelain"], ws)
    foreign = [l for l in dirty.splitlines()
               if l.strip() and not l.strip().endswith(rec_rel)]
    if head != record["git_head"] or foreign:
        os.remove(rec_p)
        print(f"打 tag 前复核失败: HEAD 变动或出现其他改动 ({foreign}), 记录已回滚",
              file=sys.stderr)
        return False
    r = subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"release {tag} (record: {rec_rel})"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30, cwd=ws)
    if r.returncode != 0:
        os.remove(rec_p)
        print(f"打 tag 失败, 记录已回滚: {(r.stderr or '').strip()}",
              file=sys.stderr)
        return False
    _git(["add", rec_rel], ws)
    return True


def main():
    ap = argparse.ArgumentParser(description="发布门禁 — 全绿才许打 tag")
    ap.add_argument("--tag", required=True, help="版本 tag, 如 v1.0.0")
    ap.add_argument("--project", default=None, help="工程根目录 (默认向上发现)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑 G0~G2, 不落记录不打 tag")
    ap.add_argument("--allow-xfail", action="store_true",
                    help="豁免未翻转 xfail (ID 记入发布档案)")
    ap.add_argument("--timeout", type=int, default=10, help="采集超时秒数")
    args = ap.parse_args()

    ws = args.project or find_project_root(os.getcwd())
    if not ws:
        print("错误: 未找到工程根 (含 .workbench/config.json)", file=sys.stderr)
        sys.exit(1)
    ws = os.path.abspath(ws)
    openocd_exe = load_machine()["openocd_exe"]

    ok, msg, ctx = run_gates(ws, args.tag, args.allow_xfail,
                             args.timeout, openocd_exe)
    print(msg)
    if not ok:
        sys.exit(1)

    record = build_record(ws, args.tag, ctx["results"], ctx["waived"])
    if args.dry_run:
        print(f"[dry-run] 将写 .workbench/releases/{args.tag}.json 并打 tag "
              f"{args.tag}; results={len(record['results'])} 条, "
              f"xfail_waived={record['xfail_waived']}, "
              f"artifacts={list(record['artifacts'])}")
        sys.exit(0)

    if not finalize(ws, args.tag, record):
        sys.exit(1)
    print(f"[OK] 已发布 {args.tag}: 记录 .workbench/releases/{args.tag}.json;"
          " push 请自行执行")


if __name__ == "__main__":
    main()
```

注意：finalize 中 tag 子进程调用必须原样使用上面代码块的写法（不带 `-c user.*` 配置注入——tag message 不需要作者身份）。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m unittest discover -s tests -p "test_release.py" -v`
Expected: 6 tests PASS

- [x] **Step 5: 全套件回归 + dry-run 冒烟（无板也应走到 G0.5 失败）**

Run: `python -m unittest discover -s tests -v && python scripts/release.py --tag v0.0.0-smoke --project <工作区根>\stm32f103-adc-oled --dry-run`
Expected: 单测全 PASS；冒烟输出 `G0.5 SWD 预检失败` 或 `G0 失败`（adc-oled 尚无 git），且**绝不产生** releases/ 文件。

- [x] **Step 6: Commit**

```bash
git add scripts/release.py tests/test_release.py
git commit -m "feat(release): 发布门禁 G0~G3 + tag 安全序列 (dry-run/--allow-xfail)"
```

---

### Task 6: adc-oled 落地（git init + 清单迁移 + 演示需求）

**Files:**
- Create: `<工作区根>\stm32f103-adc-oled\.gitignore`
- Create: `<工作区根>\stm32f103-adc-oled\.workbench\expectations.json`
- Modify: `<工作区根>\stm32f103-adc-oled\.workbench\config.json`（verify 块让位）

**Interfaces:**
- Consumes: Task 4 的 manifest 模式。
- Produces: FR-SYS-01 / FR-ADC-01 / FR-ADC-02 三条迁移期望 + FR-ALERT-01（xfail 演示种子，Task 7 实现）。

- [x] **Step 1: git init + gitignore + 基线 commit**

`.gitignore` 内容：

```
# 构建产物与机器状态不入库 (spec 2026-08-26 §7)
.workbench/build/
.workbench/state.json
.workbench/build/last_failure.json
build/
*.o
*.d
```

命令（PowerShell，项目根）：

```powershell
cd <工作区根>\stm32f103-adc-oled
git init
# 写入上面的 .gitignore 后:
git add -A
git status --short   # 确认 build/ 与 .workbench/build|state 未被纳入
git commit -m "chore: baseline import (pre harness-borrow onboarding)"
```

Expected: 提交不含 build/ 与 state.json。

- [x] **Step 2: 写 expectations.json**

`.workbench/expectations.json`：

```json
{
  "version": "1.0",
  "expectations": [
    {
      "id": "FR-SYS-01",
      "desc": "上电输出 boot 横幅",
      "texts": ["=== adc-oled boot ==="],
      "xfail": false
    },
    {
      "id": "FR-ADC-01",
      "desc": "ADC 初始化成功",
      "texts": ["[init] ADC OK"],
      "xfail": false
    },
    {
      "id": "FR-ADC-02",
      "desc": "周期采样行 raw/mv/V 三值一致换算",
      "patterns": ["ADC raw=\\d+ mv=\\d+ \\(\\d\\.\\d\\d V\\)"],
      "xfail": false
    },
    {
      "id": "FR-ALERT-01",
      "desc": "电压 >3.0V 时输出告警行 ALERT HIGH mv=<n>",
      "patterns": ["ALERT HIGH mv=(\\d+)"],
      "capture_group": 1,
      "min": 3000,
      "xfail": true,
      "xfail_reason": "超压告警功能未实现 (验收剧本演示需求)"
    }
  ]
}
```

注：原 config 的裸子串 `"ADC raw="` 被 FR-ADC-02 的整行正则涵盖，有意不再单独迁移（commit message 里注明）。

- [x] **Step 3: config.json 的 verify 块让位**

把 `.workbench/config.json` 中整个 `"verify": {...}` 块替换为：

```json
  "verify": {
    "description": "期望已迁移至 .workbench/expectations.json (2026-08-26)"
  },
```

（保留键名以防旧工具读它；expect/expect_patterns 移除，避免双源混淆。）

- [x] **Step 4: 提交**

```powershell
git add .workbench
git commit -m "feat: migrate verify expectations to manifest (+FR-ALERT-01 xfail seed); drop bare ADC raw= (subsumed by FR-ADC-02)"
```

- [x] **Step 5: [需板卡] 清单模式冒烟**

```powershell
python <工作区根>\embedded-toolkit\scripts\verify.py --project <工作区根>\stm32f103-adc-oled
```

Expected: `[5] Verify: OK  mode=manifest`，四行 `[PASS] FR-SYS-01 / FR-ADC-01 / FR-ADC-02` + `[XFAIL] FR-ALERT-01`，总 Verdict PASS（XFAIL 保绿）。板子不在则 DEFER 到 Task 7。

- [x] **Step 6: Commit（若 Step 5 有微调）**

```powershell
git add -A; git commit -m "fix: manifest smoke adjustments"  # 仅当有改动
```

---

### Task 7: 真机 E2E 验收剧本（spec §9，全绿才算完成）

**Files:**
- Modify: `<工作区根>\stm32f103-adc-oled\User\main.c`（实现 FR-ALERT-01）

前置：ST-Link 在位。以下每步记录实际输出；任何一步不符即停。

- [x] **Step 1: XFAIL 生效（条目级红、套件绿）**

Run: `python <工作区根>\embedded-toolkit\scripts\verify.py --project <工作区根>\stm32f103-adc-oled`
Expected: Verdict PASS；含 `[XFAIL] FR-ALERT-01`。（spec §9.1 的"红"指条目级 XFAIL 标记；套件按设计保绿。）

- [x] **Step 2: 实现告警 → XPASS 强制翻转**

先定位采样 printf：`grep -n "ADC raw" User/main.c`。在该打印之后按现有变量名加：

```c
if (mv > 3000)
{
    printf("ALERT HIGH mv=%u\r\n", (unsigned)mv);
}
```

（若电位器当前 <3V，先把电位器拧到 >3V 再跑。）重跑 verify：

Expected: `Verdict: FAIL`，`[XPASS] FR-ALERT-01` + 落地信号提示行；last_failure.json 的 agent_hint 为 XPASS 专属文案。

- [x] **Step 3: 翻转 → 全绿**

把 FR-ALERT-01 改 `"xfail": false`（删掉 xfail_reason 或留注释均可——loader 允许 false 时不带 reason），重跑 verify。
Expected: 四条全 `[PASS]`，Verdict PASS。

```powershell
git add -A; git commit -m "feat(adc): over-voltage ALERT line (FR-ALERT-01) + flip expectation"
```

- [x] **Step 4: dry-run 四门**

```powershell
python <工作区根>\embedded-toolkit\scripts\release.py --project <工作区根>\stm32f103-adc-oled --tag v1.1.0 --dry-run
```

Expected: `G0~G2 全过` + `[dry-run] ...`，且 `.workbench/releases/` 未产生文件、无新 tag。

- [x] **Step 5: 正式发布**

```powershell
python <工作区根>\embedded-toolkit\scripts\release.py --project <工作区根>\stm32f103-adc-oled --tag v1.1.0
git log --oneline -1; git tag -l; git show v1.1.0 --stat
```

Expected: `[OK] 已发布 v1.1.0`；annotated tag 指向含 ALERT 功能的 commit；`git status` 显示 releases/v1.1.0.json 已 staged（入库策略生效）。用户自行决定何时 push 与补 commit 记录文件。

- [x] **Step 6: 反向 A — 脏树拦截**

改任意已跟踪文件不提交 → 重跑 Step 5 命令（换 tag v1.1.1）。
Expected: `G0 失败: 工作树不干净`。还原改动。

- [x] **Step 7: 反向 B — xfail 拦截与豁免留痕**

临时把 FR-SYS-01 改 `"xfail": true, "xfail_reason": "验收反向测试"`，commit 后用 tag v1.1.1 重跑 release：
Expected: `G2 存在未翻转 xfail: FR-SYS-01` 退出码 1；改用 `--allow-xfail` 重跑：
Expected: 通过且记录中 `"xfail_waived": ["FR-SYS-01"]`。随后还原 FR-SYS-01 并 commit，删除 v1.1.1 的记录与 tag（`git tag -d v1.1.1`）保持仓库整洁。

- [x] **Step 8: blink legacy 回归**

```powershell
cd <工作区根>\stm32f103-blink
python <工作区根>\embedded-toolkit\scripts\verify.py
```

Expected: 与基线行为一致（Verdict PASS，无 mode=manifest 字样）——证明回退路径零影响。

---

### Task 8: README 文档收尾

**Files:**
- Modify: `<工作区根>\embedded-toolkit\README.md`（存在则追加节，不存在则新建）

- [x] **Step 1: 追加以下内容**

```markdown
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
```

- [x] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: expectations manifest + release gate usage"
```

## Self-Review 结论（写计划时已核）

- 规格覆盖：§3→Task 2/3，§4→Task 3，§5→Task 4，§6→Task 5，§7→Task 6 Step 1，§8→Task 6，§9→Task 7，§12 基线风险→Task 1。
- 类型一致性：evaluate_expectations 返回键（results/verdict/xpass_ids）在 T3/T4/T5 三处一致；statuses 取值 pass|xfail|xpass|fail 全文一致；release.run_gates/finalize 签名与其测试一致。
- 已知取舍：finalize 的"脏树复核"放行记录文件自身（否则自锁）；Task 7 Step 1 把 spec"红"明确为条目级 XFAIL（套件按 §4 保绿）。

## 执行附录（2026-08-26 实施日回填，含偏差记录）

全部 8 任务完成。与计划文本的偏差：

1. **T4 Step 5**：原计划的 feedback try/except 替换遗漏了挂在同一 try 上的
   `finally: _output()`，首次运行语法错误——修复为顺序调用 `_output`（语义等价）。
2. **T5**：finalize 的 porcelain 需 `-uall`（新仓首发布时目录行会误判 foreign）；
   swd_probe 判据从"返回码+stdout"改为**内容导向**（OpenOCD 关键行在 stderr、
   克隆 ST-Link 退出码不可靠），并补显式 `transport select swd` + 3 次重试
   （对齐 hardfault.py 纪律）。测试 setUp 需配 repo 级 git 身份（本机无全局身份，
   annotated tag 的 tagger 也需要）。
3. **T7 Step 7**：反向 B 种子最初用 FR-SYS-01（横幅每帧都输出）→ 变成 XPASS 在
   **G1 就被拦截**，轮不到 G2——门禁比设计更严的实证；改用不存在的 FR-DEMO-99
   正确触发 G2，`--allow-xfail` 豁免留痕验证通过后已清理。
4. **T7 Step 8（blink 回归）**：Verdict FAIL 为**存量固件问题**（输出止步于
   `[init] LED ... OK`），非本次回归——A/B 对照（基线版 verify.py 同样失败）
   证明 legacy 行为未变；回归目的达成，但 spec §9.7 "照常 PASS" 的预期本身
   建立在未验证的假设上，blink 待独立排查。
5. **T7 硬件中断**：Step 4 前板子 SWD 间歇失联（克隆 ST-Link 接触类问题），
   G0.5 秒级预检如设计拦下；用户重新插拔后恢复。
6. **审计加固轮**（当日第二轮 fresh-checker 审核 M1/M2/L5 后追加）：加载器堵四类
   "烧录后才崩"清单缺陷（cg⇒patterns/预编译正则/JSONDecodeError 转译/NaN 拒绝）、
   release 强制 hex 哈希入档、回滚清理空目录、新增 7 个测试（全套件 36 个）。
