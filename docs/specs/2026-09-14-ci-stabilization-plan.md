# CI 稳定化小单（F-164/F-165）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉两笔已登记预置债，让 master CI 复绿——gcc_build 预检平台化（ubuntu 上 `.exe` 硬编码必败）+ 两枚墙钟计时钉改注入假时钟。

**Architecture:** F-164 单点替换 `main()` 预检两行为 `shutil.which` 判定（Windows 等价由 PATHEXT 覆盖）；F-165 纯测试侧改造——patch 被测模块命名空间的 `datetime`/`time` 为虚拟钟，把"赌时钟不抖"的断言换成零容差行为钉。

**Tech Stack:** Python 3.10/3.12（unittest，非 pytest）、GitHub Actions、ruff。

**Spec:** `docs/specs/2026-09-14-ci-stabilization-design.md`（commit `b268c93`，已批准）。

## Global Constraints

- 分支 `ci-stabilize-20260914`（自 master `fc8fc7a` 切出，已建）；push 需维护者另行授权（Task 6 的人工门）。
- F 号：**F-164 = gcc_build 预检平台化，F-165 = 计时钉**；CHANGELOG 两条目分记，格式仿 F-162/F-163 近例。
- 测试框架 `python -m unittest`；跑单文件 `python -m unittest tests.test_xxx -v`；全量 `python -m unittest discover -s tests`（当前基线 853 例 OK, skipped=6）。
- lint：`python -m ruff check scripts tests` 零违规。
- F-089 卫生钉：任何 tracked .py/.md 改动行不得含裸 `<d-claude-root>`/`<d-claude-root>` 形态（用 `<d-claude-root>` 占位）。
- 中文注释风格与仓内一致；commit message `type(F-16x): 摘要`。
- 不放宽既有断言语义；生产代码最小改动（F-165 原则上只动测试文件）。
- 验收终判在远端 CI（Task 5），本地全绿只是前置。

---

### Task 1: F-164 gcc_build 预检平台化

**Files:**
- Modify: `scripts/gcc_build.py`（import 块 + main() 预检段，约 206-212 行）
- Test: `tests/test_gcc_build.py`（末尾追加一个测试类；`unittest.main()` 保持在最后）

**Interfaces:**
- Consumes: `machine` dict（`load_machine()` 返回值，测试可 patch `gcc_build.load_machine`）；预检错误收集式输出 `{"status":"error","error":{"code":"precheck","message":...}}`（经 `output_json` 打 stdout）。
- Produces: 预检终态判定式 = `shutil.which("arm-none-eabi-gcc", path=gcc_path)` 与 `shutil.which(make_exe)`；Task 5 的远端 sim-demo job 转绿依赖此。

- [ ] **Step 1: 写失败测试（预检形态钉 + 三枚 mock 行为钉）**

`tests/test_gcc_build.py` 追加（先读文件头：已有 `os/sys/unittest`、`sys.path.insert` + `import gcc_build`；需补 `import io, json, tempfile, contextlib` 与 `from unittest import mock`——按文件头缺什么补什么）。注意 `unittest.main()` 行必须在全部类定义之后（F-125 钉），把新类插在它前面：

