# M-4/L-4 验证缺口小工单实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 销掉总工单 v2 终审遗留两笔：M-4（`--junit-xml` 产物被 GitHub Actions test reporter 实吃）、L-4（`verify.step_flash` 接入 N-3 构造性标记）。

**Architecture:** M-4 纯 CI 配置改动（sim-demo job 加旗标 + `dorny/test-reporter@SHA` 消费步骤），零 Python 新代码；L-4 把 `openocd_run.py` 已有的 N-3 标记常量与缺席判定抽为可导入共享件，`verify.py:step_flash` 串尾追加同一条 echo 并在 rc=0 后过同一校验器。

**Tech Stack:** Python 3.10/3.12（unittest，非 pytest）、GitHub Actions、OpenOCD、ruff。

**Spec:** `docs/specs/2026-09-13-m4-l4-ticket-design.md`（commit `dc12a1a`，已批准）。

## Global Constraints

- 全部工作在 `0912` 分支（当前 HEAD 所在），**不 push**（Executor 永不 push 惯例）。
- F 号已在 spec commit 预占：**F-162 = M-4，F-163 = L-4**；CHANGELOG 条目格式仿既有条目（`- **F-16x (标签) 标题，类型，文件清单**:` + 缩进明细行）。
- 测试框架是 `python -m unittest`：跑单文件 `python -m unittest tests.test_xxx -v`；全量 `python -m unittest discover -s tests`。**仓内无 pytest，勿用 pytest 命令。**
- lint 门禁：`python -m ruff check scripts tests`（或本地 ruff 二进制，见 machine.json；CI 用 astral-sh/ruff-action）。
- import 卫生：`scripts/` 模块 import 期零 IO（`test_import_hygiene` 钉死）；新增 import 行带 `# noqa: E402` 注释时沿用 verify.py 既有风格（括号注明 F 号来源）。
- 中文注释/文档措辞与仓内既有风格一致；CHANGELOG/README 改动与代码同 commit 或紧随其 docs commit，二选一但 F 号账目必须完整。
- commit message 风格：`type(F-16x): 摘要`（见 `git log --oneline -5` 近例）。
- 验收全绿定义：全量 unittest 绿 + ruff 过 + coverage 棘轮（ci.yml 里 `--fail-under=38`）不因本次改动需要下调。

---

### Task 1: N-3 共享件抽取（openocd_run.py，行为零变更）

**Files:**
- Modify: `scripts/openocd_run.py:62-70`（标记常量区，新增一个纯函数）
- Test: `tests/test_openocd_n3_marker.py`（追加共享件用例）

**Interfaces:**
- Consumes: 既有常量 `ACTION_DONE_MARKER = "MARK_ACTION_DONE"`、`_ACTION_DONE_CMD = f"echo {ACTION_DONE_MARKER}"`（`openocd_run.py:68-69`）。
- Produces: `openocd_run.ACTION_DONE_CMD: str`（公开别名，值同 `_ACTION_DONE_CMD`）、`openocd_run.marker_present(combined_output: str) -> bool`。Task 3 消费这两个符号。

- [x] **Step 1: 写失败测试**

在 `tests/test_openocd_n3_marker.py` 末尾追加（沿用该文件既有 import 与风格；先读文件头确认它如何 import openocd_run——通常是 `sys.path.insert` 后 `import openocd_run`）：

```python
class N3SharedContractTests(unittest.TestCase):
    """F-163 (L-4): 标记常量与缺席判定抽为公开共享件 —
    openocd_run 自身与 verify.step_flash 消费同一判据，无双实现漂移。"""

    def test_public_cmd_alias_same_value(self):
        self.assertEqual(openocd_run.ACTION_DONE_CMD, openocd_run._ACTION_DONE_CMD)
        self.assertEqual(openocd_run.ACTION_DONE_CMD,
                         f"echo {openocd_run.ACTION_DONE_MARKER}")

    def test_marker_present_true_only_when_marker_in_output(self):
        self.assertTrue(openocd_run.marker_present(
            "Info : Programming... / Mark action done: MARK_ACTION_DONE"))
        self.assertFalse(openocd_run.marker_present(
            "Info : Programming started but OpenOCD exited early"))

    def test_marker_present_empty_output_false(self):
        self.assertFalse(openocd_run.marker_present(""))
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m unittest tests.test_openocd_n3_marker -v`
Expected: FAIL — `AttributeError: module 'openocd_run' has no attribute 'ACTION_DONE_CMD'`

