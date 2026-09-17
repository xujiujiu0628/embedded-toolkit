# ESP32-S3 最小闭环试点 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `<d-claude-root>\esp32s3-hello` 工程内运行 `python <toolkit>/scripts/verify.py`，跑通 ESP32-S3 的 build → flash → capture → verify 全链路并 PASS（STM32 缺省路径零破坏）。

**Architecture:** embedded-toolkit 新增 `esp_runtime.py`（idf.py / esptool / UART 采集三个后端实现），verify.py 三个既有派发点（`step_build` / `step_flash` / capture backend if-elif）各加一分支；缺省配置行为逐字节不变。试点工程是标准 ESP-IDF 工程 + `.workbench/config.json` 薄配置。

**Tech Stack:** ESP-IDF v5.4.4（Xtensa GCC 工具链）、esptool（IDF 自带）、pyserial 3.5（已装）、Python 3.14 + unittest/pytest、PowerShell 子进程封装。

**Spec:** `docs/specs/2026-09-16-esp32s3-pilot-design.md`（本文档与其同分支入库；执行时两份一起读）

## Global Constraints

- **分支纪律**：所有 toolkit 提交只落在 `feat/esp32s3-pilot`；**不 push、不 merge master**。`esp32s3-hello` 是独立 git 仓库，同样只建本地分支主线。
- **工单号**：本特性统一记 **F-174**，commit 前缀 `feat(F-174):` / `test(F-174):` / `docs(F-174):`。
- **机器路径唯一合法源**：所有 ESP 绝对路径只进 `machine.json`（键 `esp_idf_path` / `esp_tools_dir`），脚本内不得硬编码 `D:\...`。
- **缺省零破坏**：`builder` 缺省 gcc、`flash.backend` 缺省 openocd、`capture.backend` 缺省 semihosting——不配置时行为与今日 master 完全一致，Task 3-5 各有一个"缺省回归钉"测试负责证明。
- **测试基线**：每个任务收尾前 `python -m pytest tests -q` 必须全绿（当前 860 collected，只增不减）；`python -m ruff check scripts tests` 零新告警（ruff 规则集 E/F，E402/E501 白名单在 `ruff.toml`）。
- **注释风格**：中文注释，与仓内 F-xxx 惯例一致（说明"为什么"，如 F-090"只信 returncode"）。
- **commit 署名**：每条 message 末尾空一行后加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- **判定纪律**：子进程成败只信 returncode（F-090 同源教训）；超时必须有 message，不许裸 traceback 出 main。

## File Structure

```
embedded-toolkit/
  machine.example.json                 改: +esp_idf_path/+esp_tools_dir 占位键   (Task 1)
  scripts/esp_runtime.py               新建: ESP 三后端 + panic 文本标记        (Task 2-5 递增)
  scripts/verify.py                    改: step_build / step_analyze / step_flash /
                                          _run_capture_step 四处派发            (Task 3-5)
  tests/test_esp_runtime.py            新建: esp_runtime 全函数 host 单测       (Task 2-5)
  tests/test_verify_esp_dispatch.py    新建: verify 派发 + 缺省回归钉           (Task 3-5)
docs/specs/2026-09-16-esp32s3-pilot-{design,plan}.md   入档 (Task 1)

<d-claude-root>\esp32s3-hello\               新建独立工程仓库                         (Task 6)
  CMakeLists.txt  sdkconfig.defaults  .gitignore
  main/CMakeLists.txt  main/hello_main.c
  .workbench/config.json

<d-claude-root>\vendor\esp-idf\              ESP-IDF v5.4.4（工具链本体，不入库）     (Task 1)
<d-claude-root>\vendor\esp-idf-tools\        IDF_TOOLS_PATH 指向处                   (Task 1)
<d-claude-root>\README.md                    改: hw-projects 分类表 +1 行            (Task 6)
```

---

### Task 1: 安装 ESP-IDF v5.4.4 + machine.json 键位

**Files:**
- Create: `<d-claude-root>\vendor\esp-idf\`（git clone）、`<d-claude-root>\vendor\esp-idf-tools\`（install.ps1 产物）
- Modify: `machine.example.json`（+两键占位）、`machine.json`（本机真实路径，**不入 git**）
- Create: `docs/specs/2026-09-16-esp32s3-pilot-plan.md`（本文件入库）

**Interfaces:**
- Consumes: 无
- Produces: `machine.json` 键 `esp_idf_path: str`（IDF 根）、`esp_tools_dir: str`（IDF_TOOLS_PATH）；shell 可用 `. <d-claude-root>\vendor\esp-idf\export.ps1` 后 `idf.py --version` 输出 `ESP-IDF v5.4.4`

- [ ] **Step 1: 克隆 IDF（长任务，放后台）**

```powershell
git clone --recursive -b v5.4.4 https://github.com/espressif/esp-idf.git <d-claude-root>\vendor\esp-idf
```

若 GitHub 速率不可接受改用镜像（镜像 tag 有延迟，先确认 `v5.4.4` 存在）：`https://gitee.com/mirrors/esp-idf`。
注意：`--recursive` 子模块约 1GB 级，单命令超时就用 `run_in_background` 后轮询 `git -C <d-claude-root>\vendor\esp-idf submodule status | findstr /c:"-"`（行首 `-` = 未初始化计数归零为止）。

- [ ] **Step 2: 安装工具链（只装 esp32s3，省 GB）**

```powershell
$env:IDF_GITHUB_ASSETS = "dl.espressif.cn/github_assets"   # 国内镜像拉工具二进制
$env:IDF_TOOLS_PATH = "<d-claude-root>\vendor\esp-idf-tools"
cd <d-claude-root>\vendor\esp-idf
.\install.ps1 esp32s3
```

- [ ] **Step 3: 验证安装**

```powershell
$env:IDF_TOOLS_PATH = "<d-claude-root>\vendor\esp-idf-tools"
cd <d-claude-root>\vendor\esp-idf; . .\export.ps1; idf.py --version
```

Expected: `ESP-IDF v5.4.4`。失败 = 后续全阻塞，先修到这行为绿色才继续。

- [ ] **Step 4: machine.json / machine.example.json 加键**

`machine.json`（本机文件）与 `machine.example.json`（入库模板）各加：

```json
  "esp_idf_path": "<d-claude-root>\\vendor\\esp-idf",
  "esp_tools_dir": "<d-claude-root>\\vendor\\esp-idf-tools"
```

