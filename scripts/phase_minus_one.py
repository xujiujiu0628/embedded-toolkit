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
import sys

from wb_common import TOOLKIT_ROOT

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")
ISSUES_PATH = os.path.join(TOOLKIT_ROOT, "data", "f103_known_issues.json")

# ── 项目当前固定引脚占用（从 CLAUDE.md 和 main.c 提取）──
FIXED_PINS = {
    "PB8": "OLED_SCL (I2C1)",
    "PB9": "OLED_SDA (I2C1)",
    "PB10": "MPU6050_SCL (I2C2 / SW I2C)",
    "PB11": "MPU6050_SDA (I2C2 / SW I2C)",
    "PA2": "SG90 Servo (TIM2_CH3 PWM)",
    "PB0": "Button (GPIO Input, pull-up)",
    "PC13": "LED heartbeat (GPIO Output)",
}


def load_ref():
    with open(REF_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_issues():
    if not os.path.exists(ISSUES_PATH):
        return {}
    with open(ISSUES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def check_chip_support(peripheral, ref):
    """检查 F103 是否有此外设"""
    rels = ref.get("_relationships", {})
    periphs = ref.get("peripherals", {})

    if peripheral in periphs:
        return {"status": "OK", "detail": f"{peripheral} in knowledge base (FULL coverage)"}
    elif peripheral in rels:
        return {"status": "OK", "detail": f"{peripheral} available on F103 (PARTIAL KB coverage)"}
    else:
        # 不在知识库中，但 F103 可能支持
        return {"status": "UNKNOWN", "detail": f"{peripheral} not in knowledge base — verify F103 datasheet"}


def check_pin_conflicts(pins, peripheral, ref):
    """检查目标引脚是否与现有功能冲突"""
    if not pins:
        return {"status": "OK", "detail": "No pins specified"}

    conflicts = []
    shares = []

    for pin in pins:
        pin = pin.strip().upper()
        if pin in FIXED_PINS:
            existing = FIXED_PINS[pin]
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
    """综合所有检查 → 最终裁定"""
    statuses = [c.get("status", "OK") for c in checks.values()]
    if "CONFLICT" in statuses or "UNKNOWN" in statuses:
        return "BLOCKED"
    if "WARN" in statuses or "PARTIAL" in statuses or "NONE" in statuses:
        return "OK_WITH_WARNINGS"
    return "OK"


def run_check(peripheral, pins, features, target_desc=""):
    """执行完整检查，返回结构化结果"""
    ref = load_ref()
    issues = load_issues()

    checks = {
        "chip_support": check_chip_support(peripheral, ref),
        "pin_conflict": check_pin_conflicts(pins, peripheral, ref),
        "kb_coverage": check_kb_coverage(peripheral, ref),
        "known_issues": check_known_issues(peripheral, issues),
    }

    recommendations = []
    if checks["chip_support"]["status"] != "OK":
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
    print(f"Chip: STM32F103C8T6 | Flash: 64KB | SRAM: 20KB\n")


def main():
    parser = argparse.ArgumentParser(description="Phase -1: Pre-Drafter compatibility check")
    parser.add_argument("--peripheral", "-p", default="", help="Target peripheral (e.g. I2C1, USART2)")
    parser.add_argument("--pins", default="", help="Comma-separated pins (e.g. PB6,PB7)")
    parser.add_argument("--features", default="", help="Comma-separated features (e.g. DMA,interrupt)")
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
    features = [f.strip() for f in args.features.split(",") if f.strip()]
    result = run_check(args.peripheral.upper(), pins, features, args.target)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 人类可读输出
        print(f"\n=== Phase -1: {result['target']} ===\n")
        for name, check in result["checks"].items():
            icon = {"OK": "PASS", "WARN": "WARN", "CONFLICT": "FAIL", "UNKNOWN": "????",
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