- [x] **Step 3: 最小实现**

`scripts/openocd_run.py` 第 68-70 行常量区，在 `_ACTION_DONE_CMD` 定义之后、`_WARNING_LINE_RE` 之前插入：

```python
# F-163 (L-4): 公开别名 + 缺席判定纯函数 — verify.step_flash 与 openocd_run
# 两条路径消费同一判据 (构造性证据优先于退出码, N-3 立法原意)。
ACTION_DONE_CMD = _ACTION_DONE_CMD


def marker_present(combined_output: str) -> bool:
    """串尾标记 echo 是否在场 (在场 = 动作脚本真跑到底)。纯函数, import 零 IO。"""
    return ACTION_DONE_MARKER in combined_output
```

注意：`ACTION_DONE_CMD` 若模块顶部有 `__all__` 需同步加入（先检查，无 `__all__` 则不动）。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m unittest tests.test_openocd_n3_marker -v`
Expected: PASS（新 3 例 + 该文件既有全绿——既有 N-3 行为钉不许动）

- [x] **Step 5: 全量回归（行为零变更声明的证据）**

Run: `python -m unittest discover -s tests`
Expected: 全绿（844+3 例）

- [x] **Step 6: Commit**

```bash
git add scripts/openocd_run.py tests/test_openocd_n3_marker.py
git commit -m "refactor(F-163-pre): N-3 标记常量/缺席判定抽公开共享件 — openocd_run 行为零变更 (L-4 第一步)"
```

---

### Task 2: step_flash 测试钉先行（TDD 红）

**Files:**
- Test: `tests/test_verify_failure_paths.py:213-231`（`StepFlashNoArtifactTests` 类后新增一个测试类）

**Interfaces:**
- Consumes: `verify.step_flash(hex_file)`（`verify.py:216`）、`verify.run_cmd(cmd, timeout)`（`verify.py:151`，返回 dict 含 `status/returncode/stdout/stderr`）、Task 1 的 `openocd_run.ACTION_DONE_MARKER`。
- Produces: 三个失败钉（rc=0+标记在场→ok；rc=0+标记缺席→error action_incomplete；rc≠0→旧 error 路径），Task 3 转绿。

- [x] **Step 1: 写失败测试**

`tests/test_verify_failure_paths.py` 中 `StepFlashNoArtifactTests` 类之后新增（文件头已有 `mock`、`tempfile`、`shutil`、`verify` 导入，先读文件头确认可用名，缺什么补什么）：

```python
class StepFlashN3MarkerTests(unittest.TestCase):
    """F-163 (L-4): step_flash 高频真机路径接 N-3 构造性标记 —
    rc=0 只是必要条件; 串尾标记缺席 = OpenOCD 提前退出, 拒绝按成功入账。"""

    def setUp(self):
        old = verify.WORKSPACE
        verify.WORKSPACE = tempfile.mkdtemp()
        self.addCleanup(setattr, verify, "WORKSPACE", old)
        self.addCleanup(shutil.rmtree, verify.WORKSPACE, ignore_errors=True)
        os.makedirs(os.path.join(verify.WORKSPACE, "obj"), exist_ok=True)
        self.hex_rel = "obj/app.hex"
        with open(os.path.join(verify.WORKSPACE, self.hex_rel), "w") as f:
            f.write(":00000001FF\n")

    @mock.patch.object(verify, "run_cmd")
    @mock.patch.object(verify, "_openocd_exe", return_value="openocd")
    def _flash(self, m_exe, m_run, returncode=0, stdout_tail=""):
        m_run.return_value = {"status": "ok" if returncode == 0 else "error",
                              "returncode": returncode,
                              "stdout": stdout_tail, "stderr": ""}
        return verify.step_flash(self.hex_rel), m_run

    def test_rc0_with_marker_ok_and_cmd_carries_echo(self):
        r, m_run = self._flash(stdout_tail="Mark: MARK_ACTION_DONE")
        self.assertEqual(r["status"], "ok")
        cmd = m_run.call_args[0][0]
        self.assertIn("echo MARK_ACTION_DONE", " ".join(cmd))

    def test_rc0_without_marker_rejected(self):
        r, _ = self._flash(stdout_tail="Info : everything looks fine (truncated)")
        self.assertEqual(r["status"], "error")
        self.assertIn("action_incomplete", r["message"])

    def test_nonzero_rc_keeps_legacy_error_path(self):
        r, _ = self._flash(returncode=1, stdout_tail="MARK_ACTION_DONE")
        self.assertEqual(r["status"], "error")
        self.assertNotIn("action_incomplete", r.get("message", ""))
