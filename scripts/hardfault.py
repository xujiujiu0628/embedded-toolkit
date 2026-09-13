#!/usr/bin/env python3
"""
HardFault 自动诊断器 — 通过 OpenOCD 读取故障寄存器并解析为可读报告

用法:
    python hardfault.py                          # 自动诊断当前连接的设备
    python hardfault.py --json                   # JSON 输出
    python hardfault.py --map path/to/firmware.map  # 指定 map 文件路径
    python hardfault.py --json --fault-text capture.txt
        # F-116/H-1: 传入含层 1 [HF] PC=/LR= 行的捕获文本 (verify 落盘的
        # captured_output), 把真实故障点单独解析为 fault_site 字段。
        # live PC/LR 在 handler 自旋场景指向 HardFault 处理链内 (halt 时
        # IPSR≠0, CPU 正停在 handler), 不是故障现场——两回事必须分开呈现。

工作原理:
    1. OpenOCD init → halt → 读取所有寄存器 + SCB 故障寄存器
    2. 解码 CFSR/HFSR 位域, 识别 Fault 类型
    3. 解析 .map 符号表, 将 PC/LR/BFAR 解析为函数名
    4. (可选) 从层 1 [HF] 行提取压栈帧 PC/LR, 解析为 fault_site (真实现场)
    5. 生成结构化诊断报告, 由 Claude AI 做最终判断
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

from wb_common import find_project_root, load_machine
from runtime_common import now_iso  # F-157: UTC+8 本地版收编共享层


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)
# 机器路径只允许存在于 machine.json (与 verify.py 同模式)
# F-054: OPENOCD_EXE 模块级常量已惰性化——import 期零 IO, 解析点在 run_openocd_diag()

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


# F-157: 本地 now_iso (UTC+8 硬编码) 删除, 收编 runtime_common 共享版
# (astimezone 本地时区) — 时区口径变化见 CHANGELOG。

def run_openocd_diag() -> str:
    """运行 OpenOCD 读取故障寄存器, 返回原始输出文本"""
    openocd_exe = load_machine()["openocd_exe"]  # F-054: 惰性解析 (原模块级常量)
    cmd = [
        openocd_exe,
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
        "-c", "mdw 0xE000ED28 1",   # CFSR (首读: 诊断依据)
        "-c", "mdw 0xE000ED2C 1",   # HFSR
        "-c", "mdw 0xE000ED38 1",   # BFAR
        "-c", "mdw 0xE000ED34 1",   # MMFAR
        # F-109 (真机取证结案): CFSR/HFSR 是 W1C 粘滞位, 只读不清会把
        # 本次故障位留给下一次诊断 (陈旧位误诊)。读到即报告, 随即写全 1
        # 清除 + 复读取证 residual。BFAR/MMFAR 普通 R/W 不清——CFSR 的
        # BFSR.BFARVALID/MFSR.MMARVALID 位清后其值即声明失效。
        "-c", "mww 0xE000ED28 0xFFFFFFFF",
        "-c", "mww 0xE000ED2C 0xFFFFFFFF",
        "-c", "mdw 0xE000ED28 1",   # 复核: 粘滞位卫生状态
        "-c", "mdw 0xE000ED2C 1",
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


def parse_mdw_all_values(text: str, target_addr: int) -> list:
    """提取某地址所有 mdw 读取值 (按出现顺序)。

    F-109: CFSR/HFSR 清位前后各读一次 → [清除前, 复核残值]。调用方取
    [0] 作诊断依据, [-1] 作粘滞位卫生复核; 只有一次读时不虚构残值。"""
    pattern = rf'{target_addr:#010x}:\s*([0-9a-fA-F]+)'
    return [int(m, 16) for m in re.findall(pattern, text, re.IGNORECASE)]


def sticky_hygiene(regs: dict) -> dict:
    """粘滞位卫生结论: 读后 W1C 清除是否生效。

    cleared: True=复核读到 0 / False=仍有残值 (写路径异常或复位竞态,
    如实报告不隐藏) / None=二次读缺失, 不可知。"""
    out = {}
    for name in ("cfsr", "hfsr"):
        before = regs.get(name)
        after = regs.get(f"{name}_residual")
        out[name] = {
            "before": f"0x{before:08X}" if before is not None else "N/A",
            "after": f"0x{after:08X}" if after is not None else None,
            "cleared": (after == 0) if after is not None else None,
        }
    return out


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
        vals = parse_mdw_all_values(raw_output, addr)
        if vals:
            regs[name] = vals[0]  # 诊断依据 = 清除前首读
        # F-109: 粘滞位有清后复核读 → 末值作 residual; 普通 R/W 或
        # 单次读不虚构 (无第二值即无键)。
        if name in ("cfsr", "hfsr") and len(vals) >= 2:
            regs[f"{name}_residual"] = vals[-1]

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


_GCC_SYM_RE = re.compile(r"^\s+0x([0-9a-fA-F]{1,16})\s+([A-Za-z_][A-Za-z0-9_.]*)$")


def _parse_gcc_map_symbols(lines: list[str]) -> list[dict]:
    """解析 GNU ld map 的符号行: 缩进的 `0xADDR  name` 两列形态。

    排除 `. = ALIGN(...)` 等伪行 (name 须以字母/下划线开头);
    三列以上 (section/addr/size/obj) 行不匹配。type/size/object 字段
    ld map 不提供, 置空保持 schema 兼容。"""
    symbols = []
    for line in lines:
        m = _GCC_SYM_RE.match(line.rstrip())
        if m:
            symbols.append({"name": m.group(2), "addr": int(m.group(1), 16),
                            "type": "", "size": 0, "object": ""})
    return symbols


def parse_map_symbols(map_path: str) -> list[dict]:
    """解析 .map 文件的全局符号表, 返回 [{name, addr, size, type}, ...]"""
    symbols = []
    if not os.path.exists(map_path):
        return symbols

    with open(map_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # GCC ld map 无 "Global Symbols" 段 — 插板终判实测 (F-005 全貌 = 死路径+
    # ARMCC-only 解析器): 检出 GCC 版式则走 ld 分支, ARMCC 路径行为不变。
    if lines and not any("Global Symbols" in ln for ln in lines):
        gcc = _parse_gcc_map_symbols(lines)
        if gcc:
            return gcc

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


_HF_SITE_RE = re.compile(r"\[HF\] PC=([0-9A-Fa-f]{8}) LR=([0-9A-Fa-f]{8})")


def parse_hf_site(text: str) -> dict | None:
    """F-116/H-1: 从层 1 捕获文本提取压栈帧 PC/LR (真实故障点)。

    handler 自旋场景下 live PC 恒在 HardFault 处理链内 (halt 时 IPSR≠0),
    唯一携带故障现场的文本就是模板的 `[HF] PC=xxxxxxxx LR=xxxxxxxx` 行。
    只认大写十六进制 8 位 (模板契约); 无该行返回 None (semihosting-era
    blink 版无此行, 行为向后兼容)。取首个命中——多命中意味着重复 fault
    现场混窗, 层 1 自旋使二次 fault 不可能进同一缓冲, 保守取先者如实。"""
    m = _HF_SITE_RE.search(text or "")
    if not m:
        return None
    return {"pc": int(m.group(1), 16), "lr": int(m.group(2), 16)}


def resolve_address(addr: int, symbols: list[dict]) -> dict | None:
    """将地址解析为最近的符号名（地址在符号范围内）"""
    best = None
    best_size = 0
    for sym in symbols:
        if sym["addr"] <= addr < sym["addr"] + sym["size"]:
            # F-082: 优先匹配最小包含符号（更精确）。旧实现 `size > best_size`
            # 实际选最大包含符号，与注释意图矛盾（F-081 发现登记）——
            # 嵌套场景 PC 落在大函数内的小 helper 时会误报外层函数。
            if best is None or sym["size"] < best_size:
                best = sym
                best_size = sym["size"]
    if best:
        offset = addr - best["addr"]
        return {"name": best["name"], "offset": offset, "size": best["size"]}
    # F-005 第三层 (插板终判实测): GCC ld map 符号无 size → 区间匹配恒空。
    # 兜底=最近前导符号 (最大 addr ≤ 目标); ARMCC 主路径语义不变。
    cand = [s for s in symbols if s["addr"] <= addr]
    if not cand:
        return None
    sym = max(cand, key=lambda s: s["addr"])
    return {"name": sym["name"], "offset": addr - sym["addr"], "size": sym["size"]}


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
            # F-118 (工单 P0-6): 旧实现 idx = lr & 0xF 对合法值 F1/F9/FD 得
            # 1/9/13, 4 项表 → F9 (最常见, 返回 Thread/MSP) 恒 unknown,
            # F1 被错标。按 ARMv7-M: EXC_RETURN 描述"返回到哪", 低位语义
            # bit3=目标模式, bit2=目标堆栈 → 合法值恰为 F1/F5/F9/FD。
            exc_return = {
                0x1: "返回 Handler 模式 (MSP)",
                0x5: "保留/Secure (M3 非法组合: Handler+PSP)",
                0x9: "返回 Thread 模式 (MSP)",
                0xD: "返回 Thread 模式 (PSP)",
            }
            idx = (lr >> 2) & 3
            key = 0x1 | (idx << 2)  # idx 0→F1, 1→F5, 2→F9, 3→FD
            desc = exc_return.get(key, "unknown")
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


def _read_fault_text(spec: str) -> str:
    """读 --fault-text 指定的捕获文本 ('-' = stdin)。不可读返回空串。"""
    try:
        if spec == "-":
            return sys.stdin.read()
        with open(spec, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        print(f"WARNING: --fault-text 不可读: {e}", file=sys.stderr)
        return ""


def _diagnose_from_text(args, started_at, started_ts) -> None:
    """--no-probe 仅解析通道 (F-130, 工单二 A-3): 不触 OpenOCD。

    MCP diagnose_hardfault 工具的底座: agent 手里已有捕获文本 (run_verify
    产物), 解析层 1 [HF] PC=/LR= 现场行即可定位故障点, 不必也无权抢探针。
    无 live 寄存器 → fault_type/CFSR 分析缺席, 诚实标注而非伪装完整诊断。
    退出码: 解析出诊断 = 0; 文本不可得/无现场行 = 1 (消费方按 rc 分流)。"""
    if not args.fault_text:
        result = {"status": "error",
                  "error": "--no-probe 需要配 --fault-text (无探针即无 live 寄存器, "
                           "没有文本就没有可解析的现场)"}
        print(json.dumps(result, ensure_ascii=False, indent=2)
              if args.json else result["error"])
        sys.exit(1)

    cap_text = _read_fault_text(args.fault_text)
    map_path = args.map or _default_map_path()
    symbols = parse_map_symbols(map_path)
    note = _map_degradation_note(map_path, symbols)
    if note:
        print("WARNING: " + note, file=sys.stderr)
    site = parse_hf_site(cap_text)

    resolved = {}
    fault_site = None
    if site:
        fault_site = {
            "pc": f"0x{site['pc']:08X}",
            "lr": f"0x{site['lr']:08X}",
            "source": "layer1_stacked_frame",
        }
        for key in ("pc", "lr"):
            if site[key] > 0x08000000:
                sym = resolve_address(site[key], symbols)
                if sym:
                    fault_site[key + "_sym"] = f"{sym['name']}+{sym['offset']}"
                    resolved[key] = fault_site[key + "_sym"]

    result = {
        "status": "parsed_text_only" if site else "no_fault_marker",
        "probe": "skipped (--no-probe, 仅解析不触硬件)",
        **({"fault_site": fault_site} if fault_site else {}),
        "resolved": resolved,
        "diagnosis": (
            "仅层 1 现场行解析 (--no-probe): 故障点已定位; fault_type/CFSR "
            "位级归因需 live 探针, 建议接入真机后跑完整 hardfault.py 复核"
            if site else
            "捕获文本无 [HF] PC=/LR= 现场行 — 无 HardFault 痕迹或文本不是 "
            "故障现场 (--no-probe 无 live 寄存器可兜底)"),
        "symbols_total": len(symbols),
        "needs_ai_judgement": True,
        "_meta": {
            "map_file": map_path,
            "timestamp": started_at,
            "elapsed_sec": round(time.time() - started_ts, 1),
        },
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["diagnosis"])
    sys.exit(0 if site else 1)


def _default_map_path() -> str:
    """默认 .map: 从 cwd 向上发现工程根, 取 lst/ 下第一个 .map。

    F-005: 旧默认 <toolkit 仓根>/lst/blink.map 是 blink 退役残留 —
    路径恒不存在 → 符号解析恒空, 诊断静默降级无告警。verify.py 子进程
    调用时 cwd=工程根, 手工运行在工程目录内同样可发现。"""
    root = find_project_root(os.getcwd())
    if root:
        # build/ 优先: GCC 工程 map 在 build/ (2026-08-30 插板终判实测 —
        # 只找 lst/ 是 Keil 时代口径, 对 adc-oled 恒 miss 落回死兜底);
        # lst/ 兼容 Keil-era 工程。
        for sub in ("build", "lst"):
            d = os.path.join(root, sub)
            if os.path.isdir(d):
                maps = sorted(glob.glob(os.path.join(d, "*.map")))
                if maps:
                    return maps[0]
    return os.path.join(WORKSPACE, "lst", "blink.map")


def main():
    parser = argparse.ArgumentParser(description="HardFault 自动诊断器")
    parser.add_argument("--map", default=None,
                        help=".map 文件路径 (默认: cwd 向上发现工程 lst/*.map, F-005)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--raw", action="store_true", help="输出 OpenOCD 原始输出")
    parser.add_argument("--fault-text", default=None,
                        help="含层 1 [HF] PC=/LR= 行的捕获文本路径, '-'=stdin "
                             "(F-116/H-1: handler 自旋场景下 live PC 非故障现场)")
    parser.add_argument("--no-probe", action="store_true",
                        help="只解析不探针 (F-130, MCP 通道底座): 跳过 OpenOCD "
                             "现场读取, 仅用 --fault-text 的层 1 现场行出诊断")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()

    if args.no_probe:
        _diagnose_from_text(args, started_at, started_ts)
        return

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

    # F-116/H-1: 层 1 现场行 → fault_site (真实故障点, 与 live PC 分开呈现)
    fault_site = None
    if args.fault_text:
        try:
            if args.fault_text == "-":
                cap_text = sys.stdin.read()
            else:
                with open(args.fault_text, encoding="utf-8",
                          errors="replace") as f:
                    cap_text = f.read()
        except OSError as e:
            cap_text = ""
            print(f"WARNING: --fault-text 不可读: {e}", file=sys.stderr)
        site = parse_hf_site(cap_text)
        if site:
            fault_site = {
                "pc": f"0x{site['pc']:08X}",
                "lr": f"0x{site['lr']:08X}",
                "source": "layer1_stacked_frame",
            }
            for key in ("pc", "lr"):
                if site[key] > 0x08000000:
                    sym = resolve_address(site[key], symbols)
                    if sym:
                        fault_site[key + "_sym"] = \
                            f"{sym['name']}+{sym['offset']}"
            xpsr = regs.get("xpsr", 0)
            if isinstance(xpsr, int) and (xpsr & 0x1FF):
                fault_site["live_pc_note"] = (
                    "halt 现场 IPSR≠0 (异常上下文内 halt): live PC 属 handler "
                    "处理链, 故障现场以 fault_site 为准")

    result = {
        "status": "hardfault_detected",
        "fault_type": fault["primary"],
        "registers": {k: f"0x{v:08X}" if isinstance(v, int) else v
                       for k, v in regs.items()
                       if not k.startswith("_") and not k.endswith("_residual")},
        "fault_registers": {
            "cfsr": {"raw": f"0x{regs.get('cfsr',0):08X}", "bits": fault["cfsr_bits"]},
            "hfsr": {"raw": f"0x{regs.get('hfsr',0):08X}", "bits": fault["hfsr_bits"]},
            "bfar": f"0x{regs.get('bfar',0):08X}" if regs.get("bfar") else "N/A",
            "mmfar": f"0x{regs.get('mmfar',0):08X}" if regs.get("mmfar") else "N/A",
        },
        # F-109: 粘滞位卫生复核 (读→清→复读); 消费方据此判断残值污染
        "sticky_hygiene": sticky_hygiene(regs),
        "resolved": resolved,
        # F-116/H-1: 仅当 --fault-text 提供且含层 1 现场行时在场
        **({"fault_site": fault_site} if fault_site else {}),
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
    print("\nRegisters:")
    for name, val in r["registers"].items():
        print(f"  {name:>5}: {val}")
    print("\nFault Registers:")
    fr = r["fault_registers"]
    print(f"  CFSR:  {fr['cfsr']['raw']}  ({len(fr['cfsr']['bits'])} bits active)")
    print(f"  HFSR:  {fr['hfsr']['raw']}  ({len(fr['hfsr']['bits'])} bits active)")
    print(f"  BFAR:  {fr['bfar']}")
    print(f"  MMFAR: {fr['mmfar']}")
    sh = r.get("sticky_hygiene") or {}
    for reg, info in sh.items():
        if info["cleared"] is True:
            mark = "已清除"
        elif info["cleared"] is False:
            mark = "仍残值!"
        else:
            mark = "未复核"
        print(f"  {reg.upper()} 粘滞位: {info['before']} → 清后复核 "
              f"{info['after'] or '?'} ({mark})")
    if r["resolved"]:
        print("\nResolved:")
        for k, v in r["resolved"].items():
            print(f"  {k}: {v}")
    fs = r.get("fault_site")
    if fs:
        print("\nFault Site (层 1 压栈帧, F-116/H-1):")
        print(f"  PC: {fs['pc']}"
              + (f" → {fs['pc_sym']}" if fs.get("pc_sym") else ""))
        print(f"  LR: {fs['lr']}"
              + (f" → {fs['lr_sym']}" if fs.get("lr_sym") else ""))
        if fs.get("live_pc_note"):
            print(f"  ⚠ {fs['live_pc_note']}")
    print(f"\nDiagnosis:\n  {r['diagnosis']}")
    print(f"\nSymbols loaded: {r['symbols_total']}")
    if r.get("_note"):
        print(f"\nNote: {r['_note']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
