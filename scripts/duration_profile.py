#!/usr/bin/env python3
"""verify step-level 时长画像 (F-050, 2026-09-02 方案四-4).

设计意图: "分层"前先做时长画像 —— 不拍脑袋切层, 用数据驱动.
  - 读 .workbench/state/checkpoints.jsonl (F-047 落盘) + 读 result.steps.duration_sec
  - 聚合每个 step 的 min / p50 / p95 / max / 占比
  - 输出: 人类可读报告 + --json 机器可读
  - 当前限制: 仓内无真机 (gcc_path 占位), checkpoints.jsonl 跑不起来, 数据靠 mock
    演示 —— 真机一通, 跑 N 次 verify 后数据自动真实化

用法:
  python scripts/duration_profile.py [--project 工程根] [--json]
  python scripts/duration_profile.py --demo    # 用 mock 数据演示 (无真实 checkpoints)
"""
import argparse
import json
import os
import sys
import statistics


# 已知 step 名 (与 verify.py result.steps 对应)
STEP_KEYS = ("build", "analyze", "flash", "capture", "hardfault",
             "physical_gate")


def _read_checkpoints(workspace: str) -> list[dict]:
    """读 .workbench/state/checkpoints.jsonl, 每行一个 checkpoint 字典.

    缺失/损坏 → 返回空 list (调用方决定是 mock 还是空报告).
    """
    path = os.path.join(workspace, ".workbench", "state", "checkpoints.jsonl")
    out = []
    if not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _collect_step_durations(checkpoints: list[dict], result_lookup=None) -> dict:
    """聚合每个 step 的耗时列表 (秒).

    来源:
      ① checkpoints.jsonl 每条 entry 的 step_keys (F-047 字段) → 已知跑过
      ② result_lookup 是可选 callback(checkpoint) -> result dict, 用于读
         steps[step].duration_sec (F-050 新加). 缺这个 callback → 用 entry
         自带的 duration_sec 当 fallback (整流程耗时, 不是 step 级).
    """
    by_step: dict[str, list[float]] = {k: [] for k in STEP_KEYS}
    if not checkpoints:
        return by_step
    for cp in checkpoints:
        step_keys = cp.get("step_keys", []) or []
        for step in step_keys:
            if step not in by_step:
                continue
            d = None
            if result_lookup is not None:
                result = result_lookup(cp)
                if isinstance(result, dict):
                    s = result.get("steps", {}).get(step, {})
                    if isinstance(s, dict) and "duration_sec" in s:
                        d = float(s["duration_sec"])
            if d is None:
                # 兜底: 用整流程 duration_sec 顶替 (粗但不崩)
                d = float(cp.get("duration_sec", 0) or 0)
            if d > 0:
                by_step[step].append(d)
    return by_step


def _percentile(xs: list[float], p: float) -> float:
    """线性插值百分位 (不依赖 numpy)."""
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _summarize(by_step: dict) -> dict:
    """每个 step 出 min/p50/p95/max/count/sum."""
    out = {}
    for step, xs in by_step.items():
        if not xs:
            out[step] = {"count": 0, "min": 0.0, "p50": 0.0,
                         "p95": 0.0, "max": 0.0, "sum": 0.0}
            continue
        out[step] = {
            "count": len(xs),
            "min": round(min(xs), 2),
            "p50": round(_percentile(xs, 0.5), 2),
            "p95": round(_percentile(xs, 0.95), 2),
            "max": round(max(xs), 2),
            "sum": round(sum(xs), 2),
        }
    return out


def _format_text(stats: dict) -> str:
    """人读报告: 每 step 一行, 含 count / p50 / p95 / max / 占比."""
    if not any(s.get("count", 0) > 0 for s in stats.values()):
        return ("duration_profile: 无数据 (checkpoints.jsonl 缺失或全空; "
                "用 --demo 跑示意数据, 或先跑 N 次真 verify 累积数据)")
    total_sum = sum(s.get("sum", 0) for s in stats.values())
    lines = [f"duration_profile: 每 step 时长 (合计 {total_sum:.1f}s)"]
    for step, s in stats.items():
        if s.get("count", 0) == 0:
            continue
        pct = (s["sum"] / total_sum * 100) if total_sum else 0
        lines.append(
            f"  {step:<14} n={s['count']:<3} "
            f"min={s['min']:>5.1f}s  p50={s['p50']:>5.1f}s  "
            f"p95={s['p95']:>5.1f}s  max={s['max']:>5.1f}s  "
            f"sum={s['sum']:>6.1f}s  ({pct:>4.1f}%)")
    return "\n".join(lines)


def _demo_stats() -> dict:
    """mock 数据: 模拟一次真 verify 的典型耗时分布 (示意, 非真值).

    透明标: 这些数字不代表真机表现, 只能用来检验工具自身.
    """
    return {
        "build": {"count": 5, "min": 2.1, "p50": 3.4, "p95": 5.2,
                  "max": 5.8, "sum": 16.5},
        "analyze": {"count": 5, "min": 0.1, "p50": 0.2, "p95": 0.3,
                    "max": 0.4, "sum": 1.0},
        "flash": {"count": 5, "min": 0.8, "p50": 1.1, "p95": 1.6,
                  "max": 2.0, "sum": 5.5},
        "capture": {"count": 5, "min": 8.0, "p50": 10.5, "p95": 14.0,
                    "max": 15.2, "sum": 52.0},
        "physical_gate": {"count": 5, "min": 0.3, "p50": 0.5, "p95": 0.8,
                          "max": 1.0, "sum": 2.5},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="verify step-level 时长画像 (F-050, 方案四-4)")
    parser.add_argument("--project", default=None,
                        help="工程根 (默认 cwd 向上发现)")
    parser.add_argument("--demo", action="store_true",
                        help="用 mock 数据演示 (无 checkpoints.jsonl 时)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.demo:
        stats = _demo_stats()
        source = "demo (mock 数据, 非真机表现; 仅用于工具自检)"
    else:
        ws = args.project or os.getcwd()
        # 与 wb_common.find_project_root 保持兼容, 简版
        while ws and not os.path.isdir(os.path.join(ws, ".workbench")):
            parent = os.path.dirname(ws)
            if parent == ws:
                ws = None
                break
            ws = parent
        if not ws:
            print("错误: 未找到工程根 (含 .workbench/)", file=sys.stderr)
            return 1
        cps = _read_checkpoints(ws)
        by_step = _collect_step_durations(cps, result_lookup=None)
        stats = _summarize(by_step)
        source = f"real (checkpoints.jsonl, {len(cps)} 条 entry)"

    if args.json:
        out = {"tool": "duration_profile", "source": source, "stats": stats}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_format_text(stats))
        print(f"\n[source: {source}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
