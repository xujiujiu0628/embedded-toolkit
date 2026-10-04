#!/usr/bin/env python3
r"""
闭环验证编排器 — 一键完成 编译→分析→烧录→采集→验证

用法:
    python verify.py                        # 完整流程
    python verify.py --timeout 10           # 捕获 10 秒
    python verify.py --no-build             # 跳过编译 (用上次产物)
    python verify.py --no-flash             # 跳过烧录 (用已烧录固件)
    python verify.py --json                 # JSON 输出 (供 Claude 判断)

流程:
    1. Build   → gcc_build.py (默认 builder=gcc; idf → esp_runtime, F-174; 显式配 "keil" 时唤起 archive 退役桥)
    2. Analyze → gcc 路径直传 build metrics; keil 路径走 archive 唤起的 keil_analyze 知识库 (有 error 则终止)
    3. Flash   → OpenOCD program (默认) | esptool (flash.backend=esptool, F-174)
    4. Capture → verify.py 内置双路: semihosting 内联会话 (默认) | rtt (capture.backend) | uart (F-174, ESP32)
    4c. Physical → OpenOCD ODR 轮询 GPIO 翻转频率 (物理层门控, 默认 skipped)
    5. Output  → 结构化 JSON 结果, Claude 对比期望判断 ✅/❌

Keil 退役区 (2026-09-05 F-067b): scripts/legacy/keil/ + data/keil-error-db.json
+ scripts/error_db_grow.py + config/keil.json 已从仓内拆出, 物理副本位于
<D-claude-root>\\archive\\embedded-toolkit-keil-legacy-20260905\\ (用户主目录
+ archive 分类下, 见工作区顶层 README.md 维护约定). builder="keil" 路径
启动时检测 EMBEDDED_TOOLKIT_KEIL_ARCHIVE 环境变量, 未设时回退到上述默认
archive 路径, 唤起 keil_build / keil_analyze 需手动 cp 副本到仓内。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback


WORKSPACE = None  # 工程根, main() 中 --project 或 cwd 向上发现后设置

from wb_common import (TOOLKIT_ROOT, find_project_root, load_machine,
                       toolkit_version, version_ok)

def _openocd_exe() -> str:
    """F-054: 原 OPENOCD_EXE 模块级常量惰性化——import 期零 IO。

    旧形态在 import 期读 machine.json，缺失时还向 stderr 吐回退警告，
    6 个测试文件被迫以注释豁免（CONTRIBUTING 禁令 #2 的存在理由之一）。
    惰性化后 import 卫生由 test_import_hygiene 钉死。"""
    return load_machine()["openocd_exe"]

from runtime_common import now_iso, output_json  # noqa: E402  (F-041: doctor --json 复用共享层; F-157: now_iso 收编)
from runtime_common import OpenocdCfgError, resolve_openocd_cfg  # noqa: E402  (WB-20260919-06: cfg 组装单一事实源)
from runtime_common import (esp_backend_mode as _esp_backend_mode)  # noqa: E402  (F-190/M-1: 三标记 OR 上收单一事实源, F-057 再导出形态——release G0.5 同源消费)
from runtime_common import esp_backend_config_errors  # noqa: E402  (F-190/T3: GAP-F-19 混配 fail-fast 规则单一事实源)
from openocd_runtime import reset_target  # noqa: E402  (F-041/F-129: 判定后复位; F-192/N-4: swd_probe 死名已删 — verify 主链零调用, G0.5 探测面归 release/doctor 直连 openocd_runtime)
from openocd_run import ACTION_DONE_CMD, marker_present  # noqa: E402  (F-163: N-3 标记共享件)
import hw_lease  # noqa: E402  (F-145: flash+capture 段机器级设备锁)
import junit_xml  # noqa: E402  (F-147: --junit-xml 报告, 生成逻辑在模块内)

# F-147: --junit-xml 的输出路径, main() 设置; _output 是唯一出口汇点,
# 报告在出口统一落盘 (含 preflight 拒绝的早退运行)。
_JUNIT_OUT: str | None = None
from expectations import (ExpectationError, contract_hashes,  # noqa: E402,F401  (F-055: 拆分件再导出, verify.X 调用面不变)
                          evaluate_expectations, load_expectations,
                          _expect_matched, check_forbidden_fields, _forbidden_hit)
from capture_rtt import step_capture_rtt as _step_capture_rtt  # noqa: E402  (F-056: 拆分件再导出, 旧私有名保持——3 处测试钉兼容)
from physical_gate import step_physical_gate  # noqa: E402  (F-057: 拆分件再导出, 同名同签名)
from doctor import (doctor_report, fixture_health,  # noqa: E402,F401  (F-058: 拆分件再导出, 调用面不变)
                    _print_doctor, _detect_default_branch, _fixture_main_sha)
from checkpoint_ledger import (CHECKPOINT_STATUSES, _git_head,  # noqa: E402,F401  (F-059: 拆分件再导出, 调用面不变)
                               record_checkpoint)
from failure_context import (_filter_capture_lines,  # noqa: E402  (F-060: 拆分件再导出, 调用面不变)
                              resolve_capture_timeout, _save_failure_context)
from capture_semihosting import (run_semihosting_session,  # noqa: E402  (F-061: 拆分件再导出)
                                 SemihostingTimeout)
from capture_sim import (DEFAULT_MACHINE, SimTimeout,  # noqa: E402  (F-150: sim 后端)
                         resolve_qemu, run_sim_session)
import esp_runtime  # noqa: E402  (F-174: builder=idf / flash=esptool / capture=uart 三后端)

GCC_BUILD = os.path.join(TOOLKIT_ROOT, "scripts", "gcc_build.py")         # 默认后端 (builder=gcc)
# Keil 退役桥 (2026-09-05 F-067b 拆 archive): 仓内不再保留 keil_*.py,
# 启动时按 env / 默认 archive 路径定位; 不在则明确报错指向 archive README.
# 唤起流程: 把 archive/scripts_legacy_keil/keil_*.py 拷回 <TOOLKIT>/scripts/legacy/keil/
# + archive/keil-error-db.json 拷回 <TOOLKIT>/data/, 然后 builder="keil" 即可.
DEFAULT_KEIL_ARCHIVE = r"<d-claude-root>\archive\embedded-toolkit-keil-legacy-20260905"
KEIL_BRIDGE_DIR = os.environ.get(
    "EMBEDDED_TOOLKIT_KEIL_ARCHIVE", DEFAULT_KEIL_ARCHIVE)
FEEDBACK_DB = os.path.join(TOOLKIT_ROOT, "scripts", "feedback_db.py")


def _keil_bridge_paths():
    r"""解析 Keil 退役桥路径; 启动时检测, 不在则 FileNotFoundError 指向 archive。

    返回 (keil_build, keil_analyze) 两个脚本绝对路径。

    2026-09-05 F-069a: 错误信息加引导 (L-2 fresh-checker 反馈)
    — `<d-claude-root>` 是路径占位符, 用户需替换为本机用户主目录盘符
    (默认 <d-claude-root> 即 D 盘, 详见 archive README 的「唤起本 archive 前必读」段)。
    """
    if not os.path.isdir(KEIL_BRIDGE_DIR):
        raise FileNotFoundError(
            f"Keil 退役桥不在 {KEIL_BRIDGE_DIR} (env=EMBEDDED_TOOLKIT_KEIL_ARCHIVE 或"
            f" 默认 archive 路径)。\n"
            f"⚠ 提示: 路径中 `<d-claude-root>` 是占位符, 请替换为本机用户主目录"
            f"盘符 (例如 <d-claude-root> 即本仓用户主目录, 默认 D 盘)。\n"
            f"按需唤起步骤见该目录 README.md 的「唤起本 archive 前必读」段, 或"
            f"从 <d-claude-root>\\archive\\embedded-toolkit-keil-legacy-20260905\\ "
            f"物理副本拷回。")
    build = os.path.join(KEIL_BRIDGE_DIR, "scripts_legacy_keil", "keil_build.py")
    analyze = os.path.join(KEIL_BRIDGE_DIR, "scripts_legacy_keil", "keil_analyze.py")
    if not (os.path.isfile(build) and os.path.isfile(analyze)):
        raise FileNotFoundError(
            f"Keil 退役桥目录存在但脚本缺失: {build} / {analyze}。"
            f"请核对 archive 副本完整性。")
    return build, analyze

# F-157: 本地 now_iso (UTC+8 硬编码) 删除, 收编 runtime_common 共享版
# (astimezone 本地时区) — 时区口径变化见 CHANGELOG。


def load_config(project_root: str) -> dict:
    """加载工程级配置 (.workbench/config.json, 兜底 .embeddedskills)

    JSON 损坏/非 UTF-8 抛 ConfigError (main() 捕获后友好退出, F-002)"""
    for marker in (".workbench/config.json", ".embeddedskills/config.json"):
        config_path = os.path.join(project_root, marker)
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ConfigError(f"{config_path} 不可解析: {e}") from e
    raise FileNotFoundError("工程内未找到 .workbench/config.json")


def run_py(script: str, args: list[str], timeout: int = 120) -> dict:
    """运行 Python 脚本并解析 JSON 输出"""
    cmd = [sys.executable, script] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, cwd=WORKSPACE
        )
        stdout = result.stdout.strip()
        if stdout:
            return json.loads(stdout)
        return {"status": "error", "message": f"no output from {os.path.basename(script)}",
                "stderr": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"{os.path.basename(script)} timed out after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON parse error: {e}",
                "raw_output": result.stdout[:500] if 'result' in dir() else ""}


def run_cmd(cmd: list[str], timeout: int = 60) -> dict:
    """运行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, cwd=WORKSPACE
        )
        # F-090: 判据只信 returncode — 旧版 `or 'verified' in stdout` 是
        # fail-open (OpenOCD 日志实际走 stderr, stdout 恒空; 非零退出 +
        # "not verified" 类文本会被误判成功)
        success = result.returncode == 0
        return {
            "status": "ok" if success else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-500:]
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"command timed out after {timeout}s"}


