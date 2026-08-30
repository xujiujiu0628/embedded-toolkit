#!/usr/bin/env python3
"""
HardFault 自动诊断器 — 通过 OpenOCD 读取故障寄存器并解析为可读报告

用法:
    python hardfault.py                          # 自动诊断当前连接的设备
    python hardfault.py --json                   # JSON 输出
    python hardfault.py --map path/to/firmware.map  # 指定 map 文件路径

工作原理:
    1. OpenOCD init → halt → 读取所有寄存器 + SCB 故障寄存器
    2. 解码 CFSR/HFSR 位域, 识别 Fault 类型
    3. 解析 .map 符号表, 将 PC/LR/BFAR 解析为函数名
    4. 生成结构化诊断报告, 由 Claude AI 做最终判断
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone

from wb_common import find_project_root, load_machine


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)
# 机器路径只允许存在于 machine.json (与 verify.py 同模式)
OPENOCD_EXE = load_machine()["openocd_exe"]

# CFSR 位域定义 (Cortex-M3)
CFSR_BITS = {
    # MFSR [7:0] — MemManage Fault Status Register
    "mfsr_iaccviol":   (0, "Instruction access violation (execute from XN region)"),
    "mfsr_daccviol":   (1, "Data access violation (MPU protected)"),
    "mfsr_munsterr":   (3, "MemManage unstacking error"),
    "mfsr_mstkerr":    (4, "MemManage stacking error"),
    "mfsr_mlsp_ok":    (5, "Floating-point lazy state preservation"),
    "mfsr_mmarvalid":  (7, "MMFAR is valid"),
    # BFSR [15:8] — BusFault Status Register
    "bfsr_ibuserr":    (8,  "Instruction bus error (bad code fetch address)"),
    "bfsr_preciserr":  (9,  "Precise data bus error (BFAR has the address)"),
    "bfsr_impreciserr":(10, "Imprecise data bus error (BFAR not valid)"),
    "bfsr_unstkerr":   (11, "BusFault unstacking error"),
    "bfsr_stkerr":     (12, "BusFault stacking error"),
    "bfsr_lsp_ok":     (13, "Floating-point lazy state preservation"),
    "bfsr_bfarvalid":  (15, "BFAR is valid"),
    # UFSR [31:16] — UsageFault Status Register
    "ufsr_undefinstr": (16, "Undefined instruction executed"),
    "ufsr_invstate":   (17, "Invalid state (bad BX target / EPSR.T=0)"),
    "ufsr_invpc":      (18, "Invalid PC loaded (trying to branch to non-instruction)"),
    "ufsr_nocp":       (19, "Coprocessor access (no coprocessor present)"),
    "ufsr_unalgined":  (24, "Unaligned memory access"),
    "ufsr_divbyzero":  (25, "Divide by zero"),
}

# HFSR 位域
HFSR_BITS = {
    "hfsr_vecttbl": (1,  "Vector table read fault (bad VTOR / boot config)"),
    "hfsr_forced":  (30, "FORCED — escalated from MemManage/BusFault/UsageFault"),
    "hfsr_debugevt":(31, "Debug event (BKPT without debugger?)"),
}


def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def run_openocd_diag() -> str:
    """运行 OpenOCD 读取故障寄存器, 返回原始输出文本"""
    cmd = [
        OPENOCD_EXE,
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f1x.cfg",
        "-c", "transport select swd",
        "-c", "init",
        "-c", "halt",
        "-c", "reg pc",
        "-c", "reg lr",
        "-c", "reg sp",
        "-c", "reg xpsr",
        "-c", "reg msp",
        "-c", "reg r0",
        "-c", "reg r1",
        "-c", "reg r2",
        "-c", "reg r3",
        "-c", "mdw 0xE000ED28 1",   # CFSR
        "-c", "mdw 0xE000ED2C 1",   # HFSR
        "-c", "mdw 0xE000ED38 1",   # BFAR
        "-c", "mdw 0xE000ED34 1",   # MMFAR
        "-c", "shutdown",
    ]

    # ST-Link 释放竞态: verify.py capture 会话刚退出时 ST-Link 偶发未释放,
    # 首次连接失败时短延迟重试 (与门控 step_physical_gate 对齐: 3 次, 3s 间隔)
    last_out = ""
    for attempt in range(3):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=60, cwd=WORKSPACE
            )
            out = result.stdout + "\n" + result.stderr
        except subprocess.TimeoutExpired:
            out = ""
        except FileNotFoundError:
            return ""
        last_out = out
        # 连接成功判据: SWD 探测到目标 (DPIDR 打印) 且能读到 PC — 连接失败时两者皆无
        if "SWD DPIDR" in out and re.search(r"pc\s*\(/32\):\s*0x", out):
            return out
        if attempt < 2:
            time.sleep(3)
    return last_out


def parse_reg_value(text: str, reg_name: str) -> int | None:
    """从 OpenOCD 'reg <name>' 输出中提取寄存器值
    格式: "pc (/32): 0x0800012a"
    """
    pattern = rf'(?:^|\n)\s*{re.escape(reg_name)}\s*\(/\d+\):\s*(0x[0-9a-fA-F]+)'
    m = re.search(pattern, text)
    if m:
        return int(m.group(1), 16)
    return None


def parse_mdw_value(text: str, target_addr: int) -> int | None:
    """从 OpenOCD 'mdw <addr> 1' 输出中提取读取的值
    格式: "0xe000ed28: 00000000"
    """
    pattern = rf'{target_addr:#010x}:\s*([0-9a-fA-F]+)'
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return int(m.group(1), 16)
    return None


def parse_registers(raw_output: str) -> dict:
    """解析 OpenOCD 输出中的所有寄存器和故障寄存器"""
    regs = {}
    for name in ["pc", "lr", "sp", "xpsr", "msp", "psp", "r0", "r1", "r2", "r3"]:
        val = parse_reg_value(raw_output, name)
        if val is not None:
            regs[name] = val

    # 解析 mdw 输出中的故障寄存器
    mdw_map = {
        "cfsr":  0xE000ED28,
        "hfsr":  0xE000ED2C,
        "bfar":  0xE000ED38,
        "mmfar": 0xE000ED34,
    }
    for name, addr in mdw_map.items():
        val = parse_mdw_value(raw_output, addr)
        if val is not None:
            regs[name] = val

    return regs


def decode_bits(value: int, bit_defs: dict) -> dict:
    """解码位域, 返回 actived_bits 字典"""
    result = {}
    for bit_name, (bit_pos, description) in bit_defs.items():
        if value & (1 << bit_pos):
            result[bit_name] = description
    return result


def classify_fault(regs: dict) -> dict:
    """根据寄存器值分类 Fault 类型"""
    cfsr = regs.get("cfsr", 0)
    hfsr = regs.get("hfsr", 0)

    cfsr_bits = decode_bits(cfsr, CFSR_BITS)
    hfsr_bits = decode_bits(hfsr, HFSR_BITS)

    # 判断主因
    primary = "unknown"
    if hfsr & (1 << 30):  # FORCED
        # 查看哪个子 fault 升级上来的
        bfsr = (cfsr >> 8) & 0xFF
        ufsr = (cfsr >> 16) & 0xFFFF
        mfsr = cfsr & 0xFF
        if bfsr:
            primary = "BusFault"
            if bfsr & (1 << 1): primary += " (PRECISERR)"
            elif bfsr & (1 << 2): primary += " (IMPRECISERR)"
            elif bfsr & (1 << 0): primary += " (IBUSERR)"
        elif ufsr:
            primary = "UsageFault"
            if ufsr & (1 << 0): primary += " (UNDEFINSTR)"
            elif ufsr & (1 << 1): primary += " (INVSTATE)"
            elif ufsr & (1 << 8): primary += " (UNALIGNED)"
            elif ufsr & (1 << 9): primary += " (DIVBYZERO)"
        elif mfsr:
            primary = "MemManage"
            if mfsr & (1 << 0): primary += " (IACCVIOL)"
            elif mfsr & (1 << 1): primary += " (DACCVIOL)"
    elif hfsr & (1 << 31):
        primary = "DebugEvent (BKPT without debugger?)"
    elif hfsr & (1 << 1):
        primary = "VectorTable (bad VTOR/boot config)"
    elif cfsr == 0 and hfsr == 0:
        # 无任何 SCB 故障位 — CPU 暂停状态但非 HardFault (可能是程序卡死或
        # 正常运行中被调试器暂停)。修复 2026-08-12: 旧值 "Direct HardFault"
        # 导致 verify.py capture 空时误报并污染反馈库; verify.py 据此归因为 no_fault
        primary = "no_fault"
    else:
        primary = f"HardFault (HFSR=0x{hfsr:08X}, CFSR=0x{cfsr:08X})"

    return {
        "primary": primary,
        "cfsr_bits": cfsr_bits,
        "hfsr_bits": hfsr_bits,
        "cfsr_raw": cfsr,
        "hfsr_raw": hfsr,
    }


def _map_degradation_note(map_path: str, symbols: list) -> str | None:
    """符号表为空时给出降级告警 (换回复核 F-005 遗留半项: 自动发现失败后
    兜底路径仍可能指向不存在的 map, 静默降级不可接受)。无降级返回 None。"""
    if symbols:
        return None
    why = "文件不存在" if not os.path.exists(map_path) else "无全局符号"
    return ("符号表为空 (%s: %s) — 地址解析已降级, 诊断仅寄存器级可信 "
            "(F-005)" % (map_path, why))


def parse_map_symbols(map_path: str) -> list[dict]:
    """解析 .map 文件的全局符号表, 返回 [{name, addr, size, type}, ...]"""
    symbols = []
    if not os.path.exists(map_path):
        return symbols

    with open(map_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    in_global = False
    for line in lines:
        if "Global Symbols" in line:
            in_global = True
            continue
        if not in_global:
            continue
        # 符号条目格式:
        #   symbol_name    Value     Ov Type        Size  Object(Section)
        # 例:
        #   main           0x08000309   Thumb Code   120  main.o(.text)
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("===") or stripped.startswith("---"):
            continue
        # 匹配模式: 名字 (多单词?) + 十六进制值 + 类型 + 大小 + 对象
        m = re.match(
            r'^(.+?)\s+(0x[0-9a-fA-F]+)\s+(.*?)\s+(\d+)\s+(.+\.o\(.+\))$',
            stripped
        )
        if not m:
            continue
        name = m.group(1).strip()
        addr = int(m.group(2), 16)
        typestr = m.group(3).strip()
        size = int(m.group(4))
        obj = m.group(5).strip()
        symbols.append({
            "name": name,
            "addr": addr,
            "type": typestr,
            "size": size,
            "object": obj,
        })
    return symbols


def resolve_address(addr: int, symbols: list[dict]) -> dict | None:
    """将地址解析为最近的符号名（地址在符号范围内）"""
    best = None
    best_size = 0
    for sym in symbols:
        if sym["addr"] <= addr < sym["addr"] + sym["size"]:
            if sym["size"] > best_size:  # 优先匹配小函数（更精确）
                best = sym
                best_size = sym["size"]
    if best:
        offset = addr - best["addr"]
        return {"name": best["name"], "offset": offset, "size": best["size"]}
    return None


def classify_address_range(addr: int) -> str:
    """分类地址范围"""
    if 0x08000000 <= addr < 0x08010000:
        return "Flash (code/const)"
    if 0x20000000 <= addr < 0x20005000:
        return "SRAM (data/stack)"
    if 0x40000000 <= addr < 0x50000000:
        return "Peripheral bus (APB/AHB)"
    if 0xE0000000 <= addr < 0xE0100000:
        return "Cortex-M3 private (SCB/NVIC/SysTick)"
    if addr < 0x1000:
        return "Low memory (null pointer?)"
    return "Unknown"


def diagnose(regs: dict, symbols: list[dict]) -> str:
    """根据寄存器值和符号表生成自然语言诊断"""
    parts = []
    fault = classify_fault(regs)

    parts.append(f"Fault type: {fault['primary']}")

    # BFAR 分析
    bfar = regs.get("bfar", 0)
    if bfar and bfar != 0xFFFFFFFF:
        bfar_range = classify_address_range(bfar)
        bfar_sym = resolve_address(bfar, symbols)
        parts.append(f"BFAR=0x{bfar:08X} ({bfar_range})")
        if bfar_sym:
            parts.append(f"  → in or near '{bfar_sym['name']}' +{bfar_sym['offset']}")

    # MMFAR 分析
    mmfar = regs.get("mmfar", 0)
    if mmfar and mmfar != 0xFFFFFFFF:
        mmfar_range = classify_address_range(mmfar)
        mmfar_sym = resolve_address(mmfar, symbols)
        parts.append(f"MMFAR=0x{mmfar:08X} ({mmfar_range})")
        if mmfar_sym:
            parts.append(f"  → in or near '{mmfar_sym['name']}' +{mmfar_sym['offset']}")

    # PC 分析
    pc = regs.get("pc", 0)
    if pc:
        pc_sym = resolve_address(pc, symbols)
        if pc_sym:
            parts.append(f"PC=0x{pc:08X} → {pc_sym['name']}+{pc_sym['offset']}")
        else:
            parts.append(f"PC=0x{pc:08X} (no matching symbol)")

    # LR 分析
    lr = regs.get("lr", 0)
    if lr:
        # LR 在异常返回时有一个特殊值 EXC_RETURN
        if lr >= 0xFFFFFFF0:
            exc_return = ["Handler→Handler (MSP)", "Thread→Handler (MSP)",
                          "Handler→Thread (MSP)", "Thread→Thread (PSP)"]
            idx = lr & 0xF
            desc = exc_return[idx] if idx < len(exc_return) else "unknown"
            parts.append(f"LR=0x{lr:08X} (EXC_RETURN: {desc})")
        else:
            lr_sym = resolve_address(lr, symbols)
            if lr_sym:
                parts.append(f"LR=0x{lr:08X} → {lr_sym['name']}+{lr_sym['offset']}")
            else:
                parts.append(f"LR=0x{lr:08X}")

    # 激活的故障位
    for bits in [fault["cfsr_bits"], fault["hfsr_bits"]]:
        for name, desc in bits.items():
            parts.append(f"  [{name}] {desc}")

    return "\n".join(parts)


def _default_map_path() -> str:
    """默认 .map: 从 cwd 向上发现工程根, 取 lst/ 下第一个 .map。

    F-005: 旧默认 <toolkit 仓根>/lst/blink.map 是 blink 退役残留 —
    路径恒不存在 → 符号解析恒空, 诊断静默降级无告警。verify.py 子进程
    调用时 cwd=工程根, 手工运行在工程目录内同样可发现。"""
    root = find_project_root(os.getcwd())
    if root:
        lst = os.path.join(root, "lst")
        if os.path.isdir(lst):
            maps = sorted(glob.glob(os.path.join(lst, "*.map")))
            if maps:
                return maps[0]
    return os.path.join(WORKSPACE, "lst", "blink.map")


def main():
    parser = argparse.ArgumentParser(description="HardFault 自动诊断器")
    parser.add_argument("--map", default=None,
                        help=".map 文件路径 (默认: cwd 向上发现工程 lst/*.map, F-005)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--raw", action="store_true", help="输出 OpenOCD 原始输出")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()

    # 1. 运行 OpenOCD 读取寄存器
    raw = run_openocd_diag()
    if not raw:
        result = {
            "status": "error",
            "error": "OpenOCD failed to connect. Is ST-Link plugged in?",
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["error"])
        sys.exit(1)

    if args.raw:
        print(raw)
        return

    # 2. 解析寄存器
    regs = parse_registers(raw)

    # 3. 检查是否真的发生了 HardFault
    if regs.get("pc") == 0 or regs.get("msp") == 0:
        regs["_note"] = "Target may not be in HardFault — PC/MSP is zero"

    # 4. 解析符号表
    map_path = args.map or _default_map_path()
    symbols = parse_map_symbols(map_path)
    note = _map_degradation_note(map_path, symbols)
    if note:
        print("WARNING: " + note, file=sys.stderr)

    # 5. 分类 Fault 类型
    fault = classify_fault(regs)

    # 6. 生成诊断
    diagnosis_text = diagnose(regs, symbols)

    # 7. 解析地址
    resolved = {}
    pc = regs.get("pc", 0)
    lr = regs.get("lr", 0)
    bfar = regs.get("bfar", 0)
    mmfar = regs.get("mmfar", 0)

    if pc > 0x08000000:
        pc_sym = resolve_address(pc, symbols)
        if pc_sym:
            resolved["pc"] = f"{pc_sym['name']}+{pc_sym['offset']}"
    if lr > 0x08000000:
        lr_sym = resolve_address(lr, symbols)
        if lr_sym:
            resolved["lr"] = f"{lr_sym['name']}+{lr_sym['offset']}"
    if bfar and bfar < 0xFFFFFFFF:
        resolved["bfar"] = classify_address_range(bfar)
        bfar_sym = resolve_address(bfar, symbols)
        if bfar_sym:
            resolved["bfar"] += f" ({bfar_sym['name']}+{bfar_sym['offset']})"
    if mmfar and mmfar < 0xFFFFFFFF:
        resolved["mmfar"] = classify_address_range(mmfar)

    result = {
        "status": "hardfault_detected",
        "fault_type": fault["primary"],
        "registers": {k: f"0x{v:08X}" if isinstance(v, int) else v
                       for k, v in regs.items() if not k.startswith("_")},
        "fault_registers": {
            "cfsr": {"raw": f"0x{regs.get('cfsr',0):08X}", "bits": fault["cfsr_bits"]},
            "hfsr": {"raw": f"0x{regs.get('hfsr',0):08X}", "bits": fault["hfsr_bits"]},
            "bfar": f"0x{regs.get('bfar',0):08X}" if regs.get("bfar") else "N/A",
            "mmfar": f"0x{regs.get('mmfar',0):08X}" if regs.get("mmfar") else "N/A",
        },
        "resolved": resolved,
        "diagnosis": diagnosis_text,
        "symbols_total": len(symbols),
        "needs_ai_judgement": True,
        "_meta": {
            "map_file": map_path,
            "timestamp": started_at,
            "elapsed_sec": round(time.time() - started_ts, 1),
        },
    }

    if regs.get("_note"):
        result["_note"] = regs["_note"]

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_readable(result)


def _print_readable(r: dict):
    print("=" * 60)
    print("  HardFault 诊断报告")
    print("=" * 60)
    print(f"\nFault Type: {r['fault_type']}")
    print(f"\nRegisters:")
    for name, val in r["registers"].items():
        print(f"  {name:>5}: {val}")
    print(f"\nFault Registers:")
    fr = r["fault_registers"]
    print(f"  CFSR:  {fr['cfsr']['raw']}  ({len(fr['cfsr']['bits'])} bits active)")
    print(f"  HFSR:  {fr['hfsr']['raw']}  ({len(fr['hfsr']['bits'])} bits active)")
    print(f"  BFAR:  {fr['bfar']}")
    print(f"  MMFAR: {fr['mmfar']}")
    if r["resolved"]:
        print(f"\nResolved:")
        for k, v in r["resolved"].items():
            print(f"  {k}: {v}")
    print(f"\nDiagnosis:\n  {r['diagnosis']}")
    print(f"\nSymbols loaded: {r['symbols_total']}")
    if r.get("_note"):
        print(f"\nNote: {r['_note']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
