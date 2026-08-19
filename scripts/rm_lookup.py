#!/usr/bin/env python3
"""
STM32F103 参考手册快速查询工具

用法:
    python rm_lookup.py RCC                     # 查外设全部信息
    python rm_lookup.py APB2ENR                 # 查寄存器
    python rm_lookup.py "bit 3"                 # 查位含义 (需结合上下文)
    python rm_lookup.py --list                  # 列出所有外设
    python rm_lookup.py --recipe PWM            # 搜索配方
    python rm_lookup.py --json                  # 输出 JSON 格式
"""

import argparse
import json
import os
import re
import sys

from wb_common import TOOLKIT_ROOT

REF_PATH = os.path.join(TOOLKIT_ROOT, "data", "stm32f103-ref.json")


def load_ref() -> dict:
    with open(REF_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


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


def format_result(result: dict):
    """人类可读输出"""
    query = result["query"]
    periphs = result["peripherals"]
    regs = result["registers"]
    bits = result["bits"]
    recipes = result["recipes"]

    print(f"\n=== 搜索: \"{query}\" ===\n")

    if periphs:
        print("> 外设:")
        for p in periphs:
            pdata = p["data"]
            print(f"  {p['name']} — {pdata.get('description','')}")
            print(f"    基址: {pdata.get('base','')}  总线: {pdata.get('bus','')}")
            if pdata.get("clock_enable"):
                print(f"    时钟使能: {pdata['clock_enable']}")
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
                print(f"    {rdata.get('description','')}")
                if rdata.get("formula"):
                    print(f"    公式: {rdata['formula']}")
                bits_list = rdata.get("bits", {})
                if isinstance(bits_list, dict) and bits_list:
                    print(f"    位域:")
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
    parser = argparse.ArgumentParser(description="STM32F103 参考手册查询")
    parser.add_argument("query", nargs="?", default="", help="搜索词 (外设名/寄存器名/位名/配方关键词)")
    parser.add_argument("--list", action="store_true", help="列出所有外设和寄存器")
    parser.add_argument("--recipe", default=None, help="仅搜索配方")
    parser.add_argument("--rel", default=None, help="查外设关系 (e.g. 'USART1 DMA', 'I2C1 pins', 'USART2 clock')")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    global ref_data
    ref_data = load_ref()

    if args.list:
        print("\n=== STM32F103 参考手册知识库 ===\n")
        for pname, pdata in ref_data.get("peripherals", {}).items():
            print(f"[{pname}] {pdata.get('description','')}")
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
        print(f"共 {len(ref_data['peripherals'])} 个外设, 版本 {ref_data['_meta']['version']}")
        return

    if args.recipe:
        result = {"query": args.recipe, "recipes": search_recipe(args.recipe, ref_data)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            format_result(result)
        return

    if args.rel:
        result = search_relationships(args.rel, ref_data)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            format_rel_result(result)
        return

    if not args.query:
        parser.print_help()
        return

    result = search_all(args.query, ref_data)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        format_result(result)


if __name__ == "__main__":
    main()
