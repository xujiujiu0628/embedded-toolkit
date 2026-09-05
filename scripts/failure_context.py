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
_CAPTURE_STATUS_KW = ["Listening on port", "halted due to", "shutdown command",
                      "GDB", "accepting", "dropped", "semihosting is enabled",
                      "target state:", "DEPRECATED",
                      "Licensed under GNU", "For bug reports",
                      "xPSR:", "http://", "Info :", "Warn :", "xPack"]


def _filter_capture_lines(raw: str) -> list:
    """从 OpenOCD stdout+stderr 提取 semihosting 正文行。

    OpenOCD 的 log 行以 "Info:/Warn:/Error:/Debug:" 开头, semihosting 输出是
    裸文本行; 正常结束与超时收尸两条路径必须共用同一套过滤口径 (F-003)。"""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _LOG_PREFIX_RE.match(stripped):
            continue
        if any(kw in stripped for kw in _CAPTURE_STATUS_KW):
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
            "compiler errors. Common causes: missing include paths, ARMCC V5 "
            "C90 incompatibility (no C++ comments, no mixed decl+code), "
            "undefined symbols. Run /review:build if errors are unmatched in KB."
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
