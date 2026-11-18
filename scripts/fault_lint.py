#!/usr/bin/env python3
"""故障路径静态闸（F-251）—— 让「不写错误恢复」在 CI 里红。

起因（2026-11-17）：我只写 happy path。初始化序列写得很顺，掉电、从机不应答、
总线被钳死、超时回退、错误上报这些路径很弱，通常是别人（或真机）先撞出来。
这一层没有机械检查，就永远靠自觉。

三条规则（全部是启发式，宁可少报也不要淹没真问题）：

  R1 UNCHECKED_CALL   通信/外设调用返回值被丢弃:
                      `HAL_I2C_Master_Transmit(...);` —— 地址没 ACK 也照跑。
                      覆盖 I2C/SPI/UART/CAN/ADC/ADCEx（2026-11-18 补 ADC：
                      HAL_ADC_ConfigChannel/Start/Stop/校准的返回值同样会吞错）。
                      已知返回 void 的 HAL 函数与函数定义本身不报。
  R2 UNBOUNDED_WAIT   无界忙等: `while (HAL_I2C_GetFlagStatus(...) == RESET) { }`
                      —— 条件里有调用/寄存器，循环体是空的或只有一句，且条件里
                      没有任何 tick/CNT/超时变量。DWT 有界等、普通遍历循环不报。
  R3 BLOCKING_IN_ISR  ISR 里阻塞: `*_IRQHandler` / `*_Handler` 里出现 HAL_Delay、
                      `while (1)` 或 HAL_MAX_DELAY 的阻塞传输。HardFault 等故障
                      handler 的 `while (1) {}` 是有意的锁死，整类豁免。

另有一条告警规则（--strict 下升级为错误）:

  R4 NO_FAULT_TEST    工程有通信模块，却没有一条故障注入用例。判据是 tests/ 下
                      出现 `fault_shim_` 符号 —— 也就是 templates/fault_injection
                      的接法。

压制: 同一行或上一行写 `/* fault-lint:ignore R1 — 理由 */`。
**理由必填**：没有理由的压制按违规计数（这条闸自己的防腐）。

  python fault_lint.py --project <工程> [--json] [--strict]
退出码: 0 无 error（warning 不算）/ 1 有 error / 2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKIP_DIRS = {"drivers", "thirdparty", "build", ".git", "tests", "docs",
             ".workbench", "managed_components", "node_modules", "__pycache__",
             "legacy", "spikes", "tools",
             # WCH / MounRiver 的厂商树 (2026-11-17 校准: envmon 33 条里 28 条在
             # Peripheral/src 与 Debug/, 是 SDK 自己的寄存器轮询)
             "peripheral", "debug", "startup", "ld", "cmsis"}
SRC_EXT = {".c"}

FAULT_HANDLERS = {"hardfault_handler", "memmanage_handler", "busfault_handler",
                  "usagefault_handler", "nmi_handler", "svc_handler",
                  "pendsv_handler", "default_handler"}

# 返回 void 的 HAL/BSR 类函数: 调用它们不产生可检查的状态
VOID_HAL_PREFIXES = ("HAL_GPIO_WritePin", "HAL_GPIO_TogglePin", "HAL_Delay",
                     "HAL_IncTick", "HAL_NVIC_", "HAL_SYSTICK_", "HAL_DBGMCU_",
                     "HAL_RCC_", "HAL_SuspendTick", "HAL_ResumeTick")
VOID_HAL_EXACT = {"HAL_Init", "HAL_MspInit", "HAL_DeInit"}

COMM_CALL = re.compile(r"\b(HAL_(?:ADCEx|ADC|I2C|SPI|UART|CAN)_[A-Za-z0-9_]+)\s*\(")
TIMEOUT_HINT = re.compile(r"tick|Tick|CNT|cnt|timeout|Timeout|deadline|Deadline|"
                          r"millis|Millis|elapsed|Elapsed|Timer|timer|SysTick", )
IGNORE = re.compile(r"fault-lint:\s*ignore\s+(R\d)\s*(?:[—:\-–]\s*(\S.*))?")
FUNC_DEF = re.compile(
    r"(?m)^[ \t]*(?:static\s+|inline\s+|__?[A-Za-z0-9_]+\s+)*"
    r"[A-Za-z_][A-Za-z0-9_ \t\*]*\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{")


# ---------------------------------------------------------------- 工具

def strip_comments_and_strings(text: str) -> str:
    """把注释与字符串字面量清成空格（保留换行与长度），避免在它们里面误判。

    只处理 C 的 // 与 /* */、以及 "..." / '...'。不追求完美，够用即可。
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif c == "/" and nxt == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.extend("  ")
            i += 2
        elif c in "\"'":
            quote = c
            out.append(" ")
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    out.append(" ")
                    i += 1
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append(" ")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def match_paren(text: str, open_idx: int):
    """从 '(' 起找配对的 ')'，返回其下标；找不到返回 -1。"""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _suppressed(raw_lines, line_no: int, rule: str):
    """返回 (是否压制, 是否带理由)。看本行与上一行。"""
    for ln in (line_no, line_no - 1):
        if 1 <= ln <= len(raw_lines):
            m = IGNORE.search(raw_lines[ln - 1])
            if m and m.group(1) == rule:
                return True, bool(m.group(2) and m.group(2).strip())
    return False, False


