#!/usr/bin/env python3
"""
token_stats.py — Claude Code 会话 Token 成本基线统计（只读）

扫描 ~/.claude/projects/<proj>/*.jsonl 的 assistant message usage 字段，
按 任务类型 / 日期 聚合，输出 表格 或 --json 报告。

用法:
    python token_stats.py                      # 本月基线表格
    python token_stats.py --json               # JSON 报告到 stdout
    python token_stats.py --project D--claude  # 指定项目目录名
    python token_stats.py --days 7             # 最近 7 天
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

# 任务类型关键词（按首个 user message 内容匹配，先到先得）
TASK_RULES = [
    ("verify",     re.compile(r"verify\.py|烧录|闪存|闭环|gate|hardfault|诊断", re.I)),
    ("build",      re.compile(r"keil|uv4|编译|构建|错误|warning", re.I)),
    ("design",     re.compile(r"DESIGN\.md|设计文档|brainstorm|方案", re.I)),
    ("docs",       re.compile(r"docx|报告|文档|Word", re.I)),
    ("discussion", re.compile(r"讨论|怎么实现|工作流|流程", re.I)),
]

# 模型单价 ($/M tokens) — DeepSeek v4 系，随 env 配置更新（估算值，输出标注"估算"）
PRICES = {
    "input":       0.27,   # 非缓存输入
    "output":      1.10,   # 输出
    "cache_read":  0.07,   # 缓存命中
    "cache_write": 1.10,   # 缓存写入
}


def classify(first_user_text: str) -> str:
    for name, pat in TASK_RULES:
        if pat.search(first_user_text or ""):
            return name
    return "misc"


def scan_jsonl(path: str) -> dict:
    """返回 {date: {task: {input, output, cache_read, cache_write, msgs}}}"""
    agg = {}
    first_user_text = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "user" and first_user_text is None:
                c = d.get("message", {}).get("content")
                if isinstance(c, str):
                    first_user_text = c
                elif isinstance(c, list):
                    first_user_text = " ".join(
                        x.get("text", "") for x in c if isinstance(x, dict))
            elif t == "assistant":
                u = d.get("message", {}).get("usage") or {}
                ts = d.get("timestamp", "")
                day = ts[:10] if ts else "unknown"
                task = classify(first_user_text)
                day_d = agg.setdefault(day, {})
                td = day_d.setdefault(task, {"input": 0, "output": 0,
                                             "cache_read": 0,
                                             "cache_write": 0, "msgs": 0})
                td["input"]        += u.get("input_tokens", 0)
                td["output"]       += u.get("output_tokens", 0)
                td["cache_read"]   += u.get("cache_read_input_tokens", 0)
                td["cache_write"]  += u.get("cache_creation_input_tokens", 0)
                td["msgs"]         += 1
    return agg


def cost(td: dict) -> float:
    return (td["input"] * PRICES["input"] + td["output"] * PRICES["output"]
            + td["cache_read"] * PRICES["cache_read"]
            + td["cache_write"] * PRICES["cache_write"]) / 1e6


def main():
    ap = argparse.ArgumentParser(description="Claude Code 会话 Token 成本基线（只读）")
    ap.add_argument("--project", default="D--claude",
                    help="~/.claude/projects 下的项目目录名 (默认 D--claude)")
    ap.add_argument("--json", action="store_true", help="JSON 输出到 stdout")
    ap.add_argument("--days", type=int, default=0,
                    help="0=本月, N=最近 N 天 (默认 0)")
    ap.add_argument("--out", default=None,
                    help="JSON 写入文件 (utf-8 无 BOM; 默认 stdout)")
    args = ap.parse_args()

    base = os.path.expanduser(os.path.join("~", ".claude", "projects", args.project))
    if not os.path.isdir(base):
        print(f"Error: project dir not found: {base}", file=sys.stderr)
        sys.exit(1)

    agg = {}
    parsed_files = 0
    for p in glob.glob(os.path.join(base, "*.jsonl")):
        try:
            r = scan_jsonl(p)
        except (OSError, UnicodeDecodeError):
            continue
        parsed_files += 1
        for day, tasks in r.items():
            agg.setdefault(day, {}).update(tasks)

    today = datetime.date.today()
    now_days = today.strftime("%Y-%m")
    if args.days:
        cutoff = (today - datetime.timedelta(days=args.days)).isoformat()
        agg = {d: t for d, t in agg.items() if d >= cutoff}

    # 汇总
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "msgs": 0}
    for day, tasks in agg.items():
        for task, td in tasks.items():
            for k in total:
                total[k] += td.get(k, 0)
    total["cost_usd"] = round(cost(total), 2)

    report = {
        "period": now_days if not args.days else f"last{args.days}d",
        "model_prices": PRICES,
        "note": "cost is estimate; prices configurable",
        "by_day": {d: {t: td for t, td in ts.items()}
                   for d, ts in sorted(agg.items())},
        "by_task": {},
        "total": total,
    }
    for day, tasks in agg.items():
        for task, td in tasks.items():
            bt = report["by_task"].setdefault(
                task, {k: 0 for k in total if k != "cost_usd"})
            for k in bt:
                bt[k] += td.get(k, 0)
    for task, bt in report["by_task"].items():
        bt["cost_usd"] = round(cost(bt), 2)

    if args.json:
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(payload)
            print(f"Written: {args.out}")
        else:
            print(payload)
    else:
        print(f"\n=== Token 基线 ({report['period']}) — 估算成本（单价可配）===")
        print(f"扫描 {parsed_files} 个会话文件")
        print(f"\n{'任务类型':<12}{'消息':>6}{'输入K':>9}{'输出K':>9}"
              f"{'缓存读K':>9}{'缓存写K':>9}{'成本$':>8}")
        for task, bt in sorted(report["by_task"].items(),
                               key=lambda x: -x[1]["cost_usd"]):
            print(f"{task:<12}{bt['msgs']:>6}{bt['input'] // 1000:>9}"
                  f"{bt['output'] // 1000:>9}{bt['cache_read'] // 1000:>9}"
                  f"{bt['cache_write'] // 1000:>9}{bt['cost_usd']:>8.2f}")
        t = report["total"]
        print("-" * 62)
        print(f"{'TOTAL':<12}{t['msgs']:>6}{t['input'] // 1000:>9}"
              f"{t['output'] // 1000:>9}{t['cache_read'] // 1000:>9}"
              f"{t['cache_write'] // 1000:>9}{t['cost_usd']:>8.2f}")
        print(f"\n共 {len(agg)} 个有效日")


if __name__ == "__main__":
    main()