```

实施者注意：`_flash` 的装饰器顺序——被装饰函数收到的 mock 参数按**从下到上**对应装饰器行；若运行发现 `m_exe/m_run` 错位，以实际 unittest 行为为准修正参数名（这是本文件既有测试用 `@mock.patch.object` 时的同款坑，见 `test_hil_origin_guard.py` 用法）。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m unittest tests.test_verify_failure_paths.StepFlashN3MarkerTests -v`
Expected: 三例中至少两例 FAIL（无标记例现状是 rc=0→ok 放行；cmd 无 echo）。若 `test_rc0_with_marker_ok` 也失败于 mock 签名，先修测试脚手架再确认红在实现上。

- [x] **Step 3: Commit（红基线入档，本仓纪律：钉先于实现单独可见）**

```bash
git add tests/test_verify_failure_paths.py
git commit -m "test(F-163): step_flash N-3 标记三态红基线 — rc=0 无标记现状被放行即缺陷本体"
```

---

### Task 3: step_flash 实现转绿 + 文档账目（L-4 收口）

**Files:**
- Modify: `scripts/verify.py:216-233`（`step_flash`）
- Modify: `README.md:386-389`（已知遗留 L-4 条目改写"已闭合"）
- Modify: `CHANGELOG.md`（顶部新增 F-163 条目）
- Test: `tests/test_verify_failure_paths.py`（Task 2 的三例）

**Interfaces:**
- Consumes: Task 1 的 `openocd_run.ACTION_DONE_CMD`、`openocd_run.marker_present`；Task 2 的三例测试。
- Produces: `step_flash` 终态行为——成功判定 = rc==0 且标记在场；标记缺席 error 文本含 `action_incomplete`。

- [x] **Step 1: 实现**

`scripts/verify.py`：

1. import 区（第 50-53 行附近，`from openocd_runtime import ...` 之后）加：

```python
from openocd_run import ACTION_DONE_CMD, marker_present  # noqa: E402  (F-163: N-3 标记共享件)
```

（注意循环 import：openocd_run 不 import verify，方向安全；若 `test_import_hygiene` 报 import 期 IO，检查是否误引了 openocd_run 的重函数。）

2. `step_flash` 的 `cmd` 列表（`verify.py:227-232`）在 `program` 串后追加一个 `-c` 段——把

```python
        "-c", f"program {{{hex_abs}}} verify reset exit"
```

改为

```python
        "-c", f"program {{{hex_abs}}} verify",
        "-c", ACTION_DONE_CMD,
        "-c", "exit",
```

（先 echo 标记再 exit，保证 exit 截胡时标记 echo 不会在场——这正是"脚本没跑完"的构造性证据方向。`program ... verify` 不带 reset 会停在 halt 后状态，reset 由 verify 主流程的 post_reset 步骤负责——**若本地真机冒烟发现 post_reset 语义依赖 program 串内的 reset，则改回 `program {hex} verify reset` 后接 `-c ACTION_DONE_CMD -c exit`，以真机复验 Task 5 结果为准并在 commit 注明。**）

3. `return run_cmd(cmd, timeout=30)` 改为：

```python
    result = run_cmd(cmd, timeout=30)
    if result["status"] == "ok" and not marker_present(
            result.get("stdout", "") + result.get("stderr", "")):
        # F-163 (N-3): exit 0 但串尾标记缺席 = OpenOCD 提前退出, 脚本没跑完 —
        # 不许按成功入账 (构造性证据优先于退出码)
        return {"status": "error",
                "message": ("action_incomplete: 构造性标记缺席 — OpenOCD exit 0 "
                            "但 program 串未跑完 (串尾 echo 未出现), 拒绝按成功入账")}
    return result
```

（OpenOCD 日志实际走 stderr——`run_cmd` 里 F-090 注释可证——所以校验拼 stdout+stderr，与 openocd_run.py 第 305 行 `combined = proc.stderr + "\n" + proc.stdout` 同款。）

- [x] **Step 2: 跑测试转绿**

