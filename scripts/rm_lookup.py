#!/usr/bin/env python3
"""
STM32F103 参考手册快速查询工具

用法:
    python rm_lookup.py RCC                     # 查外设全部信息
    python rm_lookup.py APB2ENR                 # 查寄存器
    python rm_lookup.py "bit 3"                 # 查位含义 (需结合上下文)
    python rm_lookup.py --list                  # 列出所有外设
    python rm_lookup.py --recipe PWM            # 搜索配方
    python rm_lookup.py --pins CAN              # 查外设引脚映射 (pin-mapping 档)
    python rm_lookup.py --json                  # 输出 JSON 格式
"""

import argparse
import json
import os
import sys

from wb_common import (  # F-157: 三份 load_ref 收编; F-203: UTF-8 咒语收编
    TOOLKIT_ROOT, force_utf8_streams, load_ref)

PIN_MAPPING_PATH = os.path.join(TOOLKIT_ROOT, "data", "pin-mapping-f103.json")

# F-204 (复审 M-3): 消费面 format_pins_result 直取三键 — 载入面校验必需键
_PIN_REQUIRED_KEYS = ("function", "column", "source")


class PinMappingError(Exception):
    """pin-mapping 数据档缺失/损坏 — 显式点名, 禁裸 traceback (F-198 T2 同式)。"""


def load_pin_mapping(path=None):
    """读引脚映射档 (F-199 T1: data/pin-mapping-f103.json 唯一事实源)。

    共享层零改动 (WB-20260927-07 简报禁区): 不动 wb_common, 直接 open
    加载; 缺失/不可解析/结构坏 → PinMappingError 点名文件与原因。
    """
    target = path or PIN_MAPPING_PATH
    if not os.path.isfile(target):
        raise PinMappingError(f"pin-mapping 数据档不存在: {target}")
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise PinMappingError(
            f"pin-mapping 数据档不可读/损坏: {target} ({exc})") from exc
    if not isinstance(data, dict):
        raise PinMappingError(
            f"pin-mapping 数据档损坏: {target} (顶层非对象)")
    for name, block in data.items():
        if name == "_meta":
            continue
        if not isinstance(block, dict):
            raise PinMappingError(
                f"pin-mapping 数据档损坏: {target} (外设块 {name} 非对象)")
        for pin, entry in block.items():
            if not isinstance(entry, dict):
                raise PinMappingError(
                    f"pin-mapping 数据档损坏: {target} "
                    f"({name}.{pin} 条目非对象)")
            # F-204 (复审 M-3): 缺消费键的潜伏档修前漏到 format 面裸
            # KeyError (与本模块"禁裸 traceback"自述矛盾, F-192 --recipe
            # 同族) — 载入面显式点名文件、条目与缺键名 (F-198 T2 同式)。
            missing = [k for k in _PIN_REQUIRED_KEYS if k not in entry]
            if missing:
                raise PinMappingError(
                    f"pin-mapping 数据档损坏: {target} "
                    f"({name}.{pin} 缺必需键 {', '.join(missing)})")
    return data


def search_pins(query, mapping):
    """--pins 查询 (F-199 T1): 查询词 upper() 精确匹配顶层外设块名 —
    禁模糊匹配、禁从 _relationships 或记忆推导 (宁缺毋滥)。
    入册值原样逐字输出 (F-193 P③: DS5319 Rev 20 表内拼写 CANRX/CANTX
    不得回写替换, 规范名 CAN_RX 就是入册值); 未入册返回动态 known 集
    (顶层块键导出, 禁硬编码)。查询无果不是错误 (exit 0)。"""
    name = query.strip().upper()
    if name and name != "_meta" and name in mapping:
        rows = [dict(pin=pin, **entry) for pin, entry in mapping[name].items()]
        return {"query": query, "registered": True, "rows": rows}
    return {"query": query, "registered": False,
            "known": sorted(k for k in mapping if k != "_meta")}


