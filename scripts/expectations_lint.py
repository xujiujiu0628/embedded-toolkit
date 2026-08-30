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
import re
import sys

from wb_common import find_project_root


def lint_expectations(expectations):
    """对已解析的 expectations 数组做 E2~E9 检查, 返回 (errors, warnings)。"""
    errors = []
    warnings = []
    seen = set()
    if not isinstance(expectations, list) or not expectations:
        return [f"E1: expectations 须为非空数组"], warnings
    for i, item in enumerate(expectations):
        where = f"expectations[{i}]"
        if not isinstance(item, dict):
            errors.append(f"E2: {where} 须为对象")
            continue
        eid = item.get("id")
        if not isinstance(eid, str) or not eid.strip():
            errors.append(f"E2: {where} id 必填且非空")
            eid = f"<idx {i}>"
        elif eid in seen:
            errors.append(f"E2: id 重复: {eid}")
        seen.add(eid)
        if not isinstance(item.get("desc"), str) or not item["desc"].strip():
            errors.append(f"E3: {eid} desc 必填且非空")
        texts = item.get("texts")
        pats = item.get("patterns")
        ok_texts = isinstance(texts, list) and len(texts) > 0 and \
            all(isinstance(t, str) and t for t in texts)
        ok_pats = isinstance(pats, list) and len(pats) > 0 and \
            all(isinstance(p, str) and p for p in pats)
        if ok_texts == ok_pats:
            errors.append(f"E4: {eid} texts 与 patterns 须二选一(非空字符串数组)")
        if ok_pats:
            for p in pats:
                try:
                    re.compile(p)
                except re.error as e:
                    errors.append(f"E5: {eid} 非法正则 {p!r}: {e}")
        if item.get("xfail") and (not isinstance(item.get("xfail_reason"), str)
                                  or not item["xfail_reason"].strip()):
            errors.append(f"E6: {eid} xfail=true 时 xfail_reason 必填")
        cg = item.get("capture_group")
        if cg is not None and (isinstance(cg, bool) or not isinstance(cg, int)
                               or cg < 1):
            errors.append(f"E7: {eid} capture_group 须为正整数")
        if cg is not None and not ok_pats:
            errors.append(f"E7: {eid} capture_group 须与 patterns 搭配")
        bounds = {}
        for bound in ("min", "max"):
            v = item.get(bound)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v):
                errors.append(f"E8: {eid} {bound} 须为有限数值")
            else:
                bounds[bound] = v
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            errors.append(
                f"E9: {eid} min({bounds['min']}) > max({bounds['max']}) — "
                "边界矛盾, 该条目永远 FAIL")
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