def function_ranges(clean: str):
    """[(name, brace_idx, end_idx)] —— 粗略的顶层函数体定位（不做完整 C 解析）。"""
    out = []
    for m in FUNC_DEF.finditer(clean):
        name = m.group(1)
        brace = clean.find("{", m.end() - 1)
        if brace < 0:
            continue
        depth, end = 0, -1
        for i in range(brace, len(clean)):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > brace:
            out.append((name, brace, end))
    return out


def enclosing_function(ranges, idx: int):
    """包含 idx 的最内层函数名（没有则 None）。"""
    best = None
    for name, brace, end in ranges:
        if brace < idx <= end and (best is None or brace > best[1]):
            best = (name, brace, end)
    return best[0] if best else None


def is_fault_context(name: str) -> bool:
    """故障/错误上下文里不能用时基 —— 那里的轮询是有意的，整类豁免。"""
    low = (name or "").lower()
    return (low in FAULT_HANDLERS or low.endswith("error_handler")
            or low.startswith("fault"))


# ---------------------------------------------------------------- 规则

def rule_r1(path, clean, raw_lines, findings, suppressed_wo_reason):
    for m in COMM_CALL.finditer(clean):
        name = m.group(1)
        if name in VOID_HAL_EXACT or name.startswith(VOID_HAL_PREFIXES):
            continue
        if re.search(r"_Get[A-Za-z]*$|_GetValue$|_GetState$|_GetFlagStatus$", name):
            continue  # 取值函数: 返回值就是数据, "检查"它没有语义
        open_idx = clean.index("(", m.end() - 1)
        close_idx = match_paren(clean, open_idx)
        if close_idx < 0:
            continue
        before = clean[:m.start()].rstrip()
        after = clean[close_idx + 1:].lstrip()
        # 函数定义: 后面跟 "{"；声明: 前面是 void
        if after.startswith("{") or re.search(r"\bvoid\s*$", before):
            continue
        if after.startswith(";"):
            # 只有整条语句都是这个调用才算丢弃: 赋值右值 / return / 条件 / 强转都不算
            stmt_start = max(clean.rfind(ch, 0, m.start()) for ch in ";{}") + 1
            prefix = clean[stmt_start:m.start()]
            if re.search(r"(?<![=!<>+\-*/])=(?!=)", prefix) or re.search(r"\breturn\b", prefix):
                continue
            line_no = line_of(clean, m.start())
            hit = _suppressed(raw_lines, line_no, "R1")
            if hit[0]:
                if not hit[1]:
                    suppressed_wo_reason.append((path, line_no, "R1"))
                continue
            findings.append({
                "file": path, "line": line_no, "rule": "R1",
                "message": f"{name} 的返回值被丢弃 —— 从机不应答/总线错误在这里被吞掉",
            })


def rule_r2(path, clean, ranges, raw_lines, findings, suppressed_wo_reason):
    for m in re.finditer(r"\bwhile\s*\(", clean):
        if is_fault_context(enclosing_function(ranges, m.start())):
            continue  # 故障上下文不能用时基，轮询是有意的
        open_idx = m.end() - 1
        close_idx = match_paren(clean, open_idx)
        if close_idx < 0:
            continue
        cond = clean[open_idx + 1:close_idx]
        if TIMEOUT_HINT.search(cond):
            continue
        # 条件里得有调用或寄存器读，才像"等某个状态"
        if not (re.search(r"[A-Za-z_]+\s*\(", cond) or re.search(r"\b[A-Z][A-Z0-9_]{2,}\b", cond)):
            continue
        rest = clean[close_idx + 1:]
        body = rest.lstrip()
        if body.startswith("{"):
            depth, end = 0, -1
            for i, ch in enumerate(body):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            body = body[:end + 1] if end >= 0 else body
        else:
            semi = body.find(";")
            body = body[:semi + 1] if semi >= 0 else body
        # 只认"空转": 去掉 __NOP()/__WFI() 与空语句后什么都不剩。
        # 有实际工作的循环（遍历/搜索）不是"等"，不报——2026-11-17 校准:
        # Tetris_HardDrop 的 while(!collide(...)) 曾被误报。
        core = re.sub(r"\b__NOP\s*\(\s*\)|\b__WFI\s*\(\s*\)|;", " ", body)
        core = re.sub(r"[{}]", " ", core).strip()
        if core:
            continue
        line_no = line_of(clean, m.start())
        hit = _suppressed(raw_lines, line_no, "R2")
        if hit[0]:
            if not hit[1]:
                suppressed_wo_reason.append((path, line_no, "R2"))
            continue
        findings.append({
            "file": path, "line": line_no, "rule": "R2",
            "message": "无界忙等 —— 条件里没有 tick/CNT/超时变量，从机挂死时这里不会退出",
        })