def format_pins_result(result):
    """--pins 人读输出: 已入册四列 (脚/功能/列位/source, 入册值原样);
    未入册 = 显式指认 + 当前入册集 + CHANGELOG 指路。"""
    name = result["query"].strip().upper()
    print(f"\n=== pin-mapping: {name} ===\n")
    if result["registered"]:
        print(f"  {'脚':<6} {'功能':<10} {'列位':<12} source")
        for row in result["rows"]:
            print(f"  {row['pin']:<6} {row['function']:<10} "
                  f"{row['column']:<12} {row['source']}")
    else:
        print(f"  \"{name}\" 未入册 (data/pin-mapping-f103.json)。")
        known = ", ".join(result["known"]) or "（空）"
        print(f"  当前入册外设集: {known}")
        print("  官方锚入册流程见 CHANGELOG F-189/F-193 节 (宁缺毋滥)。")
    print()


def run_pins_mode(query, json_mode=False, path=None):
    """--pins 分支主体 (与 --rel/--recipe 同级, 命中即 return); 库态可
    直调 (驱动先例: test_rm_lookup_pins.py 函数直调零打桩)。返回进程
    退出码: 查询无果=0 (未入册走显式指认), 数据档缺失/损坏=1 (stderr
    Error 行点名文件与原因)。"""
    try:
        mapping = load_pin_mapping(path)
    except PinMappingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    result = search_pins(query, mapping)
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        format_pins_result(result)
    return 0


def search_peripheral(query: str, ref: dict) -> list[dict]:
    """在外设名称中搜索"""
    results = []
    query_lower = query.lower()
    for name, data in ref.get("peripherals", {}).items():
        if query_lower in name.lower():
            results.append({"type": "peripheral", "name": name, "data": data})
    return results


def search_register(query: str, ref: dict) -> list[dict]:
    """在所有外设的寄存器中搜索"""
    results = []
    query_upper = query.upper()
    for pname, pdata in ref.get("peripherals", {}).items():
        for rname, rdata in pdata.get("registers", {}).items():
            if query_upper in rname.upper():
                results.append({
                    "type": "register",
                    "peripheral": pname,
                    "register": rname,
                    "data": rdata
                })
    return results


def search_bit(query: str, ref: dict) -> list[dict]:
    """在位域中搜索 (搜索位号或位名)"""
    results = []
    query_upper = query.upper()
    for pname, pdata in ref.get("peripherals", {}).items():
        for rname, rdata in pdata.get("registers", {}).items():
            bits = rdata.get("bits", {})
            if not isinstance(bits, dict):
                continue
            for bit_pos, bit_info in bits.items():
                if not isinstance(bit_info, dict):
                    continue
                bit_name = bit_info.get("name", "")
                bit_desc = bit_info.get("desc", "")
                if (query_upper in bit_name.upper() or
                    query_upper in bit_desc.upper() or
                    query_upper == bit_pos):
                    results.append({
                        "type": "bit",
                        "peripheral": pname,
                        "register": rname,
                        "bit": bit_pos,
                        "name": bit_name,
                        "desc": bit_desc
                    })
    return results


def search_recipe(query: str, ref: dict) -> list[dict]:
    """搜索配方"""
    results = []
    query_lower = query.lower()
    for pname, pdata in ref.get("peripherals", {}).items():
        for recipe in pdata.get("recipes", []):
            if (query_lower in recipe.get("title", "").lower() or
                query_lower in recipe.get("code", "").lower()):
                results.append({
                    "type": "recipe",
                    "peripheral": pname,
                    **recipe
                })
    return results


def search_all(query: str, ref: dict) -> dict:
    """全方位搜索"""
    return {
        "query": query,
        "peripherals": search_peripheral(query, ref),
        "registers": search_register(query, ref),
        "bits": search_bit(query, ref),
        "recipes": search_recipe(query, ref)
    }


