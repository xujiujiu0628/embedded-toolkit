r"""失败现场上下文 (F-060) — verify.py 拆分件（防腐方案 §3.3 步骤 5c）.

last_failure.json 的生成（agent_hint 分流派发）、semihosting 正文行过滤口径
（F-003: 正常结束与超时收尸共用一套）、采集窗优先级（F-016）。

自 verify.py 整体搬迁，差异三点（记账）：WORKSPACE 全局改 workspace 参数；
TOOLKIT_ROOT 自 wb_common 导入（agent_hint 的 hardfault.py 指引随其推导，
test_failure_hints 钉改指本模块）；ts 由 runtime_common.now_iso 规范版生成
（同 F-059 记账——时刻不变）。_finish_capture_timeout 留守 verify（含
sys.exit 与 _output 的派发胶水），经再导出面调用本模块。
"""
import json
import os
import re

from runtime_common import now_iso
from wb_common import TOOLKIT_ROOT


_LOG_PREFIX_RE = re.compile(r'^(Info|Warn|Error|Debug)\s*:', re.IGNORECASE)

# F-106: 黑名单曾按"子串包含"整行删——固件正文含 "GDB"/"http://"/"dropped"
# 等词即被误滤 (semihosting 输出是裸文本, 与 OpenOCD log 同流)。收窄为
# **行首锚定的 OpenOCD 已知噪声形态** (实测串照抄自本仓测试与实机日志):
# OpenOCD 自身状态行几乎总在行首, 正文里的同名词不再误伤。
# 注: "Info :"/"Warn :" 裸串兜底已由 _LOG_PREFIX_RE (容忍空格) 覆盖, 删除。
# F-170 裁决: 固件正文行首恰撞下列锚定词 = 可预期误滤(概率≈0, 正文是 printf
# 风格行), 未来真出现按新事故立项, 不预支修复。
_CAPTURE_NOISE_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r'^Listening on port\b',
    r'^target halted due to\b',
    r'^shutdown command invoked\b',
    r'^target state:\s',
    r'^semihosting is enabled\b',
    r'^\s*(?:\w+\s+)?GDB\b.*(?:server|socket|connection)\b',  # "X GDB server" 类启动行
    r'^\s*accepting .*connection\b',
    r'^\s*dropped .*connection\b',
    r'^DEPRECATED\b',
    r'^Licensed under GNU\b',
    r'^For bug reports\b',
    r'^\s*xPSR:',
    r'^https?://openocd\b',
    r'^\s*(?:OpenOCD|xPack)\b',
))


def _filter_capture_lines(raw: str) -> list:
    """从 OpenOCD stdout+stderr 提取 semihosting 正文行。

    OpenOCD 的 log 行以 "Info:/Warn:/Error:/Debug:" 开头, semihosting 输出是
    裸文本行; 正常结束与超时收尸两条路径必须共用同一套过滤口径 (F-003)。
    F-106: 第二层过滤从子串黑名单收窄为行首锚定正则——正文含噪声词不再
    被整行误删。"""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _LOG_PREFIX_RE.match(stripped):
            continue
        if any(rx.match(stripped) for rx in _CAPTURE_NOISE_RES):
            continue
        lines.append(stripped)
    return lines


def resolve_capture_timeout(cli_timeout, capture_cfg: dict | None) -> int:
    """F-016: 采集窗优先级 CLI --timeout > 契约 capture.duration_sec > 默认 10。

    真人按键类期望 (如 FR-KEY-01) 10s 硬窗几乎必错过——2026-08-30 插板终判
    三轮空采实锤; 窗口长度属工程契约, 应可写进 config.json 而非每次背 CLI。"""
    if cli_timeout is not None:
        return cli_timeout
    d = (capture_cfg or {}).get("duration_sec")
    if isinstance(d, int) and not isinstance(d, bool) and d > 0:
        return d
    return 10


def _save_failure_context(result: dict, max_retries: int, capture_text: str = "",
                          workspace=None):
    """Save structured failure context for Agent analysis.

    Written to .workbench/build/last_failure.json so that
    Claude Code agents can read and analyze the failure before
    retrying with code fixes.

    capture_text: 完整 semihosting 输出原文落盘 (人类可读输出被截断到 500 字符,
    --json 才有完整文本 — 2026-08-16 TGL 验证教训, 失败现场必须完整可取证)
    """
    failure_path = os.path.join(workspace, ".workbench", "build", "last_failure.json")
    os.makedirs(os.path.dirname(failure_path), exist_ok=True)

    # Extract key diagnostic info
    ctx = {
        "status": result.get("status", "unknown"),
        "error": result.get("error", ""),
        "steps": {},
        "agent_hint": "",
    }
    if capture_text:
        ctx["captured_output"] = capture_text

    build_s = result.get("steps", {}).get("build", {})
    if build_s.get("status") == "build_failed":
        ctx["steps"]["build"] = {
            "attempts": build_s.get("attempts", []),
            "last_errors": build_s.get("errors", "?"),
            "last_warnings": build_s.get("warnings", "?"),
        }
        ctx["agent_hint"] = (
            "Build failed. Check the build log at .workbench/build/ for "
            "compiler errors. Common causes: missing include paths, GCC "
            "diagnostics (enable -Wall; check for C23/extension issues under "
            "-std), undefined symbols, linker script/region overflow. "
            "Run /review:build if errors are unmatched in KB."
        )

    flash_s = result.get("steps", {}).get("flash", {})
    if flash_s.get("status") == "flash_failed":
        ctx["steps"]["flash"] = {
            "attempts": flash_s.get("attempts", []),
        }
        ctx["agent_hint"] = (
            "Flash failed. Check: ST-Link connected? Board powered? "
            "SWD pins (PA13/SWDIO, PA14/SWCLK) not reconfigured as GPIO? "
            f"Try: python {os.path.join(TOOLKIT_ROOT, 'scripts', 'hardfault.py')} "
            "to check connectivity."
        )

    # 采集失败: 写入 capture 步骤现场
    if result.get("status") == "capture_failed":
        ctx["steps"]["capture"] = result.get("steps", {}).get("capture", {})
        ctx["agent_hint"] = (
            "Capture failed. Check: ST-Link connected? OpenOCD target "
            "examine succeeded? Run: python "
            f"{os.path.join(TOOLKIT_ROOT, 'scripts', 'hardfault.py')} "
            "to check SWD connectivity, then retry."
        )

    # 验证失败 (含 TIMING_FAIL): 写入 capture + verify + physical_gate 现场
    if result.get("status") in ("fail", "timing_fail"):
        steps = result.get("steps", {})
        ctx["steps"]["capture"] = steps.get("capture", {})
        ctx["steps"]["verify"] = steps.get("verify", {})
        if steps.get("physical_gate", {}).get("status") not in (None, "skipped"):
            ctx["steps"]["physical_gate"] = steps["physical_gate"]
        if result["status"] == "timing_fail":
            ctx["agent_hint"] = (
                "printf output matched but GPIO toggle frequency deviated "
                "from expected. Check clock tree: HSE 8MHz -> PLL x9 -> 72MHz "
                "(Core/Src/main.c SystemClock_Config). Roll back to Drafter "
                "to adjust clock configuration."
            )
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

    ctx["max_retries"] = max_retries
    ctx["timestamp"] = now_iso()

    try:
        with open(failure_path, 'w', encoding='utf-8') as f:
            json.dump(ctx, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # Non-critical