example 里同样填这两个值（本机同盘位的克隆直接可跑）。

- [ ] **Step 5: Commit（toolkit 仓内只有 example + plan 文件）**

```bash
git add machine.example.json docs/specs/2026-09-16-esp32s3-pilot-plan.md
git commit -m "feat(F-174): ESP-IDF v5.4.4 装入 vendor + machine.example 补 esp_idf_path/esp_tools_dir 占位键; esp32s3 试点实现计划入档

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: esp_runtime.py 核心（run_idf / 路径解析 / panic 标记）

**Files:**
- Create: `scripts/esp_runtime.py`
- Test: `tests/test_esp_runtime.py`

**Interfaces:**
- Consumes: `wb_common.load_machine() -> dict`
- Produces（Task 3-5 全依赖这些签名）:
  - `class EspConfigError(RuntimeError)`
  - `resolve_idf_path() -> str`（machine.json `esp_idf_path`，缺失/目录不存在抛 EspConfigError）
  - `run_idf(ps_commands: list[str], timeout: int, workspace: str, *, _run=subprocess.run) -> dict` → `{status: "ok"|"error", returncode, output}` 或超时 `{status:"error", message}`
  - `detect_esp_panic(text: str) -> bool`

- [ ] **Step 1: 写失败测试** — `tests/test_esp_runtime.py`：

```python
"""esp_runtime (F-174) — ESP32-S3 三后端的 host 单测, 零真机零 IO。"""
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime


class RunIdfTests(unittest.TestCase):
    def _fake_run(self, rc=0, out="hello", err=""):
        seen = {}
        def fake(cmd, **kw):
            seen["cmd"] = cmd; seen["kw"] = kw
            return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
        return fake, seen

    def test_builds_powershell_with_export_and_gate(self):
        fake, seen = self._fake_run()
        with mock.patch.object(esp_runtime, "resolve_idf_path",
                               return_value=r"D:\idf\esp-idf"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py build"], timeout=900,
                                    workspace=r"W:", _run=fake)
        self.assertEqual(r["status"], "ok")
        script = seen["cmd"][-1]                      # -Command 后的脚本文本
        self.assertIn(". 'D:/idf/esp-idf/export.ps1'", script)  # 正斜杠 (PS 不处理反斜杠转义)
        self.assertIn("idf.py build", script)
        self.assertIn("$LASTEXITCODE", script)         # 逐命令退出码门闩
        self.assertEqual(seen["cmd"][:3], ["powershell", "-NoProfile", "-ExecutionPolicy"])
        self.assertEqual(seen["kw"]["cwd"], "W:")

    def test_nonzero_rc_is_error_not_fail_open(self):
        # F-090 同源纪律: 输出里全是漂亮话, rc!=0 必须 error
        fake, _ = self._fake_run(rc=2, out="Hash of data verified")
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["idf.py flash"], 60, "W:", _run=fake)
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["returncode"], 2)

    def test_timeout_returns_message(self):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=1)
        with mock.patch.object(esp_runtime, "resolve_idf_path", return_value="X"), \
             mock.patch.object(esp_runtime, "_idf_env", return_value={}):
            r = esp_runtime.run_idf(["x"], 1, "W:", _run=boom)
        self.assertEqual(r["status"], "error")
        self.assertIn("超时", r["message"])