def rule_r3(path, clean, ranges, raw_lines, findings, suppressed_wo_reason):
    for name, brace, end in ranges:
        low = name.lower()
        if not (low.endswith("_irqhandler") or low.endswith("_handler")):
            continue
        if is_fault_context(name):
            continue  # 故障/错误 handler 的 while(1) 是有意锁死
        body = clean[brace + 1:end]
        hit = None
        for pattern, label in ((r"\bHAL_Delay\s*\(", "HAL_Delay"),
                               (r"\bwhile\s*\(\s*1\s*\)", "while(1)"),
                               (r"\bHAL_MAX_DELAY\b", "HAL_MAX_DELAY")):
            m2 = re.search(pattern, body)
            if m2:
                hit = (label, brace + 1 + m2.start())
                break
        if hit is None:
            continue
        line_no = line_of(clean, hit[1])
        s = _suppressed(raw_lines, line_no, "R3")
        if s[0]:
            if not s[1]:
                suppressed_wo_reason.append((path, line_no, "R3"))
            continue
        findings.append({
            "file": path, "line": line_no, "rule": "R3",
            "message": f"ISR {name} 里有阻塞构造 ({hit[0]}) —— 会拖垮实时性和其它中断",
        })


def rule_r4(project, findings):
    src_files = []
    test_root = os.path.join(project, "tests")
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if fn.lower().endswith((".c",)) and os.path.join(root, fn) != test_root:
                src_files.append(os.path.join(root, fn))
    comm = [p for p in src_files
            if re.search(r"i2c|spi|uart|usart|sensor|mpu|oled|dht|hc05|can", os.path.basename(p).lower())]
    if not comm:
        return
    has_fault_test = False
    if os.path.isdir(test_root):
        for root, _dirs, files in os.walk(test_root):
            for fn in files:
                if not fn.lower().endswith((".c", ".h")):
                    continue
                try:
                    text = open(os.path.join(root, fn), encoding="utf-8",
                                errors="ignore").read()
                except OSError:
                    continue
                if "fault_shim_" in text:
                    has_fault_test = True
                    break
    if not has_fault_test:
        findings.append({
            "file": os.path.relpath(test_root, project).replace("\\", "/"),
            "line": 0, "rule": "R4", "severity": "warning",
            "message": f"检测到 {len(comm)} 个通信模块，但 tests/ 里没有故障注入用例 "
                       f"（接法见 embedded-toolkit/templates/fault_injection）",
        })


# ---------------------------------------------------------------- 驱动

def lint_project(project: str):
    findings, harsh = [], []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in SRC_EXT:
                continue
            if fn.lower().startswith("system_"):
                continue  # CMSIS/WCH 厂商系统文件: 时钟就绪轮询是有意的，改了没法维护
            path = os.path.join(root, fn)
            try:
                raw = open(path, encoding="utf-8", errors="ignore", newline="").read()
            except OSError:
                continue
            rel = os.path.relpath(path, project).replace("\\", "/")
            clean = strip_comments_and_strings(raw)
            raw_lines = raw.splitlines()
            ranges = function_ranges(clean)
            rule_r1(rel, clean, raw_lines, findings, harsh)
            rule_r2(rel, clean, ranges, raw_lines, findings, harsh)
            rule_r3(rel, clean, ranges, raw_lines, findings, harsh)
    rule_r4(project, findings)
    return findings, harsh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="故障路径静态闸 (R1/R2/R3 + R4 告警)")
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="R4 告警也算 error（CI 门禁用）")
    args = ap.parse_args(argv)
    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        print(f"错误: {project} 不是目录", file=sys.stderr)
        return 2

    findings, harsh = lint_project(project)
    errors = [f for f in findings if f.get("severity") != "warning"]
    warnings = [f for f in findings if f.get("severity") == "warning"]

    if args.json:
        print(json.dumps({"project": project, "errors": errors,
                          "warnings": warnings,
                          "suppressed_without_reason": [
                              {"file": f, "line": l, "rule": r} for f, l, r in harsh]},
                         ensure_ascii=False, indent=2))
    else:
        for f in errors + warnings:
            tag = "WARN" if f.get("severity") == "warning" else "ERR "
            loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"{tag} {loc} [{f['rule']}] {f['message']}")
        for f, l, r in harsh:
            print(f"ERR  {f}:{l} [{r}] 压制没写理由 —— 理由必填")
        print(f"\nERROR {len(errors)}  WARN {len(warnings)}  "
              f"（无理由压制 {len(harsh)}）")

    failed = bool(errors) or bool(harsh) or (args.strict and bool(warnings))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