```python
class PrecheckPlatformPortableTests(unittest.TestCase):
    """F-164: 预检去 .exe 硬编码 —— ubuntu runner 上 arm-none-eabi-gcc 无后缀,
    旧判定 (Path(gcc_path)/"arm-none-eabi-gcc.exe").exists() 必败, sim-demo job
    速败 errors=-1。新判定统一 shutil.which。"""

    def _run_main(self, machine, which_sideeffects):
        """驱动 main() 到预检出口, 返回解析后的 JSON 信封。
        which_sideeffects: 传给 mock.patch 的 side_effect/return_value 字典。"""
        tmp = tempfile.mkdtemp()
        mk = os.path.join(tmp, "Makefile")
        with open(mk, "w") as f:
            f.write("TARGET = t\n")
        argv = ["gcc_build", "build", "--project", mk, "--json"]
        buf = io.StringIO()
        with mock.patch.object(gcc_build, "load_machine", return_value=machine), \
             mock.patch.object(gcc_build.sys, "argv", argv), \
             mock.patch.object(gcc_build.shutil, "which", **which_sideeffects), \
             contextlib.redirect_stdout(buf):
            gcc_build.main()
        return json.loads(buf.getvalue())

    def _machine(self):
        return {"gcc_path": "/usr/bin", "make_exe": "/usr/bin/make",
                "openocd_exe": "openocd"}

    def test_gcc_not_found_reports_gcc_path_invalid(self):
        env = self._run_main(self._machine(),
                             {"side_effect": lambda *a, **k: None})
        self.assertEqual(env["error"]["code"], "precheck")
        self.assertIn("gcc_path invalid", env["error"]["message"])

    def test_make_not_found_reports_make_exe_invalid(self):
        # gcc 查得到、make 查不到 → 只报 make_exe
        env = self._run_main(
            self._machine(),
            {"side_effect": lambda name, *a, **k:
             "/usr/bin/arm-none-eabi-gcc" if "gcc" in str(name) else None})
        self.assertEqual(env["error"]["code"], "precheck")
        self.assertIn("make_exe invalid", env["error"]["message"])
        self.assertNotIn("gcc_path invalid", env["error"]["message"])

    def test_both_found_passes_precheck(self):
        # 双命中 → 不再报 precheck（会走 _run_make, mock 掉防真跑）
        env_side = {"return_value": "/usr/bin/arm-none-eabi-gcc"}
        tmp = tempfile.mkdtemp()
        mk = os.path.join(tmp, "Makefile")
        with open(mk, "w") as f:
            f.write("TARGET = t\n")
        buf = io.StringIO()
        import subprocess as sp
        with mock.patch.object(gcc_build, "load_machine",
                               return_value=self._machine()), \
             mock.patch.object(gcc_build.sys, "argv",
                               ["gcc_build", "build", "--project", mk, "--json"]), \
             mock.patch.object(gcc_build.shutil, "which", **env_side), \
             mock.patch.object(gcc_build, "_run_make",
                               return_value=sp.CompletedProcess([], 0)), \
             contextlib.redirect_stdout(buf):
            gcc_build.main()
        env = json.loads(buf.getvalue())
        self.assertNotEqual(env.get("error", {}).get("code"), "precheck")

    def test_no_bare_exe_literal_in_precheck(self):
        # F-159 AST 形态钉: main() 源码不再含 "arm-none-eabi-gcc.exe" 字面量
        import ast
        src = open(gcc_build.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        main_fn = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "main")
        literals = [node.value for node in ast.walk(main_fn)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertFalse([s for s in literals if ".exe" in s],
                         "main() 预检段仍有 .exe 字面量 — F-164 回潮")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest tests.test_gcc_build.PrecheckPlatformPortableTests -v`
Expected: 4 例全 FAIL/ERROR——前三枚死于现实现不走 `gcc_build.shutil`（AttributeError 或 precheck 消息不含预期键），形态钉死于字面量仍在。若某例意外绿，先核对死因是否实现路径不同再进 Step 3。

- [ ] **Step 3: 实现**

`scripts/gcc_build.py`：

1. import 块（第 16-22 行区）按字母序补 `import shutil`。
2. 预检两行（约 209-211）替换：

```python
    # F-164: 预检平台化 —— 旧判定写死 "arm-none-eabi-gcc.exe", ubuntu runner
    # 上二进制无后缀必败 (sim-demo job 速败 errors=-1)。统一 shutil.which:
    # nt 下自动试 PATHEXT(.exe); POSIX 查存在+可执行位; 裸名查 PATH, 带目录查该路径。
    gcc_ok = shutil.which("arm-none-eabi-gcc",
                          path=machine.get("gcc_path") or "")
    make_ok = shutil.which(machine.get("make_exe") or "")
    if not machine.get("gcc_path") or not gcc_ok:
        errors.append(f"gcc_path invalid in machine.json: {machine.get('gcc_path')}")
    if not machine.get("make_exe") or not make_ok:
        errors.append(f"make_exe invalid in machine.json: {machine.get('make_exe')}")
```