def step_build(config: dict, builder: str = "gcc",
               rebuild: bool = False) -> dict:
    """步骤 1: 编译 (按 config.json builder 字段切换后端: gcc | keil[legacy])"""
    if rebuild and builder not in ("gcc", "idf"):
        # YAGNI: keil 后端不接 --rebuild (blink legacy 不用该旗标)
        # F-174: idf 的 rebuild = fullclean + build (esp_runtime 内实现)
        return {"status": "error", "message": "--rebuild 仅支持 builder=gcc|idf"}
    # F-174: ESP32 后端 — 路由到 esp_runtime (契约对齐 gcc_build 返回值)
    if builder == "idf":
        return esp_runtime.step_build_idf(config, rebuild=rebuild,
                                          workspace=WORKSPACE)
    if builder == "gcc":
        gcc = config.get("gcc", {})
        project = gcc.get("project", "gcc-pilot/Makefile")
        target = gcc.get("target", "")
        log_dir = gcc.get("log_dir", ".workbench/build")
        # gcc/make 路径由 gcc_build 自行从 machine.json 解析
        args = ["rebuild" if rebuild else "build", "--project", project,
                "--target", target, "--log-dir", log_dir, "--json"]
        return run_py(GCC_BUILD, args, timeout=300)

    keil = config.get("keil", {})
    project = keil.get("project", "blink.uvprojx")
    target = keil.get("target", "STM32F103C8_Blink")
    log_dir = keil.get("log_dir", ".workbench/build")

    # uv4 由 keil_build 自行从 machine.json 解析 (机器路径只允许存在于 machine.json;
    # 2026-09-05 F-067b: keil_build 来自 archive 退役桥, 不在仓内)
    keil_build, _ = _keil_bridge_paths()
    args = ["build", "--project", project,
            "--target", target, "--log-dir", log_dir, "--json"]
    return run_py(keil_build, args, timeout=120)


def step_analyze(log_file: str, builder: str = "gcc",
                 build_metrics: dict | None = None) -> dict:
    """步骤 2: 编译日志诊断 (gcc/idf 后端自带 metrics, 跳过 ARMCC 知识库分析)"""
    if builder in ("gcc", "idf"):
        m = build_metrics or {}
        return {"status": "ok",
                "summary": {"errors": m.get("errors", 0),
                            "warnings": m.get("warnings", 0),
                            "matched": 0, "unmatched": 0}}
    # 2026-09-05 F-067b: keil_analyze 来自 archive 退役桥, 不在仓内
    _, keil_analyze = _keil_bridge_paths()
    return run_py(keil_analyze, [log_file, "--json"], timeout=30)


def step_flash(hex_file: str, config: dict | None = None) -> dict:
    """步骤 3: 烧录 (flash.backend 派发: openocd[默认] | esptool[F-174])"""
    if not hex_file:
        # F-007: blink 退役后旧默认 obj/blink.hex 已移除; --no-build 无产物须明说
        return {"status": "error",
                "message": ("无可用 hex 产物 (--no-build 且 state.json 无 "
                            "last_build.hex_file): 先完整构建一次")}
    if not os.path.exists(os.path.join(WORKSPACE, hex_file)):
        return {"status": "error", "message": f"hex file not found: {hex_file}"}

    # F-174: ESP32 esptool 后端 — 地址表交给 idf.py flash (esp_runtime 内)
    flash_cfg = (config or {}).get("flash", {}) or {}
    if flash_cfg.get("backend", "openocd") == "esptool":
        return esp_runtime.step_flash_esptool(flash_cfg, workspace=WORKSPACE)

    hex_abs = os.path.join(WORKSPACE, hex_file)
    try:
        pair = resolve_openocd_cfg(workspace=WORKSPACE)
    except OpenocdCfgError as e:
        return {"status": "error", "message": str(e)}
    cmd = [
        _openocd_exe(),
        "-f", pair["interface"],
        "-f", pair["target"],
        # F-163 (L-4): program 串拆序 — verify 不带 reset, 串尾 echo 构造性标记
        # 先于 exit (exit 截胡时标记 echo 不会在场, 这正是"脚本没跑完"的构造性
        # 证据方向); reset 由主流程 post_reset (F-129) 与 capture 会话各自的
        # reset halt 起点负责, 真机复验结论回填见 CHANGELOG F-163
        "-c", f"program {{{hex_abs}}} verify",
        "-c", ACTION_DONE_CMD,
        "-c", "exit",
    ]
    result = run_cmd(cmd, timeout=30)
    if result["status"] == "ok" and not marker_present(
            result.get("stdout", "") + result.get("stderr", "")):
        # F-163 (N-3): exit 0 但串尾标记缺席 = OpenOCD 提前退出, 脚本没跑完 —
        # 不许按成功入账 (构造性证据优先于退出码)
        return {"status": "error",
                "message": ("action_incomplete: 构造性标记缺席 — OpenOCD exit 0 "
                            "但 program 串未跑完 (串尾 echo 未出现), 拒绝按成功入账")}
    return result


class ConfigError(ValueError):
    """工程配置非法 (.workbench/config.json JSON 损坏 / 非 UTF-8)。
    与 M1 的 ExpectationError 同款前置拦截: 损坏文件报友好错误而非裸 traceback"""


# F-046: HIL 任务 (flash / capture) 入口来源白名单 (2026-09-02 方案四-1)
#   manual    = 开发者手动 CLI 调起 (默认, 兼容现有 VS Code verify 任务)
#   schedule  = 定时任务 / cron 拉起 (release 门禁脚本会用)
#   dispatch  = 事件触发 / Harness 派发 (AI 工作流注入 origin=dispatch)
# 白名单外值一律 ValueError: 防止上游 typo 静默回落 manual, 绕过审计
HIL_ORIGINS = ("manual", "schedule", "dispatch")


def enforce_hil_origin(origin: str, require_schedule_origin: bool) -> tuple[bool, str]:
    """F-046 守卫: HIL 步骤 (flash / capture) 是否放行.

    Args:
        origin: 任务来源, 必须在 HIL_ORIGINS 白名单内, 否则抛 ValueError
        require_schedule_origin: --require-schedule-origin 旗标, 开启时拒绝 manual

    Returns:
        (allowed, reason): allowed=False 时 reason 给用户看的提示文本
    """
    if origin not in HIL_ORIGINS:
        raise ValueError(
            f"task_origin 非法: {origin!r}, 须为 {HIL_ORIGINS} 之一")
    if require_schedule_origin and origin == "manual":
        return False, (
            "HIL 任务 (flash/capture) 拒绝 manual 触发: "
            "请通过 schedule (CI/release 门禁) 或 dispatch (Harness 派发) 拉起, "
            "或去掉 --require-schedule-origin 旗标")
    return True, ""


def append_audit_entry(workspace: str, origin: str, step: str,
                       status: str, command: str) -> None:
    """F-046 台账: 每次 HIL 步骤执行后追加一行 JSON 到 .workbench/state/audit.jsonl.

    append-only 写入, 单调追加, 不重写历史. 失败不阻断主流程 (台账是审计而非门禁).
    """
    audit_dir = os.path.join(workspace, ".workbench", "state")
    audit_path = os.path.join(audit_dir, "audit.jsonl")
    try:
        os.makedirs(audit_dir, exist_ok=True)
        entry = {
            "ts": now_iso(),
            "origin": origin,
            "step": step,
            "status": status,
            "command": command,
        }
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # 台账是审计而非门禁: 落盘失败不阻断主流程, stderr 告警即可
        print(f"[warn] audit 落盘失败: {audit_path}", file=sys.stderr)


def _release_hw_lease(lease) -> None:
    """F-145: 释放设备锁 (best-effort——释放失败只告警, 不影响本次结果;
    进程退出时 OS 自动放锁兜底)。"""
    if not lease or not lease.get("ok"):
        return
    rs = hw_lease.release(lease)
    if not rs.get("ok"):
        print(f"[warn] 设备锁释放失败: {rs.get('error', '')} "
              f"(进程退出时 OS 自动放锁, 不影响本次结果)", file=sys.stderr)


def hardfault_budget_s() -> int:
    """层 2 诊断(hardfault.py)的总预算秒数, 取自其模块常量。

    F-222: verify 在这里 spawn hardfault.py 子进程, 外层 `timeout` 必须
    **罩过**被调方的总预算, 否则内层重试从未跑完就被外层掐断(F-219 只把
    186s 显式化, 却没改这里的 60 —— 错配本体在此, 四审抓出属实)。

    用 `runpy` 读常量而**不 import**: import hardfault 会执行其模块级代码
    (机器探测/常量解析), 且 import 缓存会让 monkeypatch 测试失效; runpy
    只取值不驻留。读不到时退回 186 (= 3×60 + 2×3) 并在注释标明这是
    **兜底副本**, 上游改预算时须同步此处——故配了
    `test_hardfault_budget_matches_module_constant` 钉住两者一致。
    """
    try:
        import runpy
        ns = runpy.run_path(
            os.path.join(TOOLKIT_ROOT, "scripts", "hardfault.py"),
            run_name="__hf_budget_probe__")   # 非 __main__ → 不跑 main()
        val = ns.get("OPENOCD_DIAG_BUDGET_S")
        if isinstance(val, int) and val > 0:
            return val
    except Exception:
        pass
    return 186   # 兜底副本: 3×60s + 2×3s, 与 hardfault.py 同口径


def _hardfault_trigger(captured_text, capture_empty, flash_ran):
    """F-115 (B1): HardFault 诊断触发路径归因 (spec rtt-hardfault §3.2)。

    "marker"        = C 级 handler 显式标记在场 (主路径; 判定只查文本,
                      semihosting/RTT 后端无关——RTT 工程回填 handler 即走此路);
    "empty_fallback"= 本次确实烧录但捕获全空 (真兜底, 归因以层 2 诊断为准);
    None            = 不触发 (--no-build/--no-flash 空输出是预期,
                      08-12 误触发回归 hf_20260812_100345 守卫)。
    同帧病态输入 (标记在但行数 0) 归因取 marker——携带信息更强。"""
    if "HARDFAULT" in captured_text:
        return "marker"
    if capture_empty and flash_ran:
        return "empty_fallback"
    return None


