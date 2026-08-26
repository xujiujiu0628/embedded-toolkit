#!/usr/bin/env python3
"""
反馈数据库 — 事件记录、统计查询、相似搜索
用法:
    python feedback_db.py --log '<json_event>'     # 记录事件
    python feedback_db.py --stats <pipeline>       # 查询统计
    python feedback_db.py --similar <error_code>   # 搜索相似事件
    python feedback_db.py --calibrate               # 导出校准数据

Note: feedback_db.json and calibration.json use load-modify-save cycles without
file locking. This is safe for single-session CLI usage (serialized via subprocess
calls). If concurrent writers are added, use a write-to-temp + os.replace() pattern.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta

from wb_common import find_project_root


def _project_feedback_dir():
    """工程 feedback 数据目录: 从 cwd 向上找工程根, 在
    .workbench/feedback 或 .embeddedskills/feedback 中取存在的那个。"""
    root = find_project_root(os.getcwd())
    if not root:
        return None
    for d in (".workbench/feedback", ".embeddedskills/feedback"):
        p = os.path.join(root, d)
        if os.path.isdir(p):
            return p
    return None


def _feedback_dir() -> str:
    """解析工程 feedback 数据目录; 未发现工程时给出明确错误。"""
    d = _project_feedback_dir()
    if not d:
        print("Error: 未找到工程根 (cwd 向上需有 .workbench/config.json 或 .embeddedskills/config.json)", file=sys.stderr)
        sys.exit(1)
    return d


@dataclass
class FeedbackEvent:
    """一次诊断事件的完整记录"""
    id: str
    pipeline: str                  # "build_fix" | "hardfault" | "code_gen" | "verify" | "fresh_check"
    timestamp: str                 # ISO 8601
    error_code: str | None = None
    fault_type: str | None = None
    module: str | None = None
    # Drafter 侧
    drafter_diagnosis: str = ""
    drafter_fix: str = ""
    # Reviewer 侧
    review_verdict: str = ""       # "approved" | "approved_with_changes" | "rejected"
    issues_found: list[str] = field(default_factory=list)
    must_fix_count: int = 0
    rounds: int = 0
    # 验证侧
    build_result: str = ""         # "0e0w" 或具体错误
    verify_result: str = ""        # "pass" | "fail"
    # 最终
    outcome: str = ""              # "fixed" | "still_broken" | "false_positive"


def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def load_feedback_db() -> dict:
    path = os.path.join(_feedback_dir(), "feedback_db.json")
    if not os.path.exists(path):
        return {"total_events": 0, "by_pipeline": {"build_fix": 0, "hardfault": 0, "code_gen": 0}, "events": []}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_feedback_db(data: dict) -> None:
    with open(os.path.join(_feedback_dir(), "feedback_db.json"), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_calibration() -> dict:
    path = os.path.join(_feedback_dir(), "calibration.json")
    if not os.path.exists(path):
        return {"build_fix": {}, "hardfault": {}, "code_gen": {}}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_calibration(data: dict) -> None:
    with open(os.path.join(_feedback_dir(), "calibration.json"), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_event_id(pipeline: str, timestamp: str | None = None) -> str:
    """生成唯一事件 ID: bf_20260720_143000"""
    prefix = {"build_fix": "bf", "hardfault": "hf", "code_gen": "cg"}.get(pipeline, "ev")
    if timestamp is None:
        timestamp = now_iso()
    ts_clean = timestamp.replace(':', '').replace('-', '').replace('T', '_')
    return f"{prefix}_{ts_clean}"


def log_event(event_data: dict | FeedbackEvent) -> str:
    """记录诊断事件 → 写入 events/ + 更新主索引 + 更新校准"""
    fb_dir = _feedback_dir()
    events_dir = os.path.join(fb_dir, "events")
    os.makedirs(events_dir, exist_ok=True)

    # Accept FeedbackEvent dataclass as the canonical shape
    if isinstance(event_data, FeedbackEvent):
        event_dict = asdict(event_data)
    else:
        event_dict = event_data

    # Validate pipeline
    pipeline = event_dict.get("pipeline", "build_fix")
    valid_pipelines = {"build_fix", "hardfault", "code_gen", "verify",
                       "fresh_check"}   # 2026-08-26: 无上下文对抗审核流水线
    if pipeline not in valid_pipelines:
        print(f"Warning: unknown pipeline '{pipeline}'", file=sys.stderr)

    # Validate outcome
    outcome = event_dict.get("outcome", "")
    valid_outcomes = {"fixed", "still_broken", "false_positive", "pass", "fail",
                      "reported", ""}   # reported: fresh_check 审核已交付
    if outcome not in valid_outcomes:
        print(f"Warning: unknown outcome '{outcome}'", file=sys.stderr)

    # Compute timestamp once for consistency
    if not event_dict.get("timestamp"):
        ts = now_iso()
        event_dict["timestamp"] = ts
    else:
        ts = event_dict["timestamp"]

    if not event_dict.get("id"):
        event_dict["id"] = make_event_id(pipeline, ts)

    eid = event_dict["id"]

    # 写入事件详情
    event_path = os.path.join(events_dir, f"{eid}.json")
    with open(event_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(event_dict, f, ensure_ascii=False, indent=2)

    # 更新主索引
    db = load_feedback_db()
    db["total_events"] += 1
    if pipeline in db["by_pipeline"]:
        db["by_pipeline"][pipeline] += 1
    db["events"].append({
        "id": eid,
        "pipeline": pipeline,
        "timestamp": event_dict["timestamp"],
        "outcome": event_dict.get("outcome", ""),
        "error_code": event_dict.get("error_code"),
        "fault_type": event_dict.get("fault_type"),
        "module": event_dict.get("module"),
    })
    save_feedback_db(db)

    # 更新校准
    update_calibration(event_dict)

    return eid


def update_calibration(event_dict: dict) -> None:
    """根据事件结果更新 calibration.json"""
    cal = load_calibration()
    pipeline = event_dict.get("pipeline", "build_fix")
    outcome = event_dict.get("outcome", "")

    if pipeline not in cal:
        cal[pipeline] = {}

    # 确定校准 key
    key = None
    if pipeline == "build_fix" and event_dict.get("error_code"):
        key = event_dict["error_code"]
    elif pipeline == "hardfault" and event_dict.get("fault_type"):
        key = event_dict["fault_type"]
    elif pipeline == "code_gen" and event_dict.get("module"):
        key = event_dict["module"]

    if key is None:
        return

    if key not in cal[pipeline]:
        cal[pipeline][key] = {
            "attempts": 0, "fixed": 0, "still_broken": 0, "false_positive": 0,
            "avg_rounds": 0.0, "last_seen": event_dict.get("timestamp", "")
        }

    entry = cal[pipeline][key]
    entry["attempts"] += 1
    if outcome == "fixed":
        entry["fixed"] += 1
    elif outcome == "still_broken":
        entry["still_broken"] += 1
    elif outcome == "false_positive":
        entry["false_positive"] += 1

    # 更新平均轮数
    rounds = event_dict.get("rounds", 1)
    entry["avg_rounds"] = round(
        (entry["avg_rounds"] * (entry["attempts"] - 1) + rounds) / entry["attempts"], 2
    )
    entry["last_seen"] = event_dict.get("timestamp", "")

    save_calibration(cal)


def get_pipeline_stats(pipeline: str) -> dict:
    """返回流水线的聚合统计"""
    cal = load_calibration()
    pipe_data = cal.get(pipeline, {})

    total_attempts = sum(v["attempts"] for v in pipe_data.values())
    total_fixed = sum(v["fixed"] for v in pipe_data.values())
    success_rate = round(total_fixed / total_attempts * 100, 1) if total_attempts > 0 else 0

    return {
        "pipeline": pipeline,
        "total_events": total_attempts,
        "fixed": total_fixed,
        "success_rate_pct": success_rate,
        "by_key": pipe_data,
    }


def find_similar(error_code: str) -> list[dict]:
    """搜索历史中相同 error_code 的事件，按成功率排序"""
    db = load_feedback_db()

    results = []
    for event_summary in db.get("events", []):
        if event_summary.get("error_code") == error_code:
            eid = event_summary["id"]
            event_path = os.path.join(_feedback_dir(), "events", f"{eid}.json")
            if os.path.exists(event_path):
                with open(event_path, 'r', encoding='utf-8') as f:
                    full = json.load(f)
                results.append({
                    "id": eid,
                    "timestamp": full.get("timestamp", ""),
                    "outcome": full.get("outcome", ""),
                    "drafter_fix": full.get("drafter_fix", ""),
                    "review_verdict": full.get("review_verdict", ""),
                    "rounds": full.get("rounds", 0),
                })

    # 按 outcome 排序: fixed > still_broken > false_positive
    order = {"fixed": 0, "still_broken": 1, "false_positive": 2}
    results.sort(key=lambda r: order.get(r["outcome"], 99))
    return results


def export_calibration() -> dict:
    """导出完整校准数据"""
    return load_calibration()


def main():
    parser = argparse.ArgumentParser(description="反馈数据库")
    parser.add_argument("--log", type=str, help="JSON 字符串格式的事件记录")
    parser.add_argument("--stats", type=str, help="查询 pipeline 统计 (build_fix|hardfault|code_gen)")
    parser.add_argument("--similar", type=str, help="搜索相似事件 (按 error_code)")
    parser.add_argument("--calibrate", action="store_true", help="导出校准数据")
    args = parser.parse_args()

    if args.log:
        try:
            event = json.loads(args.log)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"JSON parse error: {e}"}))
            sys.exit(1)
        eid = log_event(event)
        print(json.dumps({"status": "ok", "event_id": eid}, ensure_ascii=False))
    elif args.stats:
        stats = get_pipeline_stats(args.stats)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.similar:
        similar = find_similar(args.similar)
        print(json.dumps(similar, ensure_ascii=False, indent=2))
    elif args.calibrate:
        cal = export_calibration()
        print(json.dumps(cal, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