- [ ] **Step 4: 跑测试转绿**

Run: `python -m unittest tests.test_gcc_build -v` → 全绿（新 4 + 既有）

- [ ] **Step 5: 全量 + ruff**

`python -m unittest discover -s tests` → 857 全绿（853+4，skipped=6）；`python -m ruff check scripts tests` → 零违规。

- [ ] **Step 6: 本机回归确认 Windows 行为等价**

Run: `python scripts/gcc_build.py build --project examples/sim-demo --json`
Expected: status=ok（本机 machine.json 的 gcc_path 真实存在，which 判定应与旧式结果一致）——这是 Windows 等价性的活证据。

- [ ] **Step 7: Commit**

```bash
git add scripts/gcc_build.py tests/test_gcc_build.py
git commit -m "fix+test(F-164): gcc_build 预检平台化 shutil.which — 去 .exe 硬编码, ubuntu sim-demo 速败根因闭合"
```

---

### Task 2: F-164 账目（README/CHANGELOG）

**Files:**
- Modify: `README.md`（已知遗留"计时脆钉/sim-demo build_failed"两笔预置债条目中 sim-demo 那条改写）
- Modify: `CHANGELOG.md`（顶部新增 F-164 条目）

- [ ] **Step 1: README**

"预置债"两条 bullet（F-162 副产物条目，README.md 约 390-399 行）中的 sim-demo 条改写为已闭合措辞（保留登记原文可追溯，append 式，比照 M-4 条目"闭合中→已闭合"订正风格）：

```markdown
- **F-162 副产物（预置债 D-3 候选）**：✅ **已闭合（F-164, 2026-09-14）**——根因
  = `gcc_build.py` 预检写死 `arm-none-eabi-gcc.exe`（ubuntu 无后缀必败, errors=-1
  速败）；已改 `shutil.which` 平台判定（nt 走 PATHEXT 等价, 本机回归绿 + 4 枚
  mock/AST 钉）。**远端复绿以 F-164/F-165 合并 PR 的 CI 全绿为终判**（挂本单 Task 5）。
```

计时脆钉那条**本任务不动**（Task 4 的 F-165 收口时改）。

- [ ] **Step 2: CHANGELOG**

顶部新增 F-164 条目（格式仿 F-163 近例）：类型 `fix+test+docs`；文件清单 `gcc_build.py / tests/test_gcc_build.py / README / CHANGELOG`；明细含：根因行、which 替换、4 枚钉、Windows 等价活证据（Step 6 实测结果措辞）。

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs(F-164): 预检平台化记账 + sim-demo 预置债条目闭合改写在案 (远端复绿终判挂 Task 5)"
```

---

### Task 3: F-165a runtime_contract 计时钉去墙钟

**Files:**
- Test: `tests/test_runtime_contract.py`（改 `test_make_timing_is_name_collision_not_dup`，约 117-131 行）

**Interfaces:**
- Consumes: `serial_runtime.make_timing(start_time: float)`（`serial_runtime.py:151`——内部用 `datetime.now().timestamp()` 墙钟 + `now_iso()`）。
- Produces: 零墙钟依赖的确定性钉。

- [ ] **Step 1: 改造测试（先跑确认对现实现绿 = 形态锁非红基线；若红说明 patch 点位错，修注入而非改断言）**

```python
    def test_make_timing_is_name_collision_not_dup(self):
        # 实测: ser.make_timing(start_time) 现算耗时; wb.make_timing(started_at,
        # elapsed_ms) 做格式化 —— 同名异物, 各自的钉分别锁形状
        # F-165: 旧版喂 time.time()-1.0 再赌 elapsed_ms>=1000 —— 墙钟版断言,
        # CI NTP 微调回拨即 999 (0912 首跑实锤)。改注入假 datetime: 耗时逐字 =1000。
        import datetime as _dt
        t0 = 1_800_000_000.0  # 2026-09 附近的固定 epoch, 远离 pre-epoch 边界
        class _FakeDT:
            @staticmethod
            def now():
                return _dt.datetime.fromtimestamp(t0 + 1.0, _dt.timezone.utc)
            @staticmethod
            def fromtimestamp(ts):
                return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc)
        with mock.patch.object(serial_runtime, "datetime", _FakeDT):
            t_ser = serial_runtime.make_timing(t0)
        self.assertEqual(set(t_ser), {"started_at", "finished_at", "elapsed_ms"})
        self.assertEqual(t_ser["elapsed_ms"], 1000,
                         "假时钟下耗时必须逐字 1000 (墙钟回潮即红)")
        t_wb = wb_runtime.make_timing("2026-09-01T00:00:00+08:00", 123)
        self.assertEqual(t_wb["started_at"], "2026-09-01T00:00:00+08:00",
                         "wb 版 started_at 逐字透传 (ser 版是换算出来的)")
        self.assertEqual(t_wb["elapsed_ms"], 123)