Run: `python -m unittest tests.test_verify_failure_paths -v`
Expected: 全绿（新三例 + StepFlashNoArtifactTests 两例旧钉不动）

- [x] **Step 3: 全量 + lint**

Run: `python -m unittest discover -s tests` → 全绿
Run: `python -m ruff check scripts tests` → 零违规
（其他 mock `run_cmd`/`step_flash` 的测试若因 cmd 结构断言失败——如 `test_junit_xml.py:169`、`test_hw_lease.py:289`——它们是 mock 层不真跑 cmd，通读报错确认属 mock 兼容问题再最小修 mock，**不许**反向放宽新测试断言。）

- [x] **Step 4: 文档账目**

1. `README.md:386-389` L-4 条目改为（保留条目位置，措辞对齐上方 M-4 条目改写先例风格，M-4 由 Task 4 改）：

```markdown
- **N-3 覆盖洞（审核 L-4）**：✅ **已闭合（F-163, 2026-09-13）**——
  `verify.step_flash` 接入构造性标记共享件（`openocd_run.ACTION_DONE_CMD` /
  `marker_present`），rc=0 且串尾标记在场才算烧录成功；真机复验见 CHANGELOG。
```

2. `CHANGELOG.md` 顶部（F-161 条目上方）新增 F-163 条目，格式对齐既有条目：类型 `feat+test+docs`，文件清单 `openocd_run.py / verify.py / tests/test_openocd_n3_marker.py / tests/test_verify_failure_paths.py / README / CHANGELOG`，明细行记：共享件抽取、cmd 串尾 echo、缺席判定、（Task 5 完成后回填真机结论）。

- [x] **Step 5: Commit**

```bash
git add scripts/verify.py README.md CHANGELOG.md tests/test_verify_failure_paths.py
git commit -m "feat+test+docs(F-163): step_flash 接入 N-3 构造性标记 — rc=0 且标记在场才算烧成 (总工单遗留 L-4 闭合)"
```

---

### Task 4: M-4 CI 接线（sim-demo job 产 JUnit + reporter 消费 + 文档账目）

**Files:**
- Modify: `.github/workflows/ci.yml:110-118`（sim-demo job）
- Modify: `README.md:383-385`（已知遗留 M-4 条目）
- Modify: `CHANGELOG.md`（F-162 条目）

**Interfaces:**
- Consumes: `verify.py --junit-xml <path>` 旗标（`verify.py:493`，F-147 既有，零代码改动）；`dorny/test-reporter@v3.0.0` = commit `a43b3a5f7366b97d083190328d2c652e1a8b6aa2`（2026-09-13 经 `gh api repos/dorny/test-reporter/git/tags/a6ddd83...` 解 annotated tag 实证）。
- Produces: CI 产物 `build/junit-sim.xml` + PR 检查 "Sim Verify Results"。

- [x] **Step 1: 改 sim-demo job**

sim-demo job 顶部（`runs-on: ubuntu-latest` 之后）加权限声明（dorny/test-reporter 要写 check run；仓若无全局 restrictive permissions 也应显式最小化）：

```yaml
    permissions:
      contents: read
      checks: write
      pull-requests: read   # PR 上下文下写注释用
```

第 110-113 行 verify 步骤改为：

```yaml
      - name: sim-demo end-to-end verify (build → qemu sim → judge)
        run: |
          set -o pipefail
          python scripts/verify.py --project examples/sim-demo --json --junit-xml build/junit-sim.xml --timeout 20 | tee verify-result.json
```

第 116-118 行 evidence 步骤之后追加：

```yaml
      # F-162 (审核 M-4 销账): 外部 reporter 实吃 --junit-xml 产物。
      # dorny/test-reporter v3.0.0, SHA 锁定 (供应链纪律: 升级走 CHANGELOG,
      # 只升不降): a43b3a5f7366b97d083190328d2c652e1a8b6aa2
      # 解引用核验: gh api repos/dorny/test-reporter/git/tags/<tag-object-sha>
      - name: Publish test report (dorny/test-reporter@v3.0.0, SHA-pinned)
        if: always()
        continue-on-error: true
        uses: dorny/test-reporter@a43b3a5f7366b97d083190328d2c652e1a8b6aa2
        with:
          name: Sim Verify Results
          path: build/junit-sim.xml
          reporter: java-junit
```

