#!/usr/bin/env python3
"""
phase_minus_one.py — Drafter 前置兼容性检查

在 Drafter 开始写代码前，验证：
  1. 芯片是否支持目标外设
  2. 引脚是否冲突
  3. 知识库覆盖度（FULL/PARTIAL/NONE）
  4. 已知硬件陷阱

用法:
  python phase_minus_one.py --peripheral I2C1 --pins PB6,PB7
  python phase_minus_one.py --peripheral USART1 --pins PA9,PA10 --json
  python phase_minus_one.py --peripheral SPI2
  python phase_minus_one.py --list     # 列出所有已知外设和覆盖状态
"""

import argparse
import json
import os

from wb_common import TOOLKIT_ROOT, find_project_root, load_ref  # F-157: load_ref 收编

ISSUES_PATH = os.path.join(TOOLKIT_ROOT, "data", "f103_known_issues.json")


def load_fixed_pins(workspace):
    """F-158 (P2-4): 固定引脚占用表外置到工程 .workbench/fixed_pins.json —
    仓内硬编码 FIXED_PINS (维护者 adc-oled 专属) 属数据走私, 已删。
    文件形态: {"PC13": "LED heartbeat (GPIO Output)", ...}。
    缺省 (文件不在场或无 workspace) 返回 None — 冲突检查跳过不报错。"""
    if not workspace:
        return None
    path = os.path.join(workspace, ".workbench", "fixed_pins.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def load_issues():
    if not os.path.exists(ISSUES_PATH):
        return {}
    with open(ISSUES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


# F-194 (WB-20260927-02 T1): available_on_c8 字段缺失时的白名单封闭集 —
# 55 外设 = 30 true / 22 false / 3 缺字段, 缺者皆核心系统外设 (GPIO 外设
# 集族/NVIC/SysTick), C8 定义上可用。显式豁免纪律 (F-186 先例 =
# test_ref_bus_crosscheck CLOCK_EXEMPTION_SNAPSHOT): 新成员入场 = 过设计
# (改本集 + 同步 tests 钉快照), 数据侧缺字段集与本集双向互证 (钉两面)。
SYSTEM_PERIPHERALS = frozenset({"GPIO", "NVIC", "SysTick"})


def check_chip_support(peripheral, ref):
    """检查 F103 是否有此外设 (F-194: 消费 available_on_c8 三态)

    三态: is False → UNAVAILABLE (不在目标芯片, verdict BLOCKED — C8 工程
    真用 TIM5 是死路, 前置闸拦下胜过 WARN 放行白耗 HIL); is True → OK
    逐字节不变; 字段缺失 → 白名单集内 OK+注记, 集外单列 WARN 不静默。
    """
    rels = ref.get("_relationships", {})
    periphs = ref.get("peripherals", {})

    if peripheral in periphs:
        avail = periphs[peripheral].get("available_on_c8")
        if avail is False:
            return {"status": "UNAVAILABLE",
                    "detail": (f"{peripheral} not available on STM32F103C8T6 "
                               f"(available_on_c8=false in KB)")}
        if avail is None:
            if peripheral in SYSTEM_PERIPHERALS:
                return {"status": "OK",
                        "detail": (f"{peripheral} in knowledge base "
                                   f"(FULL coverage) — "
                                   "system-peripheral, field absent")}
            return {"status": "WARN",
                    "detail": (f"{peripheral} available_on_c8 field absent "
                               "and not in system-peripheral whitelist — "
                               "verify F103 datasheet")}
        return {"status": "OK", "detail": f"{peripheral} in knowledge base (FULL coverage)"}
    elif peripheral in rels:
        return {"status": "OK", "detail": f"{peripheral} available on F103 (PARTIAL KB coverage)"}
    else:
        # 不在知识库中，但 F103 可能支持
        return {"status": "UNKNOWN", "detail": f"{peripheral} not in knowledge base — verify F103 datasheet"}


def check_pin_conflicts(pins, peripheral, fixed_pins):
    """检查目标引脚是否与现有功能冲突 (F-158: 占用表外置, 第三参为
    load_fixed_pins() 的结果; None = 工程未配置占用表, 跳过不报错)"""
    if fixed_pins is None:
        return {"status": "OK",
                "detail": ("No fixed-pins map (.workbench/fixed_pins.json) "
                           "— conflict check skipped")}
    if not pins:
        return {"status": "OK", "detail": "No pins specified"}

    conflicts = []
    shares = []

    for pin in pins:
        pin = pin.strip().upper()
        if pin in fixed_pins:
            existing = fixed_pins[pin]
            # 判断是冲突还是共享
            if peripheral.upper() in existing.upper():
                shares.append(f"{pin}: {existing} (same peripheral — OK to share)")
            else:
                conflicts.append(f"{pin}: used by {existing}")

    if conflicts:
        return {
            "status": "CONFLICT",
            "detail": "; ".join(conflicts),
            "shared": shares if shares else None
        }
    elif shares:
        return {
            "status": "OK",
            "detail": "Pins share bus with existing device(s): " + "; ".join(shares)
        }
    else:
        return {"status": "OK", "detail": "No conflicts with fixed pins"}


def check_kb_coverage(peripheral, ref):
    """知识库覆盖度分级"""
    periphs = ref.get("peripherals", {})
    rels = ref.get("_relationships", {})

    if peripheral in periphs:
        pdata = periphs[peripheral]
        reg_count = len(pdata.get("registers", {}))
        recipe_count = len(pdata.get("recipes", []))
        return {
            "status": "FULL",
            "detail": f"{peripheral}: {reg_count} registers, {recipe_count} recipes in KB"
        }
    elif peripheral in rels:
        rdata = rels[peripheral]
        has_pins = "pins" in rdata
        has_dma = "dma" in rdata
        has_irq = "irq" in rdata
        parts = []
        if has_pins: parts.append("pins")
        if has_dma: parts.append("DMA")
        if has_irq: parts.append("IRQ")
        return {
            "status": "PARTIAL",
            "detail": f"{peripheral}: relationship data only ({', '.join(parts)}). No register-level info in KB."
        }
    else:
        kb_list = list(periphs.keys())
        return {
            "status": "NONE",
            "detail": f"{peripheral} not in knowledge base. KB covers: {', '.join(kb_list)}"
        }


def check_known_issues(peripheral, issues):
    """检查外设有无已知硬件陷阱"""
    if not issues:
        return {"status": "OK", "detail": "No known issues database loaded"}

    # 匹配：I2C1 → "I2C", USART1 → "USART", TIM2 → "TIM"
    for category, info in issues.items():
        if peripheral.upper().startswith(category.upper()):
            warnings = []
            for key, value in info.items():
                if key != "workaround":
                    warnings.append(f"{key}: {value}")
            if warnings:
                workaround = info.get("workaround", "")
                result = {"status": "WARN", "detail": "; ".join(warnings)}
                if workaround:
                    result["workaround"] = workaround
                return result

    return {"status": "OK", "detail": "No known issues for this peripheral"}


def compute_verdict(checks):
    """综合所有检查 → 最终裁定 (F-194: UNAVAILABLE 与 CONFLICT/UNKNOWN 同级
    参与 BLOCKED — 不在目标芯片的外设是死路, 不许以 WARN 面放行)"""
    statuses = [c.get("status", "OK") for c in checks.values()]
    if "CONFLICT" in statuses or "UNKNOWN" in statuses or "UNAVAILABLE" in statuses:
        return "BLOCKED"
    if "WARN" in statuses or "PARTIAL" in statuses or "NONE" in statuses:
        return "OK_WITH_WARNINGS"
    return "OK"


def run_check(peripheral, pins, target_desc="", workspace=None):
    """执行完整检查，返回结构化结果。
    F-158: features 形参删除 (旧版解析即弃, 从未参与判定);
    workspace 用于加载工程占用表 fixed_pins.json。"""
    ref = load_ref()
    issues = load_issues()

    checks = {
        "chip_support": check_chip_support(peripheral, ref),
        "pin_conflict": check_pin_conflicts(
            pins, peripheral, load_fixed_pins(workspace)),
        "kb_coverage": check_kb_coverage(peripheral, ref),
        "known_issues": check_known_issues(peripheral, issues),
    }

    recommendations = []
    cs_status = checks["chip_support"]["status"]
    if cs_status == "UNAVAILABLE":
        # F-194: 已知不可用 → 泛化的"查数据手册"建议是错话, 给行动指向
        recommendations.append(
            f"{peripheral} is not available on STM32F103C8T6 — pick a "
            "different peripheral or target chip (available_on_c8=false)")
    elif cs_status != "OK":
        recommendations.append("Verify peripheral availability in STM32F103 datasheet")
    if checks["kb_coverage"]["status"] in ("PARTIAL", "NONE"):
        recommendations.append(
            f"AI will generate {peripheral} code from training data only — "
            "no graph verification. Review carefully against reference manual."
        )
    if checks["known_issues"]["status"] == "WARN":
        w = checks["known_issues"].get("workaround", "")
        if w:
            recommendations.append(f"Known issue workaround: {w}")

    return {
        "chip": "STM32F103C8T6",
        "target": target_desc or f"{peripheral} driver",
        "verdict": compute_verdict(checks),
        "checks": checks,
        "recommendations": recommendations,
    }


def cmd_list(ref):
    """列出所有已知外设及覆盖状态"""
    periphs = ref.get("peripherals", {})
    rels = ref.get("_relationships", {})

    print(f"\n{'Peripheral':<12} {'KB Coverage':<12} {'Bus':<8} {'Pins/DMA/IRQ'}")
    print("-" * 72)

    all_names = sorted(set(list(periphs.keys()) + list(rels.keys())))
    for name in all_names:
        if name in periphs:
            p = periphs[name]
            print(f"{name:<12} {'FULL':<12} {p.get('bus','?'):<8} {p.get('base','?')}")
        elif name in rels:
            r = rels[name]
            flags = ""
            if "pins" in r: flags += "pins "
            if "dma" in r: flags += "DMA "
            if "irq" in r: flags += "IRQ "
            print(f"{name:<12} {'PARTIAL':<12} {r.get('bus','?'):<8} {flags.strip()}")

    print(f"\nFULL:  {len(periphs)} peripherals (register-level KB)")
    print(f"PARTIAL: {len(rels) - len([k for k in rels if k in periphs])} peripherals (relationship data only)")
    print("Chip: STM32F103C8T6 | Flash: 64KB | SRAM: 20KB\n")


def main():
    parser = argparse.ArgumentParser(description="Phase -1: Pre-Drafter compatibility check")
    parser.add_argument("--peripheral", "-p", default="", help="Target peripheral (e.g. I2C1, USART2)")
    parser.add_argument("--pins", default="", help="Comma-separated pins (e.g. PB6,PB7)")
    parser.add_argument("--target", default="", help="Human-readable task description")
    parser.add_argument("--json", action="store_true", help="JSON output (for Claude consumption)")
    parser.add_argument("--list", action="store_true", help="List all known peripherals and coverage")
    args = parser.parse_args()

    ref = load_ref()

    if args.list:
        cmd_list(ref)
        return

    if not args.peripheral:
        parser.print_help()
        print("\nExample: python phase_minus_one.py -p I2C1 --pins PB6,PB7 --target 'MPU6050 driver'")
        return

    pins = [p.strip() for p in args.pins.split(",") if p.strip()]
    # F-158: features 解析即弃的死代码删除 (旧版 split 后从未参与判定)
    result = run_check(args.peripheral.upper(), pins, args.target,
                       workspace=find_project_root(os.getcwd()))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 人类可读输出
        print(f"\n=== Phase -1: {result['target']} ===\n")
        for name, check in result["checks"].items():
            icon = {"OK": "PASS", "WARN": "WARN", "CONFLICT": "FAIL", "UNKNOWN": "????",
                    "UNAVAILABLE": "UNAV",
                    "FULL": "FULL", "PARTIAL": "PART", "NONE": "NONE"}.get(check["status"], check["status"])
            print(f"  [{icon:4s}] {name}: {check['detail']}")
            if "shared" in check and check["shared"]:
                for s in check["shared"]:
                    print(f"         {s}")

        print(f"\n  Verdict: {result['verdict']}")
        if result["recommendations"]:
            print("  Recommendations:")
            for r in result["recommendations"]:
                print(f"    - {r}")
        print()


if __name__ == "__main__":
    main()