def search_relationships(query: str, ref: dict) -> dict:
    """关系查询：解析 '外设名 关系类型' 格式的查询

    例: "USART1 DMA" → _relationships.USART1.dma
        "I2C1 pins"  → _relationships.I2C1.pins
        "USART2 IRQ" → _relationships.USART2.irq
        "TIM2 clock" → _relationships.TIM2.clock
        "SPI1"       → 全部关系
    """
    rels = ref.get("_relationships", {})
    if not rels:
        return {"query": query, "error": "No _relationships data in knowledge base"}

    parts = query.strip().split()
    periph_name = parts[0].upper()
    rel_type = parts[1].lower() if len(parts) > 1 else None

    if periph_name not in rels:
        # 尝试模糊匹配
        matches = [k for k in rels if periph_name in k]
        if matches:
            return {"query": query, "suggestion": f"Did you mean: {', '.join(matches)}?"}
        return {"query": query, "error": f"Peripheral '{periph_name}' not in relationships DB"}

    rdata = rels[periph_name]

    if rel_type is None:
        # 返回该外设的全部关系
        return {"query": query, "peripheral": periph_name, "relationships": rdata}

    # 匹配关系类型
    type_map = {
        "dma": "dma", "pins": "pins", "pin": "pins",
        "clock": "clock", "irq": "irq", "bus": "bus",
        "base": "base", "remap": "remap", "issues": "known_issues",
        "channels": "channels",
    }
    key = type_map.get(rel_type, rel_type)
    if key in rdata:
        return {"query": query, "peripheral": periph_name, "type": key, "data": rdata[key]}
    else:
        available = list(rdata.keys())
        return {
            "query": query,
            "peripheral": periph_name,
            "type": key,
            "error": f"'{rel_type}' not available. Available: {', '.join(available)}"
        }


def format_result(result: dict, ref_data: dict):
    """人类可读输出。F-133/d: ref_data 显式入参 — 旧版读模块级全局, 库态
    (未跑 main) 调用即 NameError; 对 peripherals 的裸下标取数同批清除。"""
    query = result["query"]
    # F-192 (WB-20260926-03 T2, 收 P-2): --recipe 分支只构造 {query,
    # recipes} — 裸下标四键使人读路径必崩 KeyError; 改 .get 缺省空列表,
    # 分支构造与 JSON 输出零变化 (逐字段回归钉护)。
    periphs = result.get("peripherals", [])
    regs = result.get("registers", [])
    bits = result.get("bits", [])
    recipes = result.get("recipes", [])

    print(f"\n=== 搜索: \"{query}\" ===\n")

    if periphs:
        print("> 外设:")
        for p in periphs:
            pdata = p["data"]
            print(f"  {p['name']} — {pdata.get('desc','')}")
            print(f"    基址: {pdata.get('base','')}  总线: {pdata.get('bus','')}")
            # F-191 (WB-20260926-02 T4, 收 L-1): 数据面无 clock_enable 键
            # (0/55 实测) — 死支改从 _relationships 反查; EXTI 的 clock=null
            # +clock_note 豁免形态照常呈现 note 文案 (F-186 纪律禁静默)。
            rel = ref_data.get("_relationships", {}).get(p["name"], {})
            if isinstance(rel.get("clock"), dict):
                ck = rel["clock"]
                print(f"    时钟使能: {ck.get('rcc_register','?')}"
                      f"[{ck.get('rcc_bit','?')}] {ck.get('rcc_bit_name','?')}")
            elif rel.get("clock_note"):
                print(f"    时钟使能: — {rel['clock_note']}")
            # 列出寄存器概要
            regs_summary = list(pdata.get("registers", {}).keys())
            if regs_summary:
                print(f"    寄存器: {', '.join(regs_summary)}")
            print()

    if regs:
        print("> 寄存器:")
        for r in regs:
            rdata = r["data"]
            if isinstance(rdata, dict):
                print(f"  {r['peripheral']} → {r['register']} ({rdata.get('offset','?')})")
                print(f"    {rdata.get('desc','')}")
                if rdata.get("formula"):
                    print(f"    公式: {rdata['formula']}")
                bits_list = rdata.get("bits", {})
                if isinstance(bits_list, dict) and bits_list:
                    print("    位域:")
                    for pos, info in bits_list.items():
                        if isinstance(info, dict):
                            print(f"      bit {pos}: {info.get('name','')} — {info.get('desc','')}")
                if rdata.get("examples"):
                    print(f"    常见值: {json.dumps(rdata['examples'], indent=6)}")
            print()

    if bits:
        print("> 位匹配:")
        for b in bits:
            print(f"  {b['peripheral']}::{b['register']} bit {b['bit']}: {b['name']} — {b['desc']}")
        print()

    if recipes:
        print("> 配方:")
        for i, r in enumerate(recipes, 1):
            print(f"  [{i}] {r.get('title','')}")
            if r.get("code"):
                for line in r["code"].split("\n"):
                    print(f"      {line}")
            print()

    if not (periphs or regs or bits or recipes):
        # 尝试模糊搜索
        print("  未找到精确匹配。试试:")
        print("    python rm_lookup.py --list       # 列出所有外设")
        print("    python rm_lookup.py --recipe PWM # 搜索配方")
        all_periphs = list(ref_data.get("peripherals", {}).keys())
        print(f"    已知外设: {', '.join(all_periphs)}")


