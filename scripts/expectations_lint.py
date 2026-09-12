#!/usr/bin/env python3
"""expectations.json 静态 lint — 不加载 verify.py / machine.json / 不触硬件。

动机 (R2 D 项, 2026-08-30): verify.load_expectations 的四类前置拦截只在
"verify 跑起来"时生效, 清单写错要到下次烧录采集才暴露。本工具把同一套
规则做成离线检查, 另加一条 verify 不查的**结构性矛盾**:

  E1  文件可解析 (UTF-8 JSON, 顶层含非空 expectations 数组)
  E2  条目为对象; id 非空字符串且全表唯一
  E3  desc 非空字符串
  E4  texts 与 patterns 二选一 (非空字符串数组)
  E5  patterns 可编译 (非法正则曾拖到烧录后才炸, 审计 M1)
  E6  xfail=true 时 xfail_reason 必填
  E7  capture_group 为正整数且仅与 patterns 搭配
  E8  min/max 为有限数值 (NaN 绕过边界比较恒 pass, 审计 M1)
  E9  min > max — 该条目永远 FAIL (verify 不查, 只有 lint 能提前抓)
  E10 forbidden_texts/patterns 结构 (非空字符串数组) + 非法正则 (F-112)
  E11 自杀配置: 同串并存于 texts 与 forbidden_texts (永远 FAIL) /
      xfail 条目配负断言 (WARNING, 语义错位疑点) (F-112)
  E12 record 结构 (非空字符串数组) + 仅与 patterns 搭配 +
      与 capture_group/min/max 互斥 (全量记录 vs 首匹配定界, 二选一) +
      引用的命名捕获组须在 patterns[0] 中定义 (F-148)
  E13 ordered 须为布尔 (F-148)

退出码: 0 = 干净/仅警告, 1 = 存在 error, 2 = 用法/文件不可得

用法:
  python scripts/expectations_lint.py <expectations.json 路径>
  python scripts/expectations_lint.py --project <工程根>
  python scripts/expectations_lint.py --project . --json
"""
import argparse
import json
import math
import os
import sys

from expectations import (  # F-157 (P2-3): E2~E8/E12/E13 判据单一事实源
    check_forbidden_fields, item_rule_errors)
from wb_common import find_project_root, force_utf8_streams


def lint_expectations(expectations):
    """对已解析的 expectations 数组做 E2~E11 检查, 返回 (errors, warnings)。"""
    errors = []
    warnings = []
    seen = set()
    if not isinstance(expectations, list) or not expectations:
        return ["E1: expectations 须为非空数组"], warnings
    for i, item in enumerate(expectations):
        where = f"expectations[{i}]"
        if not isinstance(item, dict):
            errors.append(f"E2: {where} 须为对象")
            continue
        eid = item.get("id")
        label = eid if isinstance(eid, str) and eid.strip() else f"<idx {i}>"
        # F-157 (P2-3): E2缺失/E3~E8/E13/E12 判据收敛 item_rule_errors
        # 单一事实源 (loader 同源); E2 id 重复与 E9 结构矛盾仍归 lint 专项
        for code, core in item_rule_errors(item):
            errors.append(f"{code}: {label} {core}")
        if isinstance(eid, str) and eid.strip():
            if eid in seen:
                errors.append(f"E2: id 重复: {eid}")
            seen.add(eid)
        # E9: min > max — 该条目永远 FAIL (verify 不查, 只有 lint 能提前抓)
        bounds = {}
        for bound in ("min", "max"):
            v = item.get(bound)
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and math.isfinite(v):
                bounds[bound] = v
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            errors.append(
                f"E9: {label} min({bounds['min']}) > max({bounds['max']}) — "
                "边界矛盾, 该条目永远 FAIL")
        # F-112: 负断言规则 E10 (结构/非法正则) + E11 (自杀配置/与 xfail 并存)
        # F-114/L-1: 码随判据走 (check_forbidden_fields 返回 (code,msg)), 不嗅探文案
        for code, msg in check_forbidden_fields(item):
            errors.append(f"{code}: {msg}")
        if item.get("xfail") and (item.get("forbidden_texts")
                                  or item.get("forbidden_patterns")):
            warnings.append(
                f"E11: {eid} xfail 条目配了负断言 — 未实现的功能谈不上"
                "\"禁止的恢复方式\", 疑为配置错位 (实现落地翻转后再配)")
        # F-148 E12/E13: 已随 F-157 收敛进 item_rule_errors (循环头部)
    if any(item.get("xfail") for item in expectations if isinstance(item, dict)):
        n = sum(1 for item in expectations
                if isinstance(item, dict) and item.get("xfail"))
        warnings.append(f"共 {n} 条 xfail 条目 — 发布前应翻转或 --allow-xfail 留痕")
    return errors, warnings


def lint_file(path):
    """lint 单个 expectations.json, 返回 {path, item_count, errors, warnings}。"""
    out = {"path": path, "item_count": 0, "errors": [], "warnings": []}
    if not os.path.isfile(path):
        out["errors"] = ["E0: 文件不存在"]
        return out
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        out["errors"] = [f"E1: 文件不可解析 (UTF-8 JSON): {e}"]
        return out
    if not isinstance(data, dict):
        out["errors"] = ["E1: 顶层须为 JSON 对象"]
        return out
    exps = data.get("expectations")
    if not isinstance(exps, list) or not exps:
        out["errors"] = ["E1: 须为含非空 expectations 数组的 JSON 对象"]
        return out
    out["item_count"] = len(exps)
    out["errors"], out["warnings"] = lint_expectations(exps)
    return out


def main():
    # F-025: 中文字段与错误报告按 ensure_ascii=False 输出, 必须与调用方环境
    # 无关地落 UTF-8 (Windows 控制台默认 GBK, 父进程/AI 按 utf-8 解码曾崩溃)
    force_utf8_streams()   # F-157: UTF-8 咒语收编 wb_common
    ap = argparse.ArgumentParser(
        description="expectations.json 静态 lint (离线, 不触硬件)")
    ap.add_argument("path", nargs="?", default=None,
                    help="expectations.json 路径")
    ap.add_argument("--project", default=None,
                    help="工程根 (lint 其 .workbench/expectations.json)")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    if args.path:
        path = args.path
    elif args.project:
        path = os.path.join(args.project, ".workbench", "expectations.json")
    else:
        root = find_project_root(os.getcwd())
        if not root:
            print("错误: 未指定路径/工程, 且 cwd 不在工程内", file=sys.stderr)
            return 2
        path = os.path.join(root, ".workbench", "expectations.json")

    result = lint_file(path)
    verdict = "error" if result["errors"] else (
        "warn" if result["warnings"] else "clean")
    if args.json:
        print(json.dumps({**result, "verdict": verdict},
                         ensure_ascii=False, indent=2))
    else:
        print(f"expectations lint: {path}  ->  {verdict.upper()}")
        for e in result["errors"]:
            print(f"  [E] {e}")
        for w in result["warnings"]:
            print(f"  [W] {w}")
        if not result["errors"] and not result["warnings"]:
            print(f"  {result['item_count']} 条期望全部合规")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