```

实施者核对点：`serial_runtime` 模块内 `make_timing` 实际引用的名字是 `datetime`（`from datetime import datetime` 还是 `import datetime`？）——先读 `serial_runtime.py` 头部 import 形态；若是 `from datetime import datetime`，则 patch 目标应为 `serial_runtime.datetime` 且 `_FakeDT` 需直接冒充 datetime 类（`now()`/`fromtimestamp()` 两个 classmethod 即可，上面代码已按此写）。`now_iso()` 走 `runtime_common`，不受 patch 影响，键存在性断言即可。

- [ ] **Step 2: 聚焦 + 全量**

`python -m unittest tests.test_runtime_contract -v` → 全绿；全量 857 绿。

- [ ] **Step 3: Commit**

```bash
git add tests/test_runtime_contract.py
git commit -m "test(F-165): runtime_contract 计时钉假时钟化 — 999<1000 墙钟抖动根除"
```

---

### Task 4: F-165b state_write_lock 降解钉假时钟化 + F-165 账目

**Files:**
- Test: `tests/test_state_write_lock.py`（改 `test_timeout_degrades_honestly`，约 98-119 行）
- Modify: `README.md`（计时脆钉预置债条目改写）
- Modify: `CHANGELOG.md`（F-165 条目）

**Interfaces:**
- Consumes: `runtime_common` 命名空间内 `time`（`runtime_common.py:160-209` 用 `time.time()`/`time.sleep(0.05)`）、`_state_lock_is_stale`、`_STATE_LOCK_THREADS`。
- Produces: 零真实等待的降解路径行为钉。

- [ ] **Step 1: 确认陈旧锁偷取另有其钉**

Grep `tests/test_state_write_lock.py` 找 stale/超龄 锁回收测试。若缺席，本任务顺手补一枚最小钉（stale=True → 锁被 unlink 重取 → 结束后释放），因为改造后降解钉将 `_state_lock_is_stale` patch 成恒 False，偷取路径不能失去覆盖。已有则在报告注明"偷取钉在场"。

- [ ] **Step 2: 改造降解钉**

```python
    def test_timeout_degrades_honestly(self):
        """F-165: 新鲜他人锁 → 虚拟时钟下等满 timeout 降级放行且 stderr 留痕。
        旧版真 sleep(0.05)+真 0.5s + elapsed>=0.4 墙钟下界 = CI 抖动源
        (ubuntu 实测翻车)。注入假 time: 轮询次数与降解时点全确定。"""
        ws = _fresh_ws()
        lock = os.path.join(ws, ".workbench", "state.json.lock")
        with open(lock, "w") as f:
            f.write("999999" if os.name == "nt" else str(os.getpid() + 1000))
        clock = {"t": 1000.0}
        sleeps = []
        def fake_time():
            return clock["t"]
        def fake_sleep(s):
            sleeps.append(s)
            clock["t"] += s
        real_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            with mock.patch.object(runtime_common, "time") as m_t, \
                 mock.patch.object(runtime_common, "_state_lock_is_stale",
                                   return_value=False):
                m_t.time.side_effect = fake_time
                m_t.sleep.side_effect = fake_sleep
                t_entered = []
                with runtime_common.state_write_lock(ws, timeout=0.5):
                    t_entered.append(True)
            msg = sys.stderr.getvalue()
        finally:
            sys.stderr = real_stderr
        self.assertEqual(t_entered, [True], "降解后上下文必须正常放行恰好一次")
        self.assertIn("降级", msg)
        # deadline=1000.5, 每跳 0.05: 恰 10 次轮询 sleep 后 time>=deadline
        self.assertEqual(sleeps, [0.05] * 10, "假时钟下轮询节拍必须精确")
        self.assertEqual(clock["t"], 1000.5)
        # 降解路径不删他人锁 (finally 仅在 acquired=True 时 unlink)
        self.assertTrue(os.path.exists(lock), "外来锁不得被降解路径删除")
        with open(lock) as f:
            self.assertIn("999999" if os.name == "nt" else str(os.getpid() + 1000),
                          f.read())