说明（写进 commit body 即可，yaml 注释已够）：`if: always()` 让失败运行的 XML 也被消费（M-4 要验证的就是 reporter 吃得下四态混合的产物）；`continue-on-error: true` 防 reporter 自身故障把 CI 判红掩盖真因——**销账判定由人盯 PR 页**（Task 6）。

- [x] **Step 2: 本地验证 XML 产物可产出**

Run: `python scripts/verify.py --project examples/sim-demo --json --junit-xml build/junit-sim-local.xml --timeout 20`
Expected: 退出码按 verify 四态判定（本机 QEMU 11.1.0 已装，09-13 环境事实）；`build/junit-sim-local.xml` 存在且 `python -c "import xml.etree.ElementTree as ET; ET.parse('build/junit-sim-local.xml')"` 零输出。
（`build/` 若被 .gitignore 覆盖正好——产物本就不入库；确认 `git status` 不出现该文件。）

- [x] **Step 3: 文档账目**

1. `README.md:383-385` M-4 条目改为：

```markdown
- **F-147 遗留（审核 M-4）**：✅ **闭合中（F-162, 2026-09-13）**——CI sim-demo
  job 已加 `--junit-xml` 产物 + `dorny/test-reporter`（SHA 锁定）消费步骤；
  销账以首个真实 PR 的 reporter 检查结果为凭（见 CHANGELOG F-162 复验记录）。
```

（Task 6 PR 复验通过后，该条目在收尾 commit 里把"闭合中"改"已闭合"并回填检查名/URL——本仓"欠账待首个 reporter 消费验证后销账"的口径，登记不藏。）

2. `CHANGELOG.md` 顶部新增 F-162 条目：类型 `ci+docs`，文件 `ci.yml / README / CHANGELOG`，明细记 SHA 锁定值、解引用核验命令、`if: always()` + `continue-on-error` 两个决策的理由。

- [x] **Step 4: YAML 静态自检**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8')); print('yaml ok')"`（若本机无 pyyaml，用 `python -m unittest tests.test_ci_config 2>/dev/null || true` 先查仓内是否已有 CI 配置解析测试——grep `ci.yml` 于 tests/，有则跑它。）
Expected: `yaml ok` 或既有配置测试绿。