# F-190/M-1: _esp_backend_mode 本体上收 runtime_common (单一事实源),
# 上方 import 再导出保持 verify._esp_backend_mode 调用面不变 (F-057 形态)——
# release.py G0.5 闸消费同一原件, 两份 OR 逻辑副本被 T2SingleSourceTests 钉死。


def _empty_capture_note(config) -> str:
    """F-188/N-3: capture 空兜底提示语按后端分流 (manifest/legacy 共用)。

    STM32 原文案逐字节不变; ESP 侧 HardFault 是 Cortex-M 概念, 空捕获归因
    串口/波特率/复位窗 (F-174/I-1 注释口径), 提示不出现 HardFault 字样。"""
    if _esp_backend_mode(config):
        return ("程序无输出（ESP 后端: 排查串口连接、波特率与复位窗"
                "是否覆盖启动输出）: ")
    return "程序无输出（无 HardFault 迹象）: "


def _step_durations_from(result: dict) -> tuple[list, dict]:
    """F-050 时长画像样本组装 (F-085 提取为共享 helper)。

    step_keys = 状态非 skipped/None 的实际跑过步骤; step_durations = 各步
    duration_sec (>0 才收)。原为早退路径内联逻辑 — 正常出口 F-085 补传
    step_durations 时按简报要求"复用早退组装逻辑、勿出新分叉"提取共享;
    两出口 filter 口径随之统一为严格形态 (status None 一律不收 — 真实
    运行 steps 必有 status, 行为不变)。"""
    step_keys = [k for k, v in (result.get("steps") or {}).items()
                 if isinstance(v, dict) and v.get("status") not in ("skipped", None)]
    step_durations = {}
    for k in step_keys:
        s = result["steps"].get(k, {})
        d = s.get("duration_sec")
        if isinstance(d, (int, float)) and d > 0:
            step_durations[k] = float(d)
    return step_keys, step_durations


def _record_checkpoint_early_exit(result: dict, args) -> None:
    """F-047 自审 (2026-09-03) Finding 2: 早退路径落台账.

    main() 各 sys.exit(1) 早退点 (build_failed / build_has_errors /
    flash_failed / capture_failed) 调用此函数, 让 progress 台账覆盖
    失败路径 — 不然 release audit 答不上"上次 build_failed 是哪天".

    与正常出口的 record_checkpoint 调用点不同: 早退时 result.steps
    已有部分填充, step_keys 来自已写入的 steps, step_durations
    来自已有的 duration_sec 字段.
    """
    if "WORKSPACE" not in globals() or WORKSPACE is None:
        return
    step_keys, step_durations = _step_durations_from(result)  # F-085: 共享组装
    record_checkpoint(
        workspace=WORKSPACE,
        status=result.get("status", "unknown"),
        duration_sec=result.get("elapsed_sec", 0.0),
        origin=getattr(args, "task_origin", "manual"),
        step_keys=step_keys,
        contract_hashes=result.get("contract_hashes") or {},
        step_durations=step_durations,
        gate_run=getattr(args, "gate_run", False),
    )


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


def verify(output: str, expect: list[str], description: str = "", expect_patterns: list[str] = None) -> dict:
    """步骤 5: AI 验证 (机器预处理 + 留给 Claude 最终判断)

    expect: 子串匹配列表; expect_patterns: 正则匹配列表 (需至少命中 1 次,
    如 ["TGL \\\\d+"] — 2026-08-16 review M1: 破坏 toggle 行为但不影响 init 的
    回归此前静默 PASS, 门禁必须能断言功能级事件)
    """
    matched = []
    missing = []
    for pattern in expect:
        if pattern in output:
            matched.append(pattern)
        else:
            missing.append(pattern)

    pat_matched = []
    pat_missing = []
    for pattern in (expect_patterns or []):
        if re.search(pattern, output):
            pat_matched.append(pattern)
        else:
            pat_missing.append(pattern)

    all_found = len(missing) == 0 and len(pat_missing) == 0
    return {
        "status": "ok" if all_found else "fail",
        "all_expected_found": all_found,
        "matched": matched,
        "missing": missing,
        "missing_patterns": pat_missing,
        "description": description,
        "needs_ai_judgement": True  # Claude 做最终判断
    }


def _finish_capture_timeout(proc, result: dict, capture_timeout: int,
                            max_retries: int, as_json: bool, lease=None,
                            method: str = "semihosting",
                            tool: str = "OpenOCD"):
    """F-003: OpenOCD 卡死超时 — 回收部分输出并诚实判 capture_failed。

    旧行为丢弃已收输出并按 capture ok(lines=0) 入账, 把"采集工具超时"
    伪装成"程序无输出"归因。正常路径 OpenOCD 必然经 sleep+halt+shutdown
    退出, 超时只发生在工具自身卡死 — 输出不可信但部分留证仍有价值。
    待真机终判: 修复前后需各跑一次真机确认归因链。
    F-150: method/tool 参数化 — sim 后端 (qemu) 复用同一收尸/归因出口。"""
    proc.kill()
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except Exception:
        stdout, stderr = "", ""
    partial = _filter_capture_lines((stdout or "") + (stderr or ""))
    result["steps"]["capture"] = {
        "status": "error", "method": method,
        "timeout_sec": capture_timeout,
        "lines": len(partial),
        "partial_output": _sanitize_text("\n".join(partial))[:2000],
        "error": (f"{tool} 未在 {capture_timeout + 30}s 内退出 — 采集超时"
                  "是工具故障, 非'程序无输出' (F-003)"),
    }
    result["status"] = "capture_failed"
    result["error"] = "capture 超时: OpenOCD 卡死, 部分输出已存失败现场"
    _release_hw_lease(lease)   # F-131: 超时出口也必须放掉硬件租约
    _save_failure_context(result, max_retries, capture_text="\n".join(partial), workspace=WORKSPACE)
    _output(result, as_json)
    sys.exit(1)