def format_rel_result(result: dict):
    """格式化关系查询输出"""
    if "error" in result:
        print(f"\n  查询 \"{result['query']}\": {result['error']}")
        if "suggestion" in result:
            print(f"  {result['suggestion']}")
        return

    periph = result.get("peripheral", "?")
    if "relationships" in result:
        # 全部关系
        rdata = result["relationships"]
        print(f"\n=== {periph} 全部关系 ===\n")
        for key, val in rdata.items():
            if isinstance(val, dict):
                print(f"  {key}: {json.dumps(val, ensure_ascii=False)}")
            else:
                print(f"  {key}: {val}")
    elif "data" in result:
        data = result["data"]
        print(f"\n=== {periph} → {result['type']} ===\n")
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  {k}: {v}")
        else:
            print(f"  {data}")
    print()


def main():
    force_utf8_streams()  # F-203 (复审 M-2): 管道中文/§字节面, F-195 T1 同式
    parser = argparse.ArgumentParser(description="STM32F103 参考手册查询")
    parser.add_argument("query", nargs="?", default="", help="搜索词 (外设名/寄存器名/位名/配方关键词)")
    parser.add_argument("--list", action="store_true", help="列出所有外设和寄存器")
    parser.add_argument("--recipe", default=None, help="仅搜索配方")
    parser.add_argument("--rel", default=None, help="查外设关系 (e.g. 'USART1 DMA', 'I2C1 pins', 'USART2 clock')")
    parser.add_argument("--pins", default=None, help="查外设引脚映射 (data/pin-mapping-f103.json, e.g. CAN)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    global ref_data
    ref_data = load_ref()

    if args.list:
        print("\n=== STM32F103 参考手册知识库 ===\n")
        for pname, pdata in ref_data.get("peripherals", {}).items():
            print(f"[{pname}] {pdata.get('desc','')}")
            print(f"  基址: {pdata.get('base','')}  总线: {pdata.get('bus','')}")
            avail = pdata.get('available_on_c8')
            if avail is not None:
                mark = 'Y' if avail else 'N'
                print(f"  C8 可用: {mark}")
            regs = list(pdata.get("registers", {}).keys())
            print(f"  寄存器: {', '.join(regs)}")
            recipes_count = len(pdata.get("recipes", []))
            if recipes_count:
                print(f"  配方: {recipes_count} 个")
            print()
        print(f"共 {len(ref_data.get('peripherals', {}))} 个外设, "
              f"版本 {ref_data.get('_meta', {}).get('version', '?')}")
        return

    if args.recipe:
        result = {"query": args.recipe, "recipes": search_recipe(args.recipe, ref_data)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            format_result(result, ref_data)
        return

    if args.rel:
        result = search_relationships(args.rel, ref_data)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            format_rel_result(result)
        return

    if args.pins:
        # F-199 T1: --pins 消费面接线 (同级互斥, 命中即 return)。
        raise SystemExit(run_pins_mode(args.pins, args.json))

    if not args.query:
        parser.print_help()
        return

    result = search_all(args.query, ref_data)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        format_result(result, ref_data)


if __name__ == "__main__":
    main()