class ResolveIdfPathTests(unittest.TestCase):
    def test_missing_key_raises(self):
        with mock.patch.object(esp_runtime, "load_machine", return_value={}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_nonexistent_dir_raises(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": r"Q:\nope"}):
            with self.assertRaises(esp_runtime.EspConfigError):
                esp_runtime.resolve_idf_path()

    def test_ok_path_returns_it(self):
        with mock.patch.object(esp_runtime, "load_machine",
                               return_value={"esp_idf_path": os.getcwd()}):
            self.assertEqual(esp_runtime.resolve_idf_path(), os.getcwd())


class PanicMarkerTests(unittest.TestCase):
    def test_markers(self):
        self.assertTrue(esp_runtime.detect_esp_panic("Guru Meditation Error: Core 0"))
        self.assertTrue(esp_runtime.detect_esp_panic("Backtrace: 0x4037abcd:0x3fc..."))
        self.assertTrue(esp_runtime.detect_esp_panic("abort() was called at PC ..."))
        self.assertFalse(esp_runtime.detect_esp_panic("ESP-PILOT-OK tick=1"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_esp_runtime.py -q` → Expected: `ModuleNotFoundError: No module named 'esp_runtime'` 之类红。

- [ ] **Step 3: 实现 `scripts/esp_runtime.py`（本任务范围）**

```python
"""ESP32 运行时后端 (F-174 esp32s3 pilot) — idf.py 构建 / esptool 烧录 / UART 采集.

设计: docs/specs/2026-09-16-esp32s3-pilot-design.md
纪律:
- 机器路径只允许存在于 machine.json (esp_idf_path / esp_tools_dir);
- 子进程成败只信 returncode (F-090 同源教训, OpenOCD 日志走 stderr 的同款坑);
- idf.py / esptool 依赖 export.ps1 注入的环境, 统一经 run_idf 单点封装
  (PowerShell 会话内 source 后顺序执行, 逐命令 $LASTEXITCODE 门闩传播退出码)。
"""
import os
import subprocess

from wb_common import load_machine

_PANIC_MARKERS = ("Guru Meditation", "Backtrace:", "abort() was called",
                  "assert failed", "Heap corruption")


class EspConfigError(RuntimeError):
    """machine.json 缺 esp_idf_path 或目录不存在 — 友好报错不裸 traceback"""


def resolve_idf_path() -> str:
    m = load_machine()
    path = m.get("esp_idf_path", "")
    if not path or not os.path.isdir(path):
        raise EspConfigError(
            f"machine.json esp_idf_path 未配置或目录不存在: {path!r} — "
            "真机构建/烧录前请填入 ESP-IDF 根目录绝对路径")
    return path


def _idf_env() -> dict:
    """子进程 env: IDF_TOOLS_PATH 指到 machine.json 的 esp_tools_dir.

    export.ps1 找不到工具会去默认 %USERPROFILE%\\.espressif 兜底——装在哪
    就必须告诉它去哪找, 键缺省时不注入 (回落 IDF 官方默认)。"""
    env = os.environ.copy()
    tools = load_machine().get("esp_tools_dir", "")
    if tools:
        env["IDF_TOOLS_PATH"] = tools
    return env


def run_idf(ps_commands: list[str], timeout: int, workspace: str,
            *, _run=subprocess.run) -> dict:
    """在 export.ps1 环境里顺序执行 PowerShell 命令串.

    导出脚本失败不单独拦——下一条命令必炸且报错更具体。
    返回 {status, returncode, output} (output = stdout+stderr 合并) 或
    超时 {status:"error", message}。_run 注入点供 host 单测。"""
    idf = resolve_idf_path()
    export = os.path.join(idf, "export.ps1").replace("\\", "/")  # PS 单引号不吃反斜杠转义
    parts = [f". '{export}'"]
    for c in ps_commands:
        parts.append(c)
        parts.append("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-Command", "; ".join(parts)]
    try:
        proc = _run(cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout, cwd=workspace,
                    env=_idf_env())
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"idf 子进程超时 ({timeout}s)"}
    return {"status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "output": (proc.stdout or "") + (proc.stderr or "")}


def detect_esp_panic(text: str) -> bool:
    """ESP panic 只做文本级标记 (spec §4.3): 符号化解析后置另票。"""
    return any(m in text for m in _PANIC_MARKERS)
```

- [ ] **Step 4: 跑测试确认全绿 + lint**

Run: `python -m pytest tests/test_esp_runtime.py -q` → PASS；`python -m ruff check scripts/esp_runtime.py tests/test_esp_runtime.py` → 零告警。

- [ ] **Step 5: Commit**

```bash
git add scripts/esp_runtime.py tests/test_esp_runtime.py
git commit -m "feat(F-174): esp_runtime 核心 — run_idf (export.ps1 单点封装+\$LASTEXITCODE 门闩, F-090 只信 returncode) / resolve_idf_path / detect_esp_panic + 9 项 host 单测

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: builder=idf 派发（build + analyze 直通）

**Files:**
- Modify: `scripts/esp_runtime.py`（追加 `step_build_idf` + `_write_last_build`）
- Modify: `scripts/verify.py`（`step_build` :177-189 区域、`step_analyze` :203-214、build 循环条件 :665）
- Test: `tests/test_esp_runtime.py`、`tests/test_verify_esp_dispatch.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `run_idf` / `EspConfigError`
- Produces: `step_build_idf(config: dict, rebuild: bool = False, workspace: str | None = None) -> dict` — 契约对齐 gcc_build：`{status, metrics:{errors,warnings}, details:{log_file, hex_file, bin_file, elf_file}, summary}`，成功时写 `.workbench/state.json` 的 `last_build.{provider:"idf", hex_file, bin_file, elf_file}`（hex_file 键复用是给 verify `--no-build` 回读用的，值 = .bin 相对路径）

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_esp_runtime.py`：

```python
import json
import tempfile


class StepBuildIdfTests(unittest.TestCase):
    """mock run_idf + tmpdir 产物, 钉: 命令装配/日志落盘/metrics/state.json 契约。"""

    def _ws(self, td, with_artifacts=True):
        os.makedirs(os.path.join(td, "build"), exist_ok=True)
        os.makedirs(os.path.join(td, ".workbench"), exist_ok=True)
        if with_artifacts:
            open(os.path.join(td, "build", "esp32s3_hello.bin"), "w").close()
            open(os.path.join(td, "build", "esp32s3_hello.elf"), "w").close()
        return td

    def test_success_contract(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({"idf": {}}, workspace=ws,
                                           _run_idf=lambda c, **kw: {
                        "status": "ok", "returncode": 0,
                        "output": "Executing idf.py build\nDone\n"})
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["metrics"], {"errors": 0, "warnings": 0})
            self.assertEqual(r["details"]["hex_file"], "build/esp32s3_hello.bin")
            self.assertEqual(r["details"]["elf_file"], "build/esp32s3_hello.elf")
            self.assertTrue(os.path.isfile(os.path.join(
                ws, r["details"]["log_file"])))          # 日志落盘
            with open(os.path.join(ws, ".workbench", "state.json"),
                      encoding="utf-8") as f:
                lb = json.load(f)["last_build"]
            self.assertEqual(lb["provider"], "idf")
            self.assertEqual(lb["hex_file"], "build/esp32s3_hello.bin")  # verify --no-build 回读键

    def test_error_line_counted_and_status_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "error", "returncode": 2,
                "output": "main.c:5:1: error: 'foo' undeclared\nninja: build stopped\n"})
            self.assertEqual(r["status"], "error")
            self.assertEqual(r["metrics"]["errors"], 1)

    def test_rc_zero_but_error_line_still_error(self):
        # rc=0 但日志含 error: → 不许按成功入账 (F-090 判据的补充证据方向)
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "cc1: error: bad\n"})
            self.assertEqual(r["status"], "error")

    def test_no_bin_artifact_errors(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td, with_artifacts=False)
            r = esp_runtime.step_build_idf({}, workspace=ws, _run_idf=lambda c, **kw: {
                "status": "ok", "returncode": 0, "output": "Done\n"})
            self.assertEqual(r["status"], "error")
            self.assertIn("bin", r["summary"].lower())

    def test_rebuild_prepends_fullclean(self):
        seen = []
        def spy(cmds, **kw):
            seen.append(list(cmds))
            return {"status": "ok", "returncode": 0, "output": "Done\n"}
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            esp_runtime.step_build_idf({}, rebuild=True, workspace=ws, _run_idf=spy)
        self.assertEqual(seen[0], ["idf.py fullclean", "idf.py build"])
```

新建 `tests/test_verify_esp_dispatch.py`：

```python
"""verify.py F-174 派发钉 — 新分支被正确路由 + 缺省路径回归 (builder/flash/capture 三处)。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime
import verify


class StepBuildDispatchTests(unittest.TestCase):
    def test_idf_routes_to_esp_runtime(self):
        with mock.patch.object(esp_runtime, "step_build_idf",
                               return_value={"status": "ok"}) as m:
            r = verify.step_build({"builder": "idf"}, builder="idf",
                                  rebuild=True)
        m.assert_called_once()                       # rebuild 旗标也放行到 idf (fullclean)
        self.assertEqual(r["status"], "ok")

    def test_gcc_default_untouched(self):
        # 缺省回归钉: gcc 路径仍走 run_py(GCC_BUILD)
        with mock.patch.object(verify, "run_py",
                               return_value={"status": "ok"}) as m:
            verify.step_build({"gcc": {"project": "p/Makefile"}}, builder="gcc")
        self.assertIn("gcc_build.py", m.call_args[0][0])

    def test_analyze_idf_passthrough_metrics(self):
        r = verify.step_analyze("x.log", builder="idf",
                                build_metrics={"errors": 0, "warnings": 3})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["summary"]["warnings"], 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败** — `python -m pytest tests/test_esp_runtime.py tests/test_verify_esp_dispatch.py -q`（红：`step_build_idf` 不存在 / idf 路由未实现）

- [ ] **Step 3a: esp_runtime.py 追加**（顶部补 `import glob, json, time`；`step_build_idf` 加 `_run_idf` 注入参数）：

```python
def step_build_idf(config: dict, rebuild: bool = False,
                   workspace: str | None = None,
                   *, _run_idf=None) -> dict:
    """builder=idf (F-174): idf.py build, 契约对齐 gcc_build (spec §4.2)。

    metrics 从合并日志行计数 ("error:" 行 + ninja "FAILED:" 行);
    成败判据: run_idf rc==0 且 errors==0, 两者缺一即 error。
    _run_idf 注入点供单测 (默认走模块级 run_idf)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    cfg = (config or {}).get("idf", {}) or {}
    commands = (["idf.py fullclean"] if rebuild else []) + ["idf.py build"]
    run = run_idf_(commands, timeout=int(cfg.get("build_timeout", 900)),
                   workspace=ws)
    output = run.get("output", "")

    log_dir = os.path.join(ws, ".workbench", "build")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "idf_build.log")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    errors = sum(1 for ln in output.splitlines()
                 if "error:" in ln or "FAILED:" in ln)
    warnings = sum(1 for ln in output.splitlines() if "warning:" in ln)
    metrics = {"errors": errors, "warnings": warnings}
    details = {"log_file": os.path.relpath(log_file, ws).replace(os.sep, "/")}

    if run.get("status") != "ok" or errors > 0:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": (f"idf build failed "
                            f"(rc={run.get('returncode', '?')}, {errors} errors)"),
                "stderr": output[-500:]}

    bins = sorted(glob.glob(os.path.join(ws, "build", "*.bin")))
    elfs = sorted(glob.glob(os.path.join(ws, "build", "*.elf")))
    if not bins:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": "idf build ok 但 build/*.bin 缺失 (先 set-target?)",
                "stderr": output[-300:]}
    bin_rel = os.path.relpath(bins[0], ws).replace(os.sep, "/")
    elf_rel = (os.path.relpath(elfs[0], ws).replace(os.sep, "/")
               if elfs else "")
    details.update({"hex_file": bin_rel, "bin_file": bin_rel,
                    "elf_file": elf_rel})
    _write_last_build(ws, bin_rel, elf_rel)
    return {"status": "ok", "metrics": metrics, "details": details,
            "summary": f"idf build ok ({warnings} warnings)"}


def _write_last_build(ws: str, bin_rel: str, elf_rel: str) -> None:
    """state.json last_build (verify --no-build 回读契约, 与 gcc_build 同构)。

    hex_file 键复用 = .bin 路径: step_flash 的存在性检查与 --no-build
    读取逻辑零改动即可走通 esptool 后端。"""
    state_path = os.path.join(ws, ".workbench", "state.json")
    state = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["last_build"] = {"provider": "idf", "hex_file": bin_rel,
                           "bin_file": bin_rel, "elf_file": elf_rel,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 3b: verify.py 三处小改**

`step_build`（:177 起）——rebuild 白名单放行 idf，并在函数体最前路由：

```python
    if rebuild and builder not in ("gcc", "idf"):
        # YAGNI: keil 后端不接 --rebuild (blink legacy 不用该旗标)
        # F-174: idf 的 rebuild = fullclean + build (esp_runtime 内实现)
        return {"status": "error", "message": "--rebuild 仅支持 builder=gcc|idf"}
    # F-174: ESP32 后端 — 路由到 esp_runtime (契约对齐 gcc_build 返回值)
    if builder == "idf":
        return esp_runtime.step_build_idf(config, rebuild=rebuild,
                                          workspace=WORKSPACE)
```

`step_analyze`（:206）——idf 与 gcc 同走 metrics 直通（spec §4.4：ARMCC 知识库对 xtensa 无意义，不接）：

```python
    if builder in ("gcc", "idf"):
```

build 循环条件（:665）——idf 无 log_file 也须进 analyze：

```python
                if log_file or builder in ("gcc", "idf"):
```

模块顶部 import 区（`from capture_sim import ...` 之后）加：

```python
import esp_runtime  # noqa: E402  (F-174: builder=idf / flash=esptool / capture=uart 三后端)
```

- [ ] **Step 4: 全量测试 + lint**

`python -m pytest tests -q` → 全绿（860 + 新增，只增不减）；`python -m ruff check scripts tests` → 零告警。

- [ ] **Step 5: Commit**

```bash
git add scripts/esp_runtime.py scripts/verify.py tests/test_esp_runtime.py tests/test_verify_esp_dispatch.py
git commit -m "feat(F-174): builder=idf 派发 — step_build_idf (metrics 行计数+state.json last_build 回读契约+日志落盘) / analyze 直通复用 gcc 路径; 缺省回归钉绿

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: flash.backend=esptool 派发

**Files:**
- Modify: `scripts/esp_runtime.py`（追加 `step_flash_esptool`）
- Modify: `scripts/verify.py`（`step_flash` :217-248 加 config 参 + 路由；调用点 :810 传 config）
- Test: `tests/test_esp_runtime.py`、`tests/test_verify_esp_dispatch.py`

**Interfaces:**
- Consumes: `run_idf`
- Produces: `step_flash_esptool(flash_cfg: dict, workspace: str | None = None, *, _run_idf=None) -> dict` — `{status:"ok", backend:"esptool", stdout}` / `{status:"error", backend:"esptool", message, stderr}`（错误 dict 三键齐是喂 verify F-163 的 message 回退链）

- [ ] **Step 1: 写失败测试** — 追加 `tests/test_esp_runtime.py`：

```python
class StepFlashEsptoolTests(unittest.TestCase):
    def test_port_required(self):
        r = esp_runtime.step_flash_esptool({}, workspace="W:")
        self.assertEqual(r["status"], "error")
        self.assertIn("port", r["message"])

    def test_command_assembly_and_rc(self):
        seen = []
        def spy(cmds, **kw):
            seen.append((cmds, kw.get("timeout")))
            return {"status": "ok", "returncode": 0,
                    "output": "Hash of data verified.\nHard resetting via RTS pin..."}
        r = esp_runtime.step_flash_esptool({"port": "COM3", "timeout": 120},
                                           workspace=r"W:", _run_idf=spy)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(seen[0][0], ["idf.py -p COM3 flash"])  # 地址表由 idf flash_args 管理
        self.assertEqual(seen[0][1], 120)

    def test_rc_fail_carries_stderr_tail(self):
        r = esp_runtime.step_flash_esptool(
            {"port": "COM9"}, workspace="W:",
            _run_idf=lambda c, **kw: {"status": "error", "returncode": 2,
                                      "output": "x" * 600 + "could not open port"})
        self.assertEqual(r["status"], "error")
        self.assertIn("COM9", r["message"])
        self.assertIn("could not open port", r["stderr"])
```

追加 `tests/test_verify_esp_dispatch.py`：

```python
class StepFlashDispatchTests(unittest.TestCase):
    """step_flash 新签名 (artifact, config=None): 缺省 openocd, esptool 路由。"""

    def _mk_artifact(self, td):
        rel = os.path.join("build", "app.bin")
        os.makedirs(os.path.dirname(os.path.join(td, rel)), exist_ok=True)
        open(os.path.join(td, rel), "w").close()
        return rel

    def test_esptool_routes_to_esp_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            rel = self._mk_artifact(td)
            with mock.patch.object(verify, "WORKSPACE", td), \
                 mock.patch.object(esp_runtime, "step_flash_esptool",
                                   return_value={"status": "ok"}) as m:
                r = verify.step_flash(rel, {"flash": {"backend": "esptool",
                                                      "port": "COM3"}})
            self.assertEqual(r["status"], "ok")
            self.assertEqual(m.call_args[0][0], {"backend": "esptool",
                                                 "port": "COM3"})

    def test_default_config_openocd_untouched(self):
        # 缺省回归钉: config=None 与 config={} 都必须走今天的 OpenOCD 命令
        with tempfile.TemporaryDirectory() as td:
            rel = self._mk_artifact(td)
            with mock.patch.object(verify, "WORKSPACE", td), \
                 mock.patch.object(verify, "_openocd_exe", return_value="ocd.exe"), \
                 mock.patch.object(verify, "run_cmd",
                                   return_value={"status": "ok", "stdout": "ACTION_DONE_MARKER"}) as m:
                for cfg in (None, {}):
                    r = verify.step_flash(rel, cfg)
                    self.assertEqual(r["status"], "ok")
            cmd = m.call_args[0][0]
            self.assertEqual(cmd[0], "ocd.exe")
            self.assertIn("interface/stlink.cfg", cmd)   # STM32 串逐字节不变
```

（文件顶部需补 `import tempfile`。）

- [ ] **Step 2: 跑测试确认失败**（`step_flash_esptool` 不存在 / `step_flash() takes 1 positional argument`）

- [ ] **Step 3a: esp_runtime.py 追加**：

```python
def step_flash_esptool(flash_cfg: dict, workspace: str | None = None,
                       *, _run_idf=None) -> dict:
    """flash.backend=esptool (F-174): 经 idf.py -p <port> flash 烧录.

    选 idf.py flash 而非手拼 esptool write_flash 地址表: flash_args 由构建
    系统生成 (bootloader/分区表/app 三镜像+offset), 手拼即漂移 (spec §4.2)。
    结束自带 --after hard-reset, capture 段仍显式再复位一次 (确定性起点)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    port = (flash_cfg.get("port") or "").strip()
    if not port:
        return {"status": "error", "backend": "esptool",
                "message": "flash.port 未配置 (esptool 后端需要串口号, 如 COM3)"}
    run = run_idf_([f"idf.py -p {port} flash"],
                   timeout=int(flash_cfg.get("timeout", 300)), workspace=ws)
    out = run.get("output", "")
    if run.get("status") == "ok":
        return {"status": "ok", "backend": "esptool", "stdout": out[-1000:]}
    return {"status": "error", "backend": "esptool",
            "message": f"idf.py flash 失败 (port={port}, "
                       f"rc={run.get('returncode', '?')})",
            "stderr": out[-500:]}
```

- [ ] **Step 3b: verify.py `step_flash` 改造**——签名与路由（产物存在性检查保持在派发前，两后端共用；OpenOCD 分支本体一字不动）：

```python
def step_flash(hex_file: str, config: dict | None = None) -> dict:
    """步骤 3: 烧录 (flash.backend 派发: openocd[默认] | esptool[F-174])"""
    if not hex_file:
        ...原样...
    if not os.path.exists(os.path.join(WORKSPACE, hex_file)):
        ...原样...

    # F-174: ESP32 esptool 后端 — 地址表交给 idf.py flash (esp_runtime 内)
    flash_cfg = (config or {}).get("flash", {}) or {}
    if flash_cfg.get("backend", "openocd") == "esptool":
        return esp_runtime.step_flash_esptool(flash_cfg, workspace=WORKSPACE)

    hex_abs = os.path.join(WORKSPACE, hex_file)
    ...原 OpenOCD 命令装配逐字节不变...
```

调用点 :810 改为：`flash = step_flash(hex_file, config)`。
文件头 docstring 流程行 `3. Flash → OpenOCD program` 改为 `3. Flash → OpenOCD program (默认) | esptool (flash.backend=esptool, F-174)`。

- [ ] **Step 4: 全量测试 + lint**（`python -m pytest tests -q` 全绿——特别盯 `test_hw_lease` / `test_hil_origin_guard` / `test_checkpoint_ledger` 这几个 patch `verify.step_flash` 的既有钉是否依旧绿）

- [ ] **Step 5: Commit**

```bash
git add scripts/esp_runtime.py scripts/verify.py tests/
git commit -m "feat(F-174): flash.backend=esptool 派发 — step_flash_esptool 经 idf.py flash (flash_args 单一事实源); step_flash 加 config 参, OpenOCD 缺省路径逐字节回归钉绿

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: capture.backend=uart 派发 + panic 标记上账

**Files:**
- Modify: `scripts/esp_runtime.py`（追加 `step_capture_uart`）
- Modify: `scripts/verify.py`（`_run_capture_step` :931 rtt 分支后加 uart elif；文件头 docstring :16）
- Test: `tests/test_esp_runtime.py`、`tests/test_verify_esp_dispatch.py`

**Interfaces:**
- Consumes: `run_idf`（复位）、`detect_esp_panic`、`serial.Serial`（pyserial 3.5 已装）
- Produces: `step_capture_uart(timeout_s: int, cap_cfg: dict, workspace: str | None = None, *, _run_idf=None) -> dict` — 返回契约对齐 `step_capture_rtt`：`{status, method:"uart", port, timeout_sec, lines, esp_panic, duration_sec, ...}` + 正文私有键 `_text`（派发方 pop）

- [ ] **Step 1: 写失败测试** — 追加 `tests/test_esp_runtime.py`：

```python
class StepCaptureUartTests(unittest.TestCase):
    """假串口: readline 依序吐预制行, 到空后按墙钟截止。"""

    def _fake_serial(self, lines):
        import serial as _s
        class FakeSer:
            def __init__(self, *a, **kw): self.i = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                if self.i < len(lines):
                    self.i += 1
                    return lines[self.i - 1].encode()
                raise _s.SerialException("done-for-test")
        return FakeSer

    def test_missing_port_errors(self):
        r = esp_runtime.step_capture_uart(5, {}, workspace="W:")
        self.assertEqual(r["status"], "error")
        self.assertIn("capture.port", r["error"])

    def test_reset_then_capture_then_contract(self):
        seen = []
        def spy(cmds, **kw):
            seen.append(cmds)
            return {"status": "ok", "returncode": 0, "output": "Chip type: ESP32-S3"}
        lines = ["ESP-PILOT-BOOT ok", "ESP-PILOT-OK tick=0 heap=123", ""]
        with mock.patch("serial.Serial", self._fake_serial(lines)), \
             mock.patch.object(esp_runtime.time, "sleep"):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "baudrate": 115200, "settle_sec": 0},
                workspace="W:", _run_idf=spy)
        # 第 4 次 readline 抛 SerialException("done-for-test") → 端口故障即 error,
        # 错误原文可读 (COM3 被占/拔线就是这个出口)
        self.assertEqual(r["status"], "error")
        self.assertIn("done-for-test", r["error"])
        self.assertIn("esptool", seen[0][0])      # 复位先行 (chip_id 廉价只读)
        self.assertIn("--after hard-reset", seen[0][0])

    def test_happy_path_text_and_panic_flag(self):
        class OkSer:
            def __init__(self, *a, **kw): self.n = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                self.n += 1
                if self.n == 1: return b"ESP-PILOT-OK tick=0\n"
                return b""      # 静默, 等 deadline
        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])   # deadline 走秒
        with mock.patch("serial.Serial", lambda *a, **kw: OkSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time", lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["method"], "uart")
        self.assertEqual(r["_text"], "ESP-PILOT-OK tick=0")
        self.assertFalse(r["esp_panic"])

    def test_panic_marked_not_fatal(self):
        class PanicSer:
            def __init__(self, *a, **kw): self.n = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def readline(self):
                self.n += 1
                if self.n == 1: return b"Guru Meditation Error: Core 0 panic'ed\n"
                return b""
        fake_time = iter([0, 0, 0, 1, 2, 3, 4, 5, 6, 6])
        with mock.patch("serial.Serial", lambda *a, **kw: PanicSer()), \
             mock.patch.object(esp_runtime.time, "sleep"), \
             mock.patch.object(esp_runtime.time, "time", lambda: next(fake_time)):
            r = esp_runtime.step_capture_uart(
                5, {"port": "COM3", "settle_sec": 0}, workspace="W:",
                _run_idf=lambda c, **kw: {"status": "ok", "returncode": 0,
                                          "output": ""})
        self.assertEqual(r["status"], "ok")      # panic 不拦截采集 (交 AI judge 定性)
        self.assertTrue(r["esp_panic"])

    def test_reset_failure_short_circuits(self):
        r = esp_runtime.step_capture_uart(
            5, {"port": "COM3"}, workspace="W:",
            _run_idf=lambda c, **kw: {"status": "error", "message": "超时 (5s)"})
        self.assertEqual(r["status"], "error")
        self.assertIn("复位失败", r["error"])
```

追加 `tests/test_verify_esp_dispatch.py`：

```python
import argparse


class CaptureUartDispatchTests(unittest.TestCase):
    def _args(self):
        return argparse.Namespace(timeout=5, task_origin="manual",
                                  require_schedule_origin=False, json=True)

    def test_uart_branch_writes_capture_step_and_panic(self):
        cfg = {"capture": {"backend": "uart", "port": "COM9"},
               "verify": {"expect": ["ESP-PILOT-OK"]}}
        result = {"steps": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "ok", "method": "uart",
                                   "esp_panic": True,
                                   "_text": "Guru Meditation Error"}) as m, \
             mock.patch.object(verify, "append_audit_entry"):
            text, lines, tmo = verify._run_capture_step(
                self._args(), cfg, result, None, False, "uart", {}, 0, "")
        self.assertIn("Guru", text)
        self.assertEqual(result["steps"]["capture"]["method"], "uart")
        self.assertTrue(result["steps"]["capture"]["esp_panic"])
        self.assertTrue(result.get("esp_panic"))   # 顶层标记供 judge
        self.assertEqual(tmo, 5)
        m.assert_called_once()

    def test_uart_failure_early_exit(self):
        cfg = {"capture": {"backend": "uart", "port": "COM9"}, "verify": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "error", "method": "uart",
                                   "error": "串口 COM9 采集失败"}), \
             mock.patch.object(verify, "append_audit_entry"), \
             mock.patch.object(verify, "_save_failure_context"), \
             mock.patch.object(verify, "_output"), \
             mock.patch.object(verify, "_record_checkpoint_early_exit"):
            with self.assertRaises(SystemExit) as cm:
                verify._run_capture_step(
                    self._args(), cfg, {"steps": {}}, None, False, "uart", {}, 0, "")
        self.assertEqual(cm.exception.code, 1)     # 失败早退非零纪律

    def test_default_backend_still_semihosting(self):
        # 缺省回归钉: cap_backend 默认值路径不碰 esp_runtime
        cfg = {"capture": {"backend": "semihosting"}, "verify": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(verify, "run_semihosting_session",
                     return_value=("", "")) as m, \
             mock.patch.object(verify, "append_audit_entry"):
            verify._run_capture_step(self._args(), cfg, {"steps": {}},
                                     None, False, "semihosting", {}, 0, "")
        m.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3a: esp_runtime.py 追加**（顶部补 `import time`；`serial` 保持函数内延迟 import——host 无 pyserial 时模块仍可 import）：

```python
def step_capture_uart(timeout_s: int, cap_cfg: dict,
                      workspace: str | None = None,
                      *, _run_idf=None) -> dict:
    """capture.backend=uart (F-174): esptool 复位进固件 → pyserial 定时采集.

    时序 (spec §7 风险"复位窗口丢日志"缓解):
      1) esptool --after hard-reset chip_id: 廉价只读命令触发确定性复位
         (--no-flash 续跑路径同样先复位, 不吃上一轮残态 — 2026-08-16 教训同款)
      2) settle_sec 静默等端口稳定 (USB-UART 桥重枚举, 默认 1.0s)
      3) readline 到 deadline: 端口异常即 error (COM3 被占/拔线给可读报错)
    panic 不拦截: 只打 esp_panic 文本标记, 定性交 AI judge (spec §4.3)。
    正文经私有键 "_text" 带回, 契约与 step_capture_rtt 一致。
    """
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    port = (cap_cfg.get("port") or "").strip()
    if not port:
        return {"status": "error", "method": "uart",
                "error": "capture.port 未配置 (uart 后端需要串口号, 如 COM3)"}
    try:
        import serial
    except ImportError:
        return {"status": "error", "method": "uart",
                "error": "缺 pyserial: pip install pyserial"}

    chip = cap_cfg.get("chip", "esp32s3")
    # 复位兼探活用 esptool 只读命令 (dash 形式——v5 已弃下划线别名, spike 见过
    # deprecation warning); 若真机提示 unknown command 换 `run` (无参纯复位退出码 0)
    reset = run_idf_([f"esptool --chip {chip} -p {port} --after "
                      f"hard-reset chip-id"], timeout=30, workspace=ws)
    if reset.get("status") != "ok":
        return {"status": "error", "method": "uart",
                "error": ("复位失败 (端口被占/板子未上电?): "
                          + (reset.get("message")
                             or reset.get("output", "")[-300:]))}

    t0 = time.time()
    deadline = t0 + float(cap_cfg.get("settle_sec", 1.0))
    try:
        while time.time() < deadline:
            time.sleep(0.05)
    except Exception:
        pass
    t0 = time.time()
    lines = []
    try:
        with serial.Serial(port, int(cap_cfg.get("baudrate", 115200)),
                           timeout=0.5) as ser:
            while time.time() - t0 < timeout_s:
                raw = ser.readline()
                if raw:
                    lines.append(raw.decode("utf-8", errors="replace")
                                 .rstrip("\r\n"))
    except serial.SerialException as e:
        return {"status": "error", "method": "uart",
                "error": f"串口 {port} 采集失败: {e}"}
    text = "\n".join(lines)
    return {
        "status": "ok", "method": "uart", "port": port,
        "timeout_sec": timeout_s,
        "lines": len([ln for ln in lines if ln.strip()]),
        "esp_panic": detect_esp_panic(text),
        "duration_sec": round(time.time() - t0, 1),
        "_text": text,
    }
```

（注意：上面 settle 等待用 time.time 循环而非裸 sleep(deadline)，是为了单测可用假时钟钉 deadline——执行者若简化为 `time.sleep(settle)` 必须先确认 test_happy_path 的假时钟仍过。）

- [ ] **Step 3b: verify.py `_run_capture_step`**——在 `elif cap_backend == "rtt":` 分支之后、`else:`（semihosting）之前插入：

```python
    elif cap_backend == "uart":
        # F-174: ESP32 UART 采集 (esptool 复位 → pyserial 定时窗) — 契约同 rtt 分支
        cap = esp_runtime.step_capture_uart(
            capture_timeout, config.get("capture", {}), WORKSPACE)
        if cap.get("status") != "ok":
            result["steps"]["capture"] = {
                k: v for k, v in cap.items() if not k.startswith("_")
            }
            result["status"] = "capture_failed"
            result["error"] = cap.get("error", "uart capture failed")
            _release_hw_lease(lease)
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        captured_text = cap.pop("_text", "")
        captured_lines = [ln for ln in captured_text.splitlines() if ln.strip()]
        cap["origin"] = args.task_origin   # F-046: 审计标记
        cap["duration_sec"] = round(time.time() - capture_t0, 1)  # F-050
        result["steps"]["capture"] = cap
        if cap.get("esp_panic"):
            # ESP panic 只上账文本标记 (spec §4.3); 4b 的 HardFault 归因链是
            # Cortex-M 专属 (CFSR/OpenOCD 寄存器), 对 ESP 文本天然不触发。
            result["esp_panic"] = True
            print("[capture] 检出 ESP panic 文本标记 — 符号化解析用 idf.py "
                  "monitor (另票), 本流程只交 AI judge 定性", file=sys.stderr)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))
```

文件头 docstring 行 16 `4. Capture → …semihosting…| rtt (capture.backend)` 补 `| uart (F-174, ESP32)`。

- [ ] **Step 4: 全量测试 + lint** → 全绿

- [ ] **Step 5: Commit**

```bash
git add scripts/esp_runtime.py scripts/verify.py tests/
git commit -m "feat(F-174): capture.backend=uart — esptool 确定性复位+settle 窗+pyserial 定时采集; esp_panic 文本标记上账 (归因链留 Cortex-M 4b 不触发); 缺省 semihosting 回归钉绿

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: esp32s3-hello 试点工程 + 顶层 README 登记

**Files:**
- Create: `<d-claude-root>\esp32s3-hello\{CMakeLists.txt,sdkconfig.defaults,.gitignore}`、`main\{CMakeLists.txt,hello_main.c}`、`.workbench\config.json`
- Modify: `<d-claude-root>\README.md`（hw-projects 分类表 +1 行——结构变更守则强制）

**Interfaces:**
- Consumes: Task 1 的 IDF 环境、Task 3-5 的三后端与 config 契约（键名逐字对齐 spec §4.1）
- Produces: 真机可 verify 的工程目录；expect 靶字符串 `ESP-PILOT-BOOT ok` / `ESP-PILOT-OK tick=`

- [ ] **Step 1: 建目录与文件**（内容全量如下，勿改字）

`CMakeLists.txt`：

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32s3_hello)
```

`sdkconfig.defaults`：

```
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y
CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y
```

（PSRAM/WiFi 全部不开——YAGNI，spec §1 非目标。）

`main/CMakeLists.txt`：

```cmake
idf_component_register(SRCS "hello_main.c"
                       INCLUDE_DIRS ".")
```

`main/hello_main.c`：

```c
/* F-174 ESP32-S3 最小闭环试点固件: 周期 printf 作 verify expect 靶。 */
#include <stdio.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"

void app_main(void)
{
    printf("ESP-PILOT-BOOT ok\n");
    uint32_t tick = 0;
    while (1) {
        printf("ESP-PILOT-OK tick=%" PRIu32 " heap=%" PRIu32 "\n",
               tick, (uint32_t)esp_get_free_heap_size());
        tick++;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
```

`.gitignore`：

```
build/
sdkconfig
sdkconfig.old
managed_components/
dependencies.lock
.workbench/build/
```

`.workbench/config.json`：

```json
{
  "builder": "idf",
  "idf": {"build_timeout": 900},
  "flash": {"backend": "esptool", "port": "COM3"},
  "capture": {"backend": "uart", "port": "COM3", "baudrate": 115200,
              "settle_sec": 1.0, "duration_sec": 15},
  "verify": {"expect": ["ESP-PILOT-BOOT ok", "ESP-PILOT-OK tick="]}
}
```

> I-3 勘误 2026-09-18（复审 N-1 订正注释位置）：原示例 `verify.capture_timeout` 为死键，按 T6 裁决改 `capture.duration_sec`，见 design §4.1 勘误注。

- [ ] **Step 2: git 入库（独立仓库）**：`<d-claude-root>\esp32s3-hello` 内 `git init` + 提交全部（autocrlf/gitignore 处理照抄 `<d-claude-root>\stm32f103-adc-oled\.gitattributes` 若存在）。提交前 `git status` 确认 build/ 未混入。

- [ ] **Step 3: 顶层 README 加行**（hw-projects 表，格式对齐现有行）：

```
| esp32s3-hello | ESP32-S3 最小闭环试点（F-174，ESP-IDF，verify 三后端首用） | 活跃 |
```

（列名以 README 实际表头为准；本仓不在 git 管理，无提交动作。）

- [ ] **Step 4: 首建冒烟（host 侧，不算验收）**

```powershell
cd <d-claude-root>\esp32s3-hello
$env:IDF_TOOLS_PATH = "<d-claude-root>\vendor\esp-idf-tools"
. <d-claude-root>\vendor\esp-idf\export.ps1
idf.py set-target esp32s3
idf.py build
```

Expected: `Project build complete`，`build\esp32s3_hello.bin` 在场。此步只证明工具链+工程骨架可用；真机全链路终验在 Task 7（验收=真机铁律）。

---

### Task 7: 真机终验 + 回归 + 收尾

**Files:**
- Modify: `docs/specs/2026-09-16-esp32s3-pilot-design.md`（状态行改"已落地"）
- Modify: 记忆目录 2 个文件 + MEMORY.md（非 git 管理）
- Delete: pip esptool（spike 临时物）

- [ ] **Step 1: 全链路 ×2**

```bash
cd <d-claude-root>/esp32s3-hello && python <d-claude-root>/embedded-toolkit/scripts/verify.py --timeout 15 --json
```

Expected: `"status": "ok"`，flash/capture/verify 段全 ok，capture.lines ≥ 3。**连跑两次**都必须绿（USB 复位时序稳定性）。第一次 build 冷编译约 3-5 分钟，正常。

- [ ] **Step 2: 负路径**

a. `capture.port` 临时改 `COM8`（不存在）→ `capture_failed`、exit 1、error 是人话；改回。
b. `verify.expect` 临时加 `"NEVER-PRINTED-XYZ"` → 顶层 status FAIL 但 capture 段 ok；改回。
c. 占用测试：另开进程占 COM3（`python -m serial.tools.miniterm COM3 115200`）再跑 `--no-build --no-flash` → 复位失败友好报错，不裸 traceback。
d. panic 标记冒烟（可选，若手边无事）：临时在 hello_main.c 加 `int *p=0; *p=1;` 循环外触发 → `esp_panic: true` 且流程不崩 → 还原。**做完必须 `git checkout` 还原。**

- [ ] **Step 3: STM32 回归（零破坏证明）**

板子在位则：`cd <d-claude-root>/stm32f103-adc-oled && python <d-claude-root>/embedded-toolkit/scripts/verify.py --no-build` → 照常 PASS。板子不在则退而 `python -m pytest tests -q` 全量绿 + 明说"真机 STM32 回归待下次上电补"，不许含糊。

- [ ] **Step 4: 收尾**

```bash
python -m pip uninstall -y esptool     # spike 临时物, 烧录统一走 IDF 自带
```

设计文档状态行改为 `状态：已落地 (2026-09-16, feat/esp32s3-pilot)`，CHANGELOG **不动**（未发布态，规则见 v0.6 封袋惯例）。toolkit 内 commit。

- [ ] **Step 5: 记忆更新**

- `esp32-onboarding-deferred-no-hardware.md`：追加"2026-09-16 唤起落地"段（分支名/三后端/验收结果），保留挂起史；
- `multi-mcu-tooling-roadmap.md`：esptool 现状更新为 IDF 5.4.4 内置（pip 版已卸），probe-rs/wokwi 仍属未接项；
- `MEMORY.md` 两行指针随之订正。

- [ ] **Step 6: 向用户汇报终验证据**（verify JSON 摘要 + 负路径行为清单），等用户裁决分支去向（保留/合 master 均不再自作主张）。

---

## Self-Review 记录

- **Spec 覆盖**：§2 安装→T1；§3 工程→T6；§4.2-4.5 三派发/esp_runtime/analyze 降级/设备锁（T4/T5 走既有 F-145 段不改码，lease 在 `_run_flash_step` 上游）→T3/T4/T5；§5 测试→T2-5 单测 + T7 真机；§6 收尾→T7；§7 风险逐条有落点。**无缺口。**
- **占位符扫描**：无 TBD/"similar to"；两处"以实际表头为准/若存在"是磁盘事实核对，非需求歧义。
- **类型一致性**：`step_build_idf/step_flash_esptool/step_capture_uart` 签名在 T2 Produces、T3-5 实现与测试三处一致；`_text` 私有键、`esp_panic` 键名与 spec §4.2/§4.3 一致；config 键（`flash.backend`/`flash.port`/`capture.backend`/`idf.build_timeout`）与 spec §4.1 逐字一致。
- **已知风险**：Task 1 镜像/网络不可控时长——执行时后台跑；Task 7 Step 3 依赖 STM32 板在场，已给降级口径。