def _parse_args(argv=None):
    """F-160 (P1-4 拆分): argparse 装配独立函数 — main() 纯接线。"""
    parser = argparse.ArgumentParser(
        description="闭环验证 — Build → Analyze → Flash → Capture → Verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python verify.py                         # 完整流程 (捕获 10s)
  python verify.py --timeout 15            # 捕获 15 秒
  python verify.py --no-build              # 跳过编译
  python verify.py --no-build --no-flash   # 仅采集+验证
  python verify.py --json | jq .verdict    # JSON 输出
        """
    )
    parser.add_argument("--timeout", type=int, default=None,
                        help="采集超时秒数 (优先 config capture.duration_sec, 再默认 10)")
    parser.add_argument("--project", default=None, help="工程根目录 (默认从 cwd 向上发现)")
    parser.add_argument("--no-build", action="store_true", help="跳过编译步骤")
    parser.add_argument("--no-flash", action="store_true", help="跳过烧录步骤")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--retry", type=int, default=0,
                        help="构建/烧录失败自动重试次数 (默认 0, 最大 3)")
    parser.add_argument("--retry-delay", type=int, default=2,
                        help="重试间隔秒数 (默认 2)")
    parser.add_argument("--require-tgl", action="store_true",
                        help="断言 capture 中至少 1 条 TGL 事件 (手动按键验证用, "
                             "2026-08-16 review M1 门禁; 纯 boot 验证勿用)")
    parser.add_argument("--rebuild", action="store_true",
                        help="编译前先 clean (builder=gcc|idf; 发布门禁用)")
    parser.add_argument("--gate-run", dest="gate_run", action="store_true",
                        help="发布门禁发起的运行: 跳过 feedback_db 落账")
    parser.add_argument("--doctor", action="store_true",
                        help="环境预检: 打印 toolkit/Python/machine.json 三键/gcc/openocd/"
                             "make/SWD 连通性矩阵后退出 (诊断报告, 不做门禁判定, 退出码恒 0)")
    parser.add_argument("--task-origin", dest="task_origin",
                        choices=list(HIL_ORIGINS), default="manual",
                        help="F-046 HIL 任务来源 (manual=手动, schedule=定时/CI, "
                             "dispatch=事件/Harness), 默认 manual")
    parser.add_argument("--require-schedule-origin",
                        dest="require_schedule_origin", action="store_true",
                        help="F-046 硬卡旗标: 开启后拒绝 task_origin=manual, "
                             "CI / release 门禁脚本默认加这个旗标")
    parser.add_argument("--lease-wait", dest="lease_wait", type=float,
                        default=0.0,
                        help="F-145: 设备锁冲突时有界等待秒数 (默认 0 = "
                             "fail-fast; 等 span 含 flash+capture 全程)")
    parser.add_argument("--junit-xml", dest="junit_xml", default=None,
                        metavar="PATH",
                        help="F-147: 另写 JUnit XML 报告到 PATH (CI 测试面板"
                             "用; preflight 拒绝 = 期望全 skipped + 一条 "
                             "preflight error; 写失败记 junit_xml_error "
                             "并拉低退出码)")

    return parser.parse_args(argv)


def _run_doctor(args) -> None:
    """F-041: 诊断分支先于工程发现 —— doctor 不依赖 .workbench 工程。"""
    report = doctor_report()
    if args.json:
        output_json(report)
    else:
        _print_doctor(report)


class BadPatternError(Exception):
    """F-217: 期望正则非法。抛异常而非自行sys.exit, 交信封统一出口。

    F-216 审查 C-2: 旧实现末句直接 `sys.exit(1)`, 不经 _fail_with_envelope
    /_output —— `--json` 消费方拿到 **0 字节 stdout**, JUnit 也不落盘。
    `SystemExit` 被 main() 的 `except SystemExit: raise` 显式放行, 信封
    结构上够不着它。这正是本单要消灭的"最该报错时机器可读性归零"。
    """


def _fail_fast_on_bad_patterns(config):
    """F-216/F-217: 编译期校验期望正则, 非法即烧录前拦下。

    三号复审转述的 A1-③: 旧实现把 re.search 放在判定阶段, 非法正则要等
    构建+烧录+采集全跑完才抛 re.error——白烧一次板子。此处与 GAP-F-19 同处
    _prepare_context (烧录前)。

    **来源只两条, 且刻意不重复实现 manifest 侧判据**:
      · legacy config.verify.expect_patterns (F-104 迁移后已整体失效, 但
        配置里留个坏正则本身就是配置错误, 故仍校验)
      · manifest expectations.json —— **不手写解析**, 直接复用
        load_expectations()。它已含 E5 正则预编译判据
        (expectations.py:117, 注释明写"惰性编译会把非法正则拖到烧录后")。
        F-216 曾在这里手写一份拷贝并读错键名 (`items` 而非真实 schema 的
        `expectations`), 造出一条永不生效的假防线 (审查 C-1)。

    **CLI 不在此列**: F-216 曾声称覆盖 `--expect-pattern`, 但该参数在
    argparse 里根本不存在 (审查 H-1), 是条死分支。
    """
    bad = []

    def check(patterns, where):
        for p in (patterns or []):
            try:
                re.compile(p)
            except (re.error, TypeError) as e:   # F-217 M-3: 非字符串抛 TypeError
                bad.append(f"{where}: {p!r} — {e}")

    verify_cfg = (config.get("verify") or {})
    check(verify_cfg.get("expect_patterns"), "config.verify.expect_patterns")

    # manifest: 复用既有单一事实源, 不手写解析 (F-217 C-1)
    try:
        load_expectations(WORKSPACE)
    except ExpectationError as e:
        bad.append(f"expectations.json: {e}")
    except Exception as e:                        # 损坏等非预期形态也不放过
        bad.append(f"expectations.json 不可读: {type(e).__name__}: {e}")

    if bad:
        raise BadPatternError(
            "期望正则非法 (烧录前拦截, 不白跑一轮硬件):\n  - "
            + "\n  - ".join(bad))


def _prepare_context(args):
    """F-160 (P1-4 拆分): 工程根发现 + 配置/版本装载。"""

    # 工程根: --project > cwd 向上发现
    global WORKSPACE
    WORKSPACE = args.project or find_project_root(os.getcwd())
    if not WORKSPACE:
        print("错误: 未找到工程根 (含 .workbench/config.json), 请在工程目录内运行或用 --project 指定",
              file=sys.stderr)
        sys.exit(1)
    WORKSPACE = os.path.abspath(WORKSPACE)
    try:
        config = load_config(WORKSPACE)
    except ConfigError as e:
        print(f"错误: 工程配置非法: {e}", file=sys.stderr)
        sys.exit(1)
    # GAP-F-19 (F-190/T3, 维护者裁定 fail-fast): 三标记任一在场而三键不齐/
    # 取值非法的混配工程, 在任何构建/烧录动作之前显式报错退 1——宁可停也
    # 不许拿缺省派发面 (openocd/semihosting) 去 ESP 工程上跑 (F-188"只列
    # 不改"面的收口)。规则本体在 runtime_common (单一事实源)。
    problems = esp_backend_config_errors(config)
    if problems:
        print("错误: ESP 后端配置混配 (GAP-F-19 fail-fast): 检出 ESP 标记, "
              "但 builder / flash.backend / capture.backend 三键必须齐且"
              "取值在 ESP 合法集:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        print('  正确配法示例: {"builder": "idf", "flash": {"backend": '
              '"esptool", "port": "COM3"}, "capture": {"backend": "uart", '
              '"port": "COM3"}}', file=sys.stderr)
        sys.exit(1)
    builder = config.get("builder", "gcc")   # 构建后端 (gcc | keil[legacy], 2026-08-28 默认翻转为 gcc)

    # F-216: 期望正则的**编译期**校验 —— 必须在任何构建/烧录之前。
    # 旧实现把 re.search 放在判定阶段 (verify()), 非法正则要等烧完板子
    # 才炸, 白烧一次且现场难归因。与上方 GAP-F-19 同属"烧录前拦住"纪律。
    # F-217: 改抛 BadPatternError 而非自行 sys.exit, 交 main() 的信封统一
    # 出口 (旧实现绕过信封, --json 下 stdout 零字节)。
    _fail_fast_on_bad_patterns(config)

    # 工具库版本检查: 工程要求的最低版本
    cfg_min = config.get("toolkit_min_version")
    if cfg_min and not version_ok(toolkit_version(), cfg_min):
        print(f"错误: 工具库版本 {toolkit_version()} 低于工程要求 {cfg_min}", file=sys.stderr)
        sys.exit(1)

    return config, builder


def main():
    """F-216: 统一异常信封。

    三号复审转述的 A1 (异常路径绕过失败信封) 实跑复现; F-217 复审后更正如下:

      ① ESP 配置缺失 — resolve_idf_path 抛 EspConfigError, 调用链无 try。
         **F-217 L-2 更正**: 实测 ESP 三键齐备 + idf 路径不可达时, 走的是
         正常失败路径(有 status/error, error_type 为None), **不进本信封**;
         混配后端则被 GAP-F-19 提前拦掉。原写的"① 由本信封兜住"未获复现,
         信封本身仍正确, 只是这个 motivating case 站不住。
      ② --project 指错目录 — _prepare_context 只接 ConfigError, 接不住
         FileNotFoundError → 裸 traceback, `--json` 下 stdout 零字节。
         **F-217 H-4 更正**: F-216 写"退出码 0, CI 会误判成功"是错的——
         用修复前代码实跑三种变体全部 EXIT=1。真实危害是机器可读性归零,
         不是 CI 误判成功。F-216 把一个推断写成了实测结论。
      ③ 非法期望正则拖到 flash 之后才炸。**F-217 C-1 更正**: manifest
         侧本就由 load_expectations 的 E5判据在烧录前拦截, "白烧一次板子"
         在该侧不成立; 真正缺的是 legacy config.verify.expect_patterns。

    本信封的职责: 任何未捕获异常都转成 _output 的标准失败结构, 走既有
    唯一出口 (evidence 字段 + JUnit 旁路), 并补写 last_failure.json
    ——与"失败现场诚实化"的承诺对齐。③ 属校验时机问题, 见
    _fail_fast_on_bad_patterns。
    """
    args = _parse_args()

    global _JUNIT_OUT
    _JUNIT_OUT = args.junit_xml

    if args.doctor:
        _run_doctor(args)
        return

    try:
        _run_pipeline(args)
    except SystemExit:
        raise                       # argparse 自身的用法错误, 语义已明确
    except BaseException as e:      # noqa: BLE001 — 信封边界, 刻意兜全量
        _fail_with_envelope(e, args)


def _fail_with_envelope(exc: BaseException, args) -> None:
    """F-216: 把未捕获异常转成标准失败结果, 走 _output 唯一出口。

    刻意用 BaseException: 这里就是"什么都得接住"的边界——内核级异常
    (MemoryError / KeyboardInterrupt) 逃出去同样会让调用方拿到 traceback
    而非结构化现场, 与本仓"失败现场诚实化"承诺相悖。KeyboardInterrupt
    仍按常规语义抛给上层处理 Windows 的 Ctrl-C, 但先落现场。
    """
    if isinstance(exc, KeyboardInterrupt):
        kind, msg = "interrupted", "用户中断 (Ctrl-C)"
    else:
        kind = "internal_error"
        msg = f"{type(exc).__name__}: {exc}"
    result = {
        "status": kind,
        "error": msg,
        "steps": {},
        "error_type": type(exc).__name__,
        "traceback": traceback.format_exc(),
        "evidence": "static",      # _output 会覆写, 此处仅保键存在
    }
    # last_failure.json: 异常路径此前完全不写, Agent 无现场可读 (F-216)
    # 工程本身不可用时 (如 --project 指错目录, WORKSPACE 指向一个没有
    # .workbench/config.json 的路径), 不往那儿写现场——那等于在校验失败
    # 的目录里凭空造出 .workbench/ 结构。改落 toolkit 自己的 build 目录。
    ws = WORKSPACE
    if not ws or not os.path.isfile(os.path.join(ws, ".workbench",
                                                  "config.json")):
        ws = TOOLKIT_ROOT
    try:
        # F-217 M-2: 原先此处又写了一遍函数内 import, 而模块顶层 (:72-73)
        # 已绑定同一符号 —— 函数内 import 使 mock.patch.object(verify,
        # "_save_failure_context") 完全失效, "写现场失败不掩盖原异常"
        # 这条路径实际不可测。直接用顶层已绑定的符号。
        result["agent_hint"] = (
            "内部错误: 这是工具链或配置问题, 不是被测工程的问题。"
            "检查 --project 指向的目录是否含 .workbench/config.json, "
            "以及 machine.json 的工具链路径。完整 traceback 见本文件 "
            "traceback 字段。")
        # workspace 收的是**工程根** (_save_failure_context 内部再拼
        # .workbench/build/), 与既有三处调用点同口径。
        _save_failure_context(result, max_retries=0, capture_text="",
                              workspace=ws)
        # F-217 M-1: _save_failure_context 内部写失败是 except...pass 静默
        # 的, 故写完**复查**文件真在, 不在就不宣称路径——否则信封会在最该
        # 诚实的时候撒谎(人读分支还会照着这个不存在的路径打印"现场: ...")。
        ctx_path = os.path.join(ws, ".workbench", "build", "last_failure.json")
        if os.path.isfile(ctx_path):
            result["failure_context_path"] = ctx_path
        else:
            result["failure_context_write_failed"] = True
            result["failure_context_expected_path"] = ctx_path
    except Exception:                      # 写现场失败不得掩盖原始异常
        result["failure_context_write_failed"] = True
    print(f"错误: {msg}", file=sys.stderr)
    if isinstance(exc, KeyboardInterrupt):
        raise
    _output(result, as_json=getattr(args, "json", False))
    sys.exit(1)


def _run_pipeline(args):
    """F-160 (P1-4 拆分): 编排骨架 — 各段实现见 _prepare_context/
    _run_build_step/_run_flash_step/_run_capture_step/_run_judgement/
    _finalize_run; 行为零变更搬移 (硬验收: 全量测试零修改全绿 +
    --json 输出逐字段结构一致)。"""
    config, builder = _prepare_context(args)

    # Clamp retry
    max_retries = max(0, min(args.retry, 3))
    retry_delay = max(1, args.retry_delay)

    started_at = now_iso()
    started_ts = time.time()

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
    # F-104 迁移告警: manifest 存在时 legacy expect/expect_patterns 整体失效
    # 曾是静默行为——工程同时持有两套期望配置时, 编辑 config.verify.expect
    # 的人得不到任何反馈, 误以为改动生效 (审计 P3 登记项)。只告警不改行为。
    if expect_mode == "manifest":
        _legacy_shadowed = (expect
                            or verify_cfg.get("expect_patterns"))
        if _legacy_shadowed:
            print("提示: .workbench/expectations.json 存在, "
                  "config.verify.expect/expect_patterns 不再生效 "
                  "(F-104 迁移告警) — 请迁移到期望清单或移除旧配置。",
                  file=sys.stderr)

    result = {
        "pipeline": "build → analyze → flash → capture → verify",
        "started_at": started_at,
        "workspace": WORKSPACE,
        "toolkit_version": toolkit_version(),
        "expect_mode": expect_mode,
        "contract_hashes": contract_hashes(WORKSPACE, expect_mode == "manifest"),
        "expect": expect,
        "description": description,
        "retry_config": {"max_retries": max_retries, "retry_delay": retry_delay},
        "steps": {}
    }

    hex_file, elf_file = _run_build_step(
        args, config, builder, result, max_retries, retry_delay)

    # F-150: sim 后端在 Step 1 前就由 config 决定 — 全程无烧录无探针
    cap_backend = (config.get("capture", {}) or {}).get("backend", "semihosting")
    sim_cfg = (config.get("capture", {}) or {}).get("sim", {}) or {}
    sim_mode = (cap_backend == "sim")

    lease = _run_flash_step(args, config, result, hex_file, sim_mode,
                            max_retries, retry_delay)

    captured_text, captured_lines, capture_timeout = _run_capture_step(
        args, config, result, lease, sim_mode, cap_backend, sim_cfg,
        max_retries, elf_file)

    _run_judgement(args, config, result, captured_text, captured_lines,
                   capture_timeout, expect, description, expectations,
                   expect_mode, started_ts)

    _finalize_run(args, config, result, lease, max_retries, captured_text)


def _run_build_step(args, config, builder, result, max_retries, retry_delay):
    """Step 1-2: Build + Analyze (with retry) — 失败早退 (sys.exit) 原样保留。"""

    # ---- Step 1-2: Build + Analyze (with retry) ----
    if not args.no_build:
        build_t0 = time.time()  # F-050: step-level timing, 给 duration_profile 用
        build_attempts = []
        build_ok = False
        analyze = None   # F-008: build 循环内的分析结果, 循环后复用不再双跑
        elf_file = ""    # F-150: sim 后端内核 (gcc details.elf_file)
        for attempt in range(max_retries + 1):
            build = step_build(config, builder, rebuild=args.rebuild)
            build_info = {
                "attempt": attempt + 1,
                "status": build.get("status", "error"),
                "errors": build.get("metrics", {}).get("errors", -1),
                "warnings": build.get("metrics", {}).get("warnings", -1),
            }
            build_attempts.append(build_info)

            if build.get("status") == "ok":
                log_file = build.get("details", {}).get("log_file", "")
                hex_file = build.get("details", {}).get("hex_file", "")
                elf_file = build.get("details", {}).get("elf_file", "")  # F-150: sim 内核

                if log_file or builder in ("gcc", "idf"):
                    analyze = step_analyze(log_file, builder, build.get("metrics"))
                    if analyze.get("status") == "ok":
                        build_ok = True
                        break
                    # F-095: analyze 报 error = 编译器跑通但产物有错 → 重试
                    # 同样的源码大概率还是 error, 纯耗重试预算; break 后由
                    # 循环外的 build_has_errors 分支区分两种失败语义
                    # （此前 analyze error 继续重试 → 恒 build_failed,
                    # build_has_errors 是死分支, F-088 登记维护者拍板修复）。
                    if analyze.get("status") == "error":
                        break
            # else: retry
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not build_ok:
            # F-095: analyze error = 编译器跑通但产物有错, 与"构建没跑成"
            # 语义不同 → 分别落 build_has_errors / build_failed（此前
            # analyze error 不 break, build_has_errors 恒不可达, F-088 登记）
            if analyze is not None and analyze.get("status") == "error":
                result["steps"]["build"] = {
                    "status": "build_has_errors",
                    "attempts": build_attempts,
                    "retry_count": len(build_attempts) - 1,
                }
                result["status"] = "build_has_errors"
                result["error"] = (f"Build has "
                                   f"{analyze.get('summary', {}).get('errors', 0)} error(s)")
                _save_failure_context(result, max_retries, workspace=WORKSPACE)
                _output(result, args.json)
                _record_checkpoint_early_exit(result, args)
                sys.exit(1)
            result["steps"]["build"] = {
                "status": "build_failed",
                "attempts": build_attempts,
                "retry_count": len(build_attempts) - 1,
            }
            result["status"] = "build_failed"
            result["error"] = f"Build failed after {len(build_attempts)} attempt(s)"
            # Save failure context for Agent analysis
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        result["steps"]["build"] = {
            "status": "ok",
            "summary": build.get("summary", ""),
            "errors": build.get("metrics", {}).get("errors", -1),
            "warnings": build.get("metrics", {}).get("warnings", -1),
            "log_file": log_file,
            "hex_file": hex_file,
            "attempts": build_attempts,
            "retry_count": len(build_attempts) - 1,
            "duration_sec": round(time.time() - build_t0, 1),  # F-050
        }

        # ---- Step 2: Analyze ----
        # F-008: 复用 build 循环内已算出的 analyze (keil 后端曾双跑 keil_analyze, 历史);
        # 循环正常 break 时 analyze 必已赋值, None 仅在异常组合下出现
        if analyze is None:
            analyze = {"status": "error"}
        result["steps"]["analyze"] = {
            "status": analyze.get("status", "error"),
            "errors": analyze.get("summary", {}).get("errors", 0),
            "warnings": analyze.get("summary", {}).get("warnings", 0),
            "matched": analyze.get("summary", {}).get("matched", 0),
            "unmatched": analyze.get("summary", {}).get("unmatched", 0),
        }
        if analyze.get("status") == "error":
            result["status"] = "build_has_errors"
            result["error"] = f"Build has {analyze.get('summary', {}).get('errors', 0)} error(s)"
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        if analyze.get("summary", {}).get("unmatched", 0) > 0:
            result["steps"]["analyze"]["review_needed"] = True
            result["steps"]["analyze"]["review_command"] = "/review:build"
            result["steps"]["analyze"]["review_note"] = (
                "One or more build errors were not found in the knowledge base. "
                "Use /review:build to run adversarial review before applying fixes."
            )
    else:
        # 从 state.json 读取上次构建产物 (gcc/keil 后端 build 时写入)
        # F-007: 无产物走 step_flash 的明确报错, 不再回落 blink 退役残留路径
        hex_file = ""
        elf_file = ""
        try:
            state_path = os.path.join(WORKSPACE, ".workbench", "state.json")
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                hex_file = state.get("last_build", {}).get("hex_file", "")
                # F-150: sim 后端的内核 = 上次构建 elf 产物
                elf_file = (state.get("last_build", {}).get("elf_file", "")
                            or state.get("last_build", {}).get("artifacts", {})
                            .get("elf_file", ""))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            hex_file = ""   # state.json 损坏不再裸 traceback, 走无产物报错
        result["steps"]["build"] = {"status": "skipped"}
        result["steps"]["analyze"] = {"status": "skipped"}

    return hex_file, elf_file


def _run_flash_step(args, config, result, hex_file, sim_mode, max_retries,
                    retry_delay):
    """Step 3: Flash (with retry) + 设备锁获取 — 返回 lease (sim 模式为 None)。"""

    # ---- Step 3: Flash (with retry) ----
    # F-046: HIL 入口守卫 — 拒 manual 时给友好提示, exit 2 (区别于 0=成功/1=失败)
    # F-145: 机器级设备锁 — flash+capture 段全程持有, 同一探针/板子同时只被
    # 一个 verify (或 openocd_run flash/erase) 占用; 冲突方拿 resource_busy +
    # 持有者信息 fail-fast (exit 2), --lease-wait 可有界等待。
    # F-150: sim 后端不触探针 → 不持锁 (CI 可并行)。
    lease = None
    if not sim_mode:
        lease = hw_lease.acquire(
            purpose=f"verify flash+capture ({os.path.basename(WORKSPACE)})",
            workspace=WORKSPACE,
            wait=getattr(args, "lease_wait", 0.0))
        if not lease.get("ok"):
            print(f"错误: {lease.get('error', '设备锁获取失败')}", file=sys.stderr)
            sys.exit(2)
    if sim_mode:
        result["steps"]["flash"] = {
            "status": "skipped",
            "reason": "F-150 sim 后端: qemu 直接加载 elf, 无烧录步骤",
        }
    elif not args.no_flash:
        flash_t0 = time.time()  # F-050: step-level timing
        # F-046 守卫 (F-050 自审发现: 此前曾误写两行同参数调用, 已删冗余)
        allowed, deny_reason = enforce_hil_origin(
            args.task_origin, args.require_schedule_origin)
        if not allowed:
            _release_hw_lease(lease)
            print(f"错误: {deny_reason}", file=sys.stderr)
            sys.exit(2)
        flash_attempts = []
        flash_ok = False
        for attempt in range(max_retries + 1):
            flash = step_flash(hex_file, config)
            # F-163 审核 Minor: message-only 错误 dict (无 hex / action_incomplete)
            # 不带 stderr/stdout——消费端必须回退读 message, 否则根因在 JSON 里隐身
            _flash_msg = (flash.get("stderr") or flash.get("stdout")
                          or flash.get("message", ""))
            flash_info = {
                "attempt": attempt + 1,
                "status": flash.get("status", "error"),
                "message": _flash_msg[-200:],
            }
            flash_attempts.append(flash_info)
            if flash.get("status") == "ok":
                flash_ok = True
                break
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not flash_ok:
            result["steps"]["flash"] = {
                "status": "flash_failed",
                "attempts": flash_attempts,
                "retry_count": len(flash_attempts) - 1,
            }
            result["status"] = "flash_failed"
            result["error"] = f"Flash failed after {len(flash_attempts)} attempt(s)"
            _release_hw_lease(lease)
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        result["steps"]["flash"] = {
            "status": "ok",
            "message": flash.get("stderr", flash.get("stdout", ""))[-300:],
            "attempts": flash_attempts,
            "retry_count": len(flash_attempts) - 1,
            "origin": args.task_origin,   # F-046: 审计标记, release audit 一眼可辨手动 vs CI
            "duration_sec": round(time.time() - flash_t0, 1),  # F-050
        }
        # F-046: 台账落盘 (audit-only, 失败不阻断主流程)
        append_audit_entry(WORKSPACE, args.task_origin, "flash", "ok",
                           " ".join(sys.argv))
    else:
        result["steps"]["flash"] = {"status": "skipped"}

    return lease


def _run_capture_step(args, config, result, lease, sim_mode, cap_backend,
                      sim_cfg, max_retries, elf_file):
    """Step 4: Capture (semihosting 默认 | rtt | sim) — 返回 (captured_text,
    captured_lines, capture_timeout)。"""

    # ---- Step 4: Capture (semihosting 默认 | rtt | F-150 sim) ----
    # 共同原则: reset halt 确定性起点 (2026-08-16 教训), 行过滤后进 verify()
    # F-046: capture 也是 HIL 步骤 — 守卫幂等, 第二次调用也是放行结果
    # F-150: sim 后端非硬件步骤 — 不跑 HIL 守卫 (CI 免 manual 限制),
    # 不落 F-046 台账, 不持设备锁 (见 Step 3)。
    capture_t0 = time.time()  # F-050: step-level timing
    if not sim_mode:
        allowed_capture, deny_reason_capture = enforce_hil_origin(
            args.task_origin, args.require_schedule_origin)
        if not allowed_capture:
            _release_hw_lease(lease)
            print(f"错误: {deny_reason_capture}", file=sys.stderr)
            sys.exit(2)
    capture_started = time.time()
    capture_timeout = resolve_capture_timeout(args.timeout, config.get("capture", {}))
    # F-016: 预告窗口 (stderr, 不污染 --json 的 stdout); 人工输入期望需知何时按键
    print("[capture] 采集窗 %ds 自烧录/复位起开启 — 含人工输入期望请全程按键"
          % capture_timeout, file=sys.stderr)
    captured_lines = []
    captured_text = ""

    if sim_mode:
        # ---- F-150: sim 后端 — qemu 直接加载 elf, 判定逻辑零改动 ----
        try:
            qemu_exe, qemu_source = resolve_qemu(sim_cfg)
            kernel = sim_cfg.get("kernel", "") or elf_file
            if not kernel:
                raise RuntimeError(
                    "sim 后端缺 elf 内核: 构建 details.elf_file 与 "
                    "config capture.sim.kernel 均不可得 (先完整构建一次)")
            if not os.path.isabs(kernel):
                kernel = os.path.join(WORKSPACE, kernel)
            if not os.path.isfile(kernel):
                raise RuntimeError(f"sim 内核不存在: {kernel}")
            stdout_sim, stderr_sim = run_sim_session(
                capture_timeout, sim_cfg.get("machine", DEFAULT_MACHINE),
                kernel, qemu_exe=qemu_exe, sim_cfg=sim_cfg,
                workspace=WORKSPACE)
        except SimTimeout as _to:
            _finish_capture_timeout(_to.proc, result, capture_timeout,
                                    max_retries, args.json, lease=lease,
                                    method="sim", tool="qemu")
        except Exception as e:
            result["steps"]["capture"] = {
                "status": "error", "method": "sim", "error": str(e)
            }
            result["status"] = "capture_failed"
            result["error"] = str(e)
            _release_hw_lease(lease)
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)
        captured_lines = _filter_capture_lines(stdout_sim + stderr_sim)
        captured_text = "\n".join(captured_lines)
        result["steps"]["capture"] = {
            "status": "ok",
            "method": "sim",
            "machine": sim_cfg.get("machine", DEFAULT_MACHINE),
            "kernel": os.path.relpath(kernel, WORKSPACE).replace(os.sep, "/"),
            "qemu_source": qemu_source,
            "timeout_sec": capture_timeout,
            "lines": len(captured_lines),
            "duration_sec": round(time.time() - capture_t0, 1),
            "origin": args.task_origin,   # 溯源一致; sim 非 HIL 不落台账
        }
    elif cap_backend == "rtt":
        cap = _step_capture_rtt(capture_timeout, config.get("capture", {}), WORKSPACE)
        if cap.get("status") != "ok":
            result["steps"]["capture"] = {
                k: v for k, v in cap.items() if not k.startswith("_")
            }
            result["status"] = "capture_failed"
            result["error"] = cap.get("error", "rtt capture failed")
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
        # F-046: 台账落盘 (RTT 后端独立标记 origin, release audit 可按 origin 聚合)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))
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
            # ESP panic 文本标记上账 (spec §4.3); 4b 的 HardFault 归因链是
            # Cortex-M 专属 (CFSR/OpenOCD 寄存器), 对 ESP 文本天然不触发。
            # F-200: panic 随链离线符号化 (spec §4.3 后置票) — 只加信息
            # 不改判据 (status/judge/expect 零动); 全链 fail-soft 不抛穿。
            result["esp_panic"] = True
            print("[capture] 检出 ESP panic 文本标记 — 定性交 AI judge",
                  file=sys.stderr)
            sym = esp_runtime.symbolize_esp_panic(captured_text, WORKSPACE)
            result["esp_panic_symbolized"] = sym
            if sym.get("available"):
                print(esp_runtime.format_symbol_box(sym))
            else:
                print("[capture] ESP panic 符号化不可用 (%s) — 原文 "
                      "backtrace 已随捕获文本入账" % sym.get("reason", "?"),
                      file=sys.stderr)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))
    else:
        # 直接调 OpenOCD: init → reset halt → semihosting enable → resume → sleep → halt → shutdown
        # 这是手工验证过的可靠方式（曾有独立 openocd_semihosting.py，F-028 删除，git 史可回放）
        # reset halt: 确定性起点 — 目标可能停在上一会话的 BKPT 冻结处 (printf 中途)
        # 或 boot 中段 (I2C2 BUSY 等待), 仅 halt 续跑会得到不完整 boot 输出 (2026-08-16 教训)
        # cmd 构建与 Popen/communicate 已下沉 capture_semihosting (F-061);
        # 超时收尸留守: _finish_capture_timeout 携带 proc 完成 F-003 归因链
        try:
            stdout, stderr = run_semihosting_session(capture_timeout, WORKSPACE)
            captured_lines = _filter_capture_lines(stdout + stderr)

        except SemihostingTimeout as _to:
            _finish_capture_timeout(_to.proc, result, capture_timeout,
                                    max_retries, args.json, lease=lease)
        except Exception as e:
            result["steps"]["capture"] = {
                "status": "error", "method": "semihosting", "error": str(e)
            }
            result["status"] = "capture_failed"
            result["error"] = str(e)
            _release_hw_lease(lease)
            _save_failure_context(result, max_retries, workspace=WORKSPACE)
            _output(result, args.json)
            # F-047 自审 Finding 2: 早退路径也必须落 checkpoint
            _record_checkpoint_early_exit(result, args)
            sys.exit(1)   # 失败早退必须非零 (审计: 原先恒 0 误导脚本化调用方)

        captured_text = "\n".join(captured_lines)
        capture_elapsed = time.time() - capture_started

        result["steps"]["capture"] = {
            "status": "ok",
            "method": "semihosting",
            "timeout_sec": capture_timeout,
            "lines": len(captured_lines),
            "duration_sec": round(capture_elapsed, 1),
            "raw_length": len(captured_text),
            "origin": args.task_origin,   # F-046: 审计标记
        }
        result["steps"]["capture"]["duration_sec"] = round(
            time.time() - capture_t0, 1)  # F-050: 含守卫 + OpenOCD 全部耗时
        # F-046: 台账落盘 (semihosting 后端, 同上)
        append_audit_entry(WORKSPACE, args.task_origin, "capture", "ok",
                           " ".join(sys.argv))

    return captured_text, captured_lines, capture_timeout


def _run_judgement(args, config, result, captured_text, captured_lines,
                   capture_timeout, expect, description, expectations,
                   expect_mode, started_ts):
    """Step 4b/4c/5: HardFault 检测 + 物理门控 + 四态判定 + 顶层 status。"""
    verify_cfg = config.get("verify", {})

    # ---- Step 4b: HardFault 自动检测 ----
    # 触发条件 (修复 2026-08-12):
    #   capture 空 ≠ HardFault — --no-build/--no-flash 时空输出是预期行为,
    #   旧逻辑在此场景误触发诊断并污染反馈库 (hf_20260812_100345 事件)。
    #   仅当输出含显式 HARDFAULT 标记 (C 级 handler 打印的 === HARDFAULT ===)
    #   或"本次确实烧录过但完全无输出"时才运行诊断, 归因以诊断结果为准。
    capture_empty = (len(captured_lines) == 0)
    flash_ran = (not args.no_flash) and \
        result.get("steps", {}).get("flash", {}).get("status") == "ok"
    hf_trigger = _hardfault_trigger(captured_text, capture_empty, flash_ran)
    # F-174/I-1: ESP 模式下双路全闸——层 2 经 OpenOCD 连 ST-Link, 语义仅
    # Cortex-M。空捕获在 ESP 侧归因串口/复位窗, 不是 HardFault; 若正文真出现
    # HARDFAULT 字样, 跨读另一台板子的 live 寄存器比不诊断更危险。ESP panic
    # 归因走 capture 段 esp_panic 文本标记 + AI 判定 (spec §4.3)。
    if hf_trigger and _esp_backend_mode(config):
        hf_trigger = None
    has_hardfault = hf_trigger == "marker"
    if hf_trigger:
        hf_path = os.path.join(TOOLKIT_ROOT, "scripts", "hardfault.py")
        if os.path.exists(hf_path):
            try:
                hf_cmd = [sys.executable, hf_path, "--json"]
                hf_kw = {}
                # F-116/H-1: marker 路径把捕获文本递给层 2, 解析 [HF] PC=/LR=
                # 行 → fault_site (真实故障点)。live PC 在自旋场景恒指 handler。
                if hf_trigger == "marker" and "[HF] PC=" in captured_text:
                    hf_cmd += ["--fault-text", "-"]
                    hf_kw["input"] = captured_text
                hf_result = subprocess.run(
                    hf_cmd,
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace',
                    # F-222: 外层必须罩过层 2 的**总**预算。
                    # F-219 只把 hardfault.py 内的 3×60+2×3=186s 显式化为
                    # OPENOCD_DIAG_BUDGET_S, 却没动这里的 60 —— 于是**在
                    # verify 链路里层 2 必然被外层掐死在第 1 次尝试**,
                    # 3 次重试从未跑到过第二遍 (改善只惠及独立运行
                    # hardfault.py 的场景)。四审抓出, 属实: 那不是"预算错配
                    # 已修复", 只做了显式化+超时可辨识, 错配本体在此。
                    # 引用常量而非重写 186 —— 两处数字若各写一份必然漂移。
                    timeout=max(60, hardfault_budget_s()), cwd=WORKSPACE,
                    **hf_kw
                )
                if hf_result.returncode == 0 and hf_result.stdout.strip():
                    hf_data = json.loads(hf_result.stdout)
                    hf_fault_type = hf_data.get("fault_type", "no_fault")
                    # 兜底诊断: 无 HARDFAULT 标记但诊断出真实故障位 → 视为 HardFault
                    if hf_fault_type != "no_fault":
                        has_hardfault = True
                    result["steps"]["hardfault"] = {
                        "status": ("hardfault_detected" if hf_fault_type != "no_fault"
                                   else "checked_no_fault"),
                        "trigger": hf_trigger,   # F-115 归因: marker/empty_fallback
                        "fault_type": hf_fault_type,
                        "diagnosis": _sanitize_text(hf_data.get("diagnosis", "")),
                        "registers": hf_data.get("registers", {}),
                        "fault_registers": hf_data.get("fault_registers", {}),
                        "resolved": hf_data.get("resolved", {}),
                    }
                    if hf_data.get("fault_site"):
                        result["steps"]["hardfault"]["fault_site"] = \
                            hf_data["fault_site"]
                    # 注入点 ②: HardFault 检测到 → 标记需要对立审查
                    if hf_fault_type != "no_fault":
                        result["steps"]["hardfault"]["review_needed"] = True
                        result["steps"]["hardfault"]["review_command"] = "/review:hardfault"
                        result["steps"]["hardfault"]["review_note"] = (
                            "HardFault detected. Use /review:hardfault to run "
                            "adversarial review of the root cause analysis before fixing code."
                        )
                else:
                    result["steps"]["hardfault"] = {
                        "status": "error",
                        "trigger": hf_trigger,   # F-115
                        "message": ("Diagnosis failed" +
                                    (f": {hf_result.stderr[-200:]}" if hf_result.stderr else ""))
                    }
            except Exception as e:
                result["steps"]["hardfault"] = {
                    "status": "error", "trigger": hf_trigger,  # F-115
                    "message": str(e)
                }

    # ---- Step 4c: 物理层门控 (TIMING_FAIL) ----
    # GPIO Toggle 频率检测: 验证时序正确性 (代码在正确的时间做了该做的事)
    # F-188/N-4: physical_gate 经 OpenOCD 采 GPIO, 语义仅 Cortex-M — I-1 同构
    # 第三处 (hardfault 层 2 / post_reset 之后), 闸打在调用侧,
    # scripts/physical_gate.py 本体零触碰。skipped+reason 形态对齐
    # F-150 sim flash skip (verify.py "F-150 sim 后端" 分支)。
    if _esp_backend_mode(config):
        physical = {
            "status": "skipped",
            "reason": ("F-188/N-4 ESP 后端: physical_gate 经 OpenOCD 采 "
                       "GPIO, OpenOCD/ST-Link 不在 ESP 链路, 步骤抑制"),
        }
    else:
        physical = step_physical_gate(config.get("physical_gate", {}), timeout=capture_timeout, workspace=WORKSPACE)
    result["steps"]["physical_gate"] = physical

    # ---- Step 5: Verify ----
    # 如果有 HardFault，自动判定失败
    if has_hardfault and "hardfault" in result.get("steps", {}):
        verification_result = {
            "status": "fail",
            "all_expected_found": False,
            "matched": [],
            "missing": expect,
            "description": f"HardFault detected: {result['steps']['hardfault'].get('fault_type', 'unknown')}",
            "needs_ai_judgement": True,
        }
    elif physical.get("status") == "timing_fail":
        # 物理层门控失败: printf 通过但 GPIO 翻转频率超差 → 强制 TIMING_FAIL
        verification_result = {
            "status": "fail",
            "all_expected_found": False,
            "matched": [],
            "missing": ["physical timing gate"],
            "description": physical.get("error", "GPIO toggle frequency out of tolerance"),
            "needs_ai_judgement": True,
        }
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
        # F-148 ③: record 命名捕获组的提取值 — 顶层 records 数组
        # ([{id, 组名: 值}, ...] 平铺; 行级明细在 steps.verify.results[*].records)
        result["records"] = ev["records"]
        # capture 空兜底 (与 legacy 同款归因; 文案按后端分流 F-188/N-3)
        if capture_empty and flash_ran:
            verification_result["description"] = (
                _empty_capture_note(config)
                + verification_result.get("description", "")
            )
    else:
        # 正则断言: 配置键 verify.expect_patterns (缺省空) + CLI --require-tgl 注入
        expect_patterns = list(verify_cfg.get("expect_patterns", []) or [])
        if getattr(args, "require_tgl", False):
            expect_patterns.append(r"TGL \d+")
        verification_result = verify(captured_text, expect, description,
                                     expect_patterns=expect_patterns or None)
        # capture 空兜底: 确实烧录过但无输出 → 归因文案按后端分流 (F-188/N-3)
        if capture_empty and flash_ran:
            verification_result["description"] = (
                _empty_capture_note(config)
                + verification_result.get("description", "")
            )
    result["steps"]["verify"] = verification_result

    # ---- Final result ----
    result["captured_output"] = _sanitize_text(captured_text)
    if has_hardfault:
        result["status"] = "hardfault"
    elif physical.get("status") == "timing_fail":
        # TIMING_FAIL 优先于 verify 的 fail — 时序错误是更严重的失败
        result["status"] = "timing_fail"
        result["error"] = physical.get("error", "Physical gate timing failure")
    elif physical.get("status") in ("probe_error", "insufficient_samples"):
        # 探测失败不谎报 pass/fail — 保持现状验证结论, 但标记探测异常
        result["status"] = verification_result["status"]
        result["physical_gate_error"] = physical.get("error", physical.get("status"))
    else:
        result["status"] = verification_result["status"]
    result["elapsed_sec"] = round(time.time() - started_ts, 1)



def _finalize_run(args, config, result, lease, max_retries, captured_text):
    """Step 6 + 落账 + 唯一出口 (F-128 evidence/F-147 junit 在 _output 汇聚)。"""

    # ---- Step 6: 判定后硬件自恢复 (F-129, 工单二 A-2) ----
    # flash 实际发生过的运行结束后复位目标——超时/卡死场景留下的挂着断点
    # 或半初始化外设不留给下一次运行 (借鉴 agentic-hil)。复位失败只记录
    # (post_reset: ok|failed|skipped), 绝不改判 verdict; capture.post_reset:
    # false 显式关闭; --no-flash / flash 未跑成的运行不触发 (无判定即无复位,
    # 早退出口也不复位——OpenOCD 卡死场景下复位大概率同样卡死)。
    flash_ok = result.get("steps", {}).get("flash", {}).get("status") == "ok"
    if _esp_backend_mode(config):
        # F-174/I-1: ESP 目标复位归 capture 起点 (esptool --after hard_reset),
        # 判定后 OpenOCD 复位对 ESP 既无意义又占 ST-Link——09-16 双 PASS
        # 碰巧无害只因 ST-Link 失联, 同机插着 STM32 时就是跨设备副作用。
        result["post_reset"] = "skipped"
    elif flash_ok and (config.get("capture", {}) or {}).get("post_reset", True):
        rs = reset_target(_openocd_exe())
        result["post_reset"] = "ok" if rs.get("status") == "ok" else "failed"
        if rs.get("status") != "ok":
            print(f"[warn] 判定后复位失败 (不影响 verdict): {rs.get('message', '')}",
                  file=sys.stderr)
    else:
        result["post_reset"] = "skipped"

    # F-131: flash+capture 段结束 (含 post_reset 的 OpenOCD 复用) — 释放租约
    _release_hw_lease(lease)

    # 验证失败 (fail/timing_fail) 时保存失败现场供 Agent 分析
    if result["status"] in ("fail", "timing_fail"):
        _save_failure_context(result, max_retries, capture_text=captured_text, workspace=WORKSPACE)

    # 注入点 ③: 自动记录反馈事件（异步，失败不影响主流程结论，但必须留痕 — F-004）。
    # --gate-run 跳过: 门禁重跑/豁免运行不得污染校准统计 (spec 2026-08-26 §5)
    result["feedback"] = _log_feedback_event(
        result, getattr(args, "gate_run", False))

    # F-047: 进度台账 — 双写 checkpoints.jsonl + state.json last_checkpoint
    #   step_keys/step_durations 收集实际跑过的步骤, 给后续审计
    #   "那次跑过哪些步/每步多久" (F-085: 正常出口补传 step_durations 与
    #   gate_run — 与早退路径共用 _step_durations_from 组装, 修复前漏传
    #   导致门禁重跑污染台账、时长画像只收失败样本)
    #   contract_hashes 复用已有契约哈希, 把"判绿锚点"和"进度台账"绑一起
    step_keys, step_durations = _step_durations_from(result)
    record_checkpoint(
        workspace=WORKSPACE,
        status=result.get("status", "unknown"),
        duration_sec=result.get("elapsed_sec", 0.0),
        origin=getattr(args, "task_origin", "manual"),
        step_keys=step_keys,
        contract_hashes=result.get("contract_hashes") or {},
        step_durations=step_durations,
        gate_run=getattr(args, "gate_run", False),
    )

    _output(result, args.json)
    # 退出码契约: ok=0, 其余(fail/timing_fail/hardfault 等)=1;
    # F-147: junit 报告写失败 → 拉低为 1 (CI 必须知道报告没落盘)
    failed = (result.get("status") != "ok"
              or bool(result.get("junit_xml_error")))
    sys.exit(1 if failed else 0)





def _log_feedback_event(result: dict, gate_run: bool) -> dict:
    """注入点 ③: 反馈落账 — 失败不影响主流程结论, 但必须留痕 (F-004)。

    落账跳过/失败曾是无痕审计盲区: button-toggle 工程 feedback 目录缺失,
    校准数据静默断流数周无人知 (F-001 的放大器)。返回的 feedback 状态字典
    随主流程 JSON 出档, 消费方可据此区分 落账成功/门禁跳过/落账失败。"""
    state = {"logged": False}
    if gate_run:
        state["skipped"] = True
        state["reason"] = "gate_run 不落校准库 (spec 2026-08-26 §5)"
        return state
    has_hardfault = result.get("status") == "hardfault"
    verify_ok = result.get("status") == "ok"
    event = {
        "pipeline": "hardfault" if has_hardfault else "build_fix",
        "error_code": result.get("steps", {}).get("analyze", {}).get("errors", None),
        "fault_type": result.get("steps", {}).get("hardfault", {}).get("fault_type"),
        "build_result": _build_result_str(result),
        "verify_result": "pass" if verify_ok else "fail",
        "outcome": "fixed" if verify_ok and not has_hardfault else "still_broken",
    }
    try:
        proc = subprocess.run(
            [sys.executable, FEEDBACK_DB, "--log", json.dumps(event)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, cwd=WORKSPACE)
        if proc.returncode == 0:
            state["logged"] = True
            try:
                state["event_id"] = json.loads(proc.stdout).get("event_id", "")
            except json.JSONDecodeError:
                pass
        else:
            state["error"] = ((proc.stderr or "") + (proc.stdout or "")).strip()[-200:]
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
    return state


def _build_result_str(result: dict) -> str:
    """从 result 中提取构建结果字符串"""
    build_s = result.get("steps", {}).get("build", {})
    if build_s.get("status") == "skipped":
        return "skipped"
    errors = build_s.get("errors", "?")
    warnings = build_s.get("warnings", "?")
    return f"{errors}e{warnings}w"


def _sanitize_text(text: str) -> str:
    """过滤控制字符和无效 Unicode，避免 JSON 编码错误"""
    return ''.join(c for c in text if c.isprintable() or c in '\n\r\t')


# ── 证据分级 (F-128 A-1; F-146 T2 retro-fit 对齐 AEL 命名) ─────────────────
# 借鉴 agentic-embedded-lab 的 claim + fidelity 概念: "仿真通过永不升级为
# 硬件等价声明"。顶层 evidence 字段让消费方机检区分证据等级; 发布门禁
# (release.py G2) 与事后审计 (release_audit.py R8) 据此拒绝非真机证据入档。
# F-146 迁移 (一次性切换, 不留别名, 仓内无外部消费方):
#   real-hardware → hardware_validated, simulator → simulation_validated;
#   第四档 production_approved 不由 verify 产出 — 是 release_audit --approve
#   在发布后对 hardware_validated 记录的人工批准回填 (见 release_audit)。
EVIDENCE_REAL = "hardware_validated"    # capture 后端 rtt/semihosting/uart 实跑
EVIDENCE_SIM = "simulation_validated"   # sim 后端 (仿真器加载执行, 无真机在场)
EVIDENCE_STATIC = "static"              # 仅构建/lint, 或 capture 未跑成 — 无运行时证据
EVIDENCE_LEVELS = (EVIDENCE_STATIC, EVIDENCE_SIM, EVIDENCE_REAL,
                   "production_approved")
_METHOD_EVIDENCE = {
    "rtt": EVIDENCE_REAL,
    "semihosting": EVIDENCE_REAL,
    # F-178 (WB-20260920-04, H-4): F-174 三后端合入时漏同步本表 ——
    # esp_runtime.py 的 uart 采集是真机后端 (pyserial 定时窗 + 复位),
    # 缺键会让 ESP32 全绿 run 落 evidence=static, G2 证据门拒收发版。
    "uart": EVIDENCE_REAL,
    "sim": EVIDENCE_SIM,   # C-1 capture_sim.py 落地即生效, 本表无需再改
}


def _evidence_level(result: dict) -> str:
    """从 result.steps.capture 推导本次运行的证据等级 (三档)。

    判据 = capture 步骤实际使用的后端; capture 未跑成 (build/flash 失败
    早退、capture_failed) 一律 static — 没采到运行时输出就是静态证据,
    不给"差一点就是真机"的模糊地带。判定 verdict 与证据等级正交:
    FAIL 也是真机证据, PASS 也可能是静态证据。"""
    cap = (result.get("steps") or {}).get("capture") or {}
    if cap.get("status") == "ok":
        return _METHOD_EVIDENCE.get(cap.get("method"), EVIDENCE_STATIC)
    return EVIDENCE_STATIC


def _output(result: dict, as_json: bool):
    # F-128: evidence 统一在唯一出口落字段 — main() 的失败早退 (build/
    # flash/capture 失败) 也汇到这里, 消费方无需对任何 status 特判缺键
    result["evidence"] = _evidence_level(result)
    # F-147: JUnit 报告旁路 — 写失败不炸主流程, 记 junit_xml_error 拉低退出码
    if _JUNIT_OUT:
        jr = junit_xml.write_junit_report(result, _JUNIT_OUT, workspace=WORKSPACE)
        if not jr.get("ok"):
            result["junit_xml_error"] = jr.get("error", "junit write failed")
    if as_json:
        # Force UTF-8 stdout for JSON output (Windows console uses GBK by default)
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 人类可读输出
        steps = result.get("steps", {})
        print("=" * 60)
        print("  闭环验证报告")
        print("=" * 60)

        # F-216: 内部错误 (信封兜住的未捕获异常) 没有 steps 结构, 逐段打 "?"
        # 会让人误读成"各步骤状态未知", 而非"这里炸了"。单独呈现。
        if result.get("error_type"):
            print("\n  内部错误 (未经预期路径的异常已被信封捕获):")
            print(f"    类型: {result['error_type']}")
            print(f"    信息: {result.get('error', '?')}")
            # F-217 M-1: 现场没落盘时不得照着不存在的路径说"现场在…"
            if result.get("failure_context_path"):
                print(f"    现场: {result['failure_context_path']}"
                      f"{' (含完整 traceback)' if result.get('traceback') else ''}")
            else:
                print(f"    现场: 写入失败 (期望路径 "
                      f"{result.get('failure_context_expected_path', '?')})"
                      f" —— 下方 traceback 是唯一现场")
            print("\n  这是工具链缺陷或配置问题, 不是被测工程的问题。")
            tb = result.get("traceback")
            if tb:
                print("\n--- traceback ---")
                print(tb.rstrip())
            print("\n" + "=" * 60)
            print("  Verdict: INTERNAL ERROR")
            print("=" * 60)
            return

        build_s = steps.get("build", {})
        print(f"\n[1] Build:    {build_s.get('status', '?').upper()}"
              f"  errors={build_s.get('errors','?')}  warnings={build_s.get('warnings','?')}")

        analyze_s = steps.get("analyze", {})
        if analyze_s.get("status") != "skipped":
            print(f"[2] Analyze:  {analyze_s.get('status', '?').upper()}"
                  f"  matched={analyze_s.get('matched','?')}/{analyze_s.get('matched',0)+analyze_s.get('unmatched',0)}")

        flash_s = steps.get("flash", {})
        print(f"[3] Flash:    {flash_s.get('status', '?').upper()}")

        capture_s = steps.get("capture", {})
        print(f"[4] Capture:  {capture_s.get('status', '?').upper()}"
              f"  lines={capture_s.get('lines','?')}  method={capture_s.get('method','?')}")

        pg_s = steps.get("physical_gate", {})
        if pg_s.get("status") != "skipped":
            pg_info = (f"  measured={pg_s.get('measured_toggles_per_sec','?')} toggles/s"
                       f" (expected {pg_s.get('expected_toggles_per_sec','?')}"
                       f" ±{pg_s.get('tolerance',0)*100:.0f}%)")
            print(f"[4c] Physical: {pg_s.get('status','?').upper()}{pg_info}")

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

        captured = result.get("captured_output", "")
        if captured:
            print(f"\n--- Captured Output ({len(captured)} chars) ---")
            print(captured[:500])
            if len(captured) > 500:
                print(f"... ({len(captured) - 500} more chars)")

        print(f"\n{'=' * 60}")
        verdict = "PASS" if result["status"] == "ok" else "FAIL"
        print(f"  Verdict: {verdict}")
        print(f"  Elapsed: {result.get('elapsed_sec', '?')}s")
        print("=" * 60)


if __name__ == "__main__":
    main()