- [x] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml README.md CHANGELOG.md
git commit -m "ci+docs(F-162): sim-demo 产 --junit-xml + test-reporter(SHA锁定) 消费 — M-4 销账接线"
```

---

### Task 5: L-4 真机复验（adc-oled 在位闭环）

**Files:**
- 无代码改动（例外：program 串 reset 次序若被真机推翻，按 Task 3 Step 1 括注回改并单独 commit）。
- Modify: `CHANGELOG.md`（F-163 条目回填真机结论行）。

**Interfaces:**
- Consumes: Task 3 的 step_flash 终态；adc-oled 工程（`<d-claude-root>\stm32f103-adc-oled`，`machine.json` 路径源）；ST-Link 在位。
- Produces: 真机证据——flash 带标记 PASS、`evidence=hardware_validated`、post_reset=ok。

- [x] **Step 1: 真机跑闭环**

Run: `python scripts/verify.py --project <d-claude-root>\stm32f103-adc-oled --json --timeout 60`（`<d-claude-root>` 即本机 `D:\` 工作区根，执行时替换）
Expected: status=ok、flash 步骤成功且无 action_incomplete、`evidence=hardware_validated`、post_reset=ok（对齐 09-13 已知基线：自动项 4/4，ALERT 捕获依赖旋钮状态）。
**注意**：09-13 记录显示"首跑自动项 3/3，ALERT 需人工拧满旋钮到阈值上（mv≈3300）"——若 ALERT 项 FAIL 而 flash/capture 链全绿，属已知人工交互缺口，不是本工单回归；判定只看 flash 路径带标记是否畅通。
**克隆 ST-Link 纪律**（[[stlink-clone-intermittent]]）：SWD 连不上先问用户"是不是你拔了"，不猜软件。

- [x] **Step 2: 反证抽查（构造性证据的存在意义）**

真机 PASS 后，一次性手改 `step_flash`  cmd 把 `ACTION_DONE_CMD` 段删掉跑同一条命令——预期 flash 报 `action_incomplete` rc=0 拒绝入账。**立刻还原**（`git checkout scripts/verify.py` 或反向手改），此步不进任何 commit。
（无板可用时的降级口径：mock 三态钉即验收证据，本步标 "skipped: no hardware" 记入 CHANGELOG——但当前板在位，默认必须跑。）

- [x] **Step 3: CHANGELOG 回填 + Commit**

F-163 条目追加一行明细：`真机复验 2026-09-13: adc-oled verify ok, flash 带标记 PASS (action_incomplete 路径人工反证一次); post_reset=ok, evidence=hardware_validated`（按实测措辞）。

```bash
git add CHANGELOG.md
git commit -m "docs(F-163): adc-oled 真机复验回填 — L-4 销账证据"
```

---

### Task 6: M-4 PR 实吃验证 + 收尾销账

**Files:**
- Modify: `README.md`（M-4 条目"闭合中"→"已闭合"）
- Modify: `CHANGELOG.md`（F-162 复验记录）
- Modify: 记忆账本 `<user-home>\.claude\projects\<workspace>\memory\embedded-toolkit-ticket-2026-09-13.md`（遗留清单勾销 M-4/L-4 两行）

**Interfaces:**
- Consumes: Task 4 的 CI 改动经**一次 push** 才可见——⚠️ 本工单唯一需要用户拍板的例外：0912 惯例不 push，但 reporter 实吃必须发生在 GitHub 远端 PR 上。执行到本步时**停下请示**，由维护者决定 push 方式（直推 0912 触发分支 CI 不行——test-reporter 的 PR 评论模式需要 PR 上下文；可行路径是 push 0912 后开 PR 到 master，或维护者本地 `gh workflow run`——`on: push/PR` 事件下 push 触发的 run 里 test-reporter 也能以 `github-check` 检查形式出结果）。
- Produces: 销账凭据（PR 检查 "Sim Verify Results" 截图级文字记录进 CHANGELOG）。

- [x] **Step 1: 请示 push 授权**（本计划唯一人工门）

向维护者报告：代码全部就绪、本地验收全绿，M-4 销账需要一次 push + PR/分支 run 观察。等待指示后再继续。

- [x] **Step 2: 观察 reporter 消费结果**

push 后 `gh run watch` 或 `gh run list --workflow CI` → sim-demo job 的 "Publish test report" 步骤绿；PR/run 页面出现 "Sim Verify Results" 检查、annotated 测试摘要（四态用例列表）= **首个外部 reporter 实吃**成立。
若 reporter 报解析错（java-junit 格式不认某边界）：抓 `junit-sim.xml` 实际内容与 dorny 格式期望比对，修 `junit_xml.py` 的生成侧（那是真缺陷销账副产品，加回归钉），重跑。
若 reporter 报权限错（`Resource not accessible by integration`）：job 缺 `checks: write`——在 sim-demo job 加顶层 `permissions: {checks: write, pull-requests: read, contents: read}` 后重推，此改动并入 F-162 账目。

- [ ] **Step 3: 销账三件套**

1. README M-4 条目 → "已闭合（F-162, 2026-09-13, 首个实吃 run: `<run URL>`）"；
2. CHANGELOG F-162 条目追加复验记录行；
3. 记忆账本 `embedded-toolkit-ticket-2026-09-13.md` 遗留欠账节：M-4、L-4 两行各加删除线 + "✅ 2026-09-13 F-162/F-163 闭合"（其余 D-2、arXiv 两条保留）。

```bash
git add README.md CHANGELOG.md
git commit -m "docs(F-162/F-163): 销账 — M-4 reporter 实吃成立 + L-4 真机证据齐 (总工单 v2 遗留 2/4 清)"
```

（记忆文件在仓外，不入 git。）

- [ ] **Step 4: fresh-checker 终审（本仓收官惯例）**

调用 `fresh-checker` skill 对两笔闭合做无上下文终审；C/H 级发现回 Task 修，M/L 级视措辞决定修或登记。终审结论追加 CHANGELOG。

> 注（fresh-checker 修复波, 2026-09-13）：Step 3/4 未全勾——终审已发生（C0 H0 M4 L3），但 Step 3 销账三件套经 M-1 订正回退为"闭合中"；check run 复观待终态配置 push 后下轮。

---

## 依赖顺序

Task 1 → 2 → 3 → 5（L-4 链）；Task 4 → 6（M-4 链）。两链独立可并行，但 Task 6 Step 1 的人工门在最后——整体收口顺序：1→2→3→4→5→6。