```

实施者核对点：①`runtime_common` 内 `time.time()` 与 `time.sleep()` 均经模块属性调用（先读 `runtime_common.py` 头部 import 形态确认 `import time`；若是 `from time import ...` 需调整 patch 目标）；②`_STATE_LOCK_THREADS.acquire(timeout=0.5)` 走真 threading——单测进程内无竞争瞬间拿到，不受假 time 影响；③计数 10 次 = `0.5/0.05`，若实现里 deadline 判定与 sleep 顺序使计数为 9 或 11，按实际节拍常数修正期望值并在报告说明推导（节拍语义不变：轮询直到虚拟 deadline）。

- [ ] **Step 3: 聚焦 + 全量**

`python -m unittest tests.test_state_write_lock -v` → 全绿；全量 857（+可能的偷取钉 +1=858）绿。

- [ ] **Step 4: 文档账目**

README 计时脆钉条目改写：

```markdown
- **计时脆弱钉（预置债）**：✅ **已闭合（F-165, 2026-09-14）**——两枚墙钟钉
  （`test_runtime_contract` ser 版耗时 / `test_state_write_lock` 降解下界）
  改注入假时钟: 零容差逐字断言, 零真实等待; 墙钟回潮即红。远端复绿终判挂
  本单合并 PR CI。
```

CHANGELOG 新增 F-165 条目：类型 `test+docs`；文件 `test_runtime_contract.py / test_state_write_lock.py / README / CHANGELOG`；两子项各记旧墙钟机理一行 + 新假时钟契约一行；若有补偷取钉记入。

- [ ] **Step 5: Commit**

```bash
git add tests/test_state_write_lock.py README.md CHANGELOG.md
git commit -m "test+docs(F-165): state_write_lock 降解钉假时钟化 + 计时预置债销账在案"
```

---

### Task 5: 远端复绿终判（人工门）

**Files:** 无代码改动。

- [ ] **Step 1: 请示 push**（比照 F-162 惯例）：报告本地 857/858 全绿 + ruff 过，请求 push `ci-stabilize-20260914` + 开 PR → master。
- [ ] **Step 2: 观察 PR CI**：全 job 绿 = 销账终判。特别盯：sim-demo job 转绿（F-164 生效实证）；若 sim-demo 转在 capture 段红 → 触发 spec 止损条款（定位 + README 新预置债登记 + CHANGELOG 注记，不强修）。
- [ ] **Step 3: 维护者 PR 页合并**（用户操作，比照 PR #8 流程）；合并后本地 master ff 同步 + 分支删除。
- [ ] **Step 4: CHANGELOG 终判回填 commit**（docs-only：远端全绿 run URL 入 F-164/F-165 条目）。
- [ ] **Step 5: 记忆账本同步**：`embedded-toolkit-ticket-2026-09-13.md` 预置债两行勾销 ✅；MEMORY.md 行更新。
