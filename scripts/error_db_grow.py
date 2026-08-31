#!/usr/bin/env python3
"""
知识库自动增长 — 五重门控检查通过后写入 keil-error-db.json
用法:
    python error_db_grow.py --event-id <event_id> --unmatched '<json>' --diagnosis '<json>'
    python error_db_grow.py --check <event_id>    # 仅检查门控
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

from wb_common import TOOLKIT_ROOT, find_project_root

ERROR_DB_PATH = os.path.join(TOOLKIT_ROOT, "data", "keil-error-db.json")


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


def _session_cache_path() -> str:
    """会话级修复缓存路径 — per-project（跟随工程 feedback 目录），
    拆分前位于 .embeddedskills/feedback/session_fix_cache.json。"""
    return os.path.join(_feedback_dir(), "session_fix_cache.json")


def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def load_event(event_id: str) -> dict | None:
    """加载事件详情 JSON (损坏 → None + 留痕, 门控按 not_found 走)"""
    event_path = os.path.join(_feedback_dir(), "events", f"{event_id}.json")
    if not os.path.exists(event_path):
        return None
    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        print(f"Warning: 事件文件不可解析 {event_path}: {e}", file=sys.stderr)
        return None


def check_gates(event_id: str) -> dict:
    """
    五重门控检查:
    ① keil_analyze 报告 unmatched > 0  → 看事件是否有 error_code
    ② Drafter 给出诊断 + 修复方案       → drafter_diagnosis + drafter_fix 非空
    ③ Reviewer verdict 通过             → review_verdict in ("approved", "approved_with_changes")
    ④ Keil 编译 0 errors, 0 warnings    → build_result == "0e0w"
    ⑤ verify.py 验证 pass              → verify_result == "pass"
    """
    event = load_event(event_id)
    if event is None:
        return {"all_passed": False, "failed_at": "event_not_found", "details": f"Event {event_id} not found"}

    gates = []

    # Gate 1: has error_code (意味着 keil_analyze 报了 unmatched)
    g1 = bool(event.get("error_code"))
    gates.append({"gate": 1, "name": "unmatched_error", "passed": g1,
                  "detail": event.get("error_code", "no error_code")})

    # Gate 2: Drafter 给出了诊断和修复
    g2 = bool(event.get("drafter_diagnosis")) and bool(event.get("drafter_fix"))
    gates.append({"gate": 2, "name": "drafter_diagnosis_and_fix", "passed": g2,
                  "detail": f"diagnosis_len={len(event.get('drafter_diagnosis',''))}, fix_len={len(event.get('drafter_fix',''))}"})

    # Gate 3: Reviewer 通过
    verdict = event.get("review_verdict", "")
    g3 = verdict in ("approved", "approved_with_changes")
    gates.append({"gate": 3, "name": "reviewer_approved", "passed": g3,
                  "detail": f"verdict={verdict}"})

    # Gate 4: 编译 0e0w
    build = event.get("build_result", "")
    g4 = build == "0e0w"
    gates.append({"gate": 4, "name": "build_clean", "passed": g4,
                  "detail": f"build_result={build}"})

    # Gate 5: 运行时验证通过
    g5 = event.get("verify_result") == "pass"
    gates.append({"gate": 5, "name": "verify_pass", "passed": g5,
                  "detail": f"verify_result={event.get('verify_result','')}"})

    all_passed = g1 and g2 and g3 and g4 and g5
    failed_at = None
    if not all_passed:
        for g in gates:
            if not g["passed"]:
                failed_at = g["name"]
                break

    return {
        "all_passed": all_passed,
        "failed_at": failed_at,
        "gates": gates,
    }


def generalization_score(unmatched_entry: dict, diagnosis: dict) -> tuple:
    """
    泛化守卫 — 静态相似度检测，评估一条修复方案的可复用性。

    检测 5 类"平台/会话特有"痕迹: 绝对路径、具体变量名、硬编码地址、
    板级专有符号、字面时序常量。全部不命中 → 泛化率 1.0 (可入库);
    命中越多 → 泛化率越低, < 0.6 时归入 session_fix_cache.json,
    不污染全局 keil-error-db.json。

    Returns:
        (score: float 0.0-1.0, hits: list[str] 命中的检测项名)
    """
    text = json.dumps({**unmatched_entry, **diagnosis}, ensure_ascii=False)
    checks = {
        "absolute_path": r"[A-Za-z]:[\\/]|(^|[^A-Za-z])/[\w.\/-]+/",
        "concrete_variables": r"\b(i|j|k|idx|tmp|temp|ptr|buf|data)\b",
        "hardcoded_address": r"0[xX][0-9a-fA-F]{4,}",
        "board_specific": r"\b(GPIOC|GPIOB|RCC_|TIM2|I2C[12]|HAL_Delay)\b",
        "literal_timing": r"\b\d{3,4}\s*(ms|us|Hz)\b",
    }
    hits = [name for name, pattern in checks.items() if re.search(pattern, text)]
    score = (len(checks) - len(hits)) / len(checks)
    return score, hits


def _cache_entry(event_id: str, new_entry: dict, score: float, hits: list) -> dict:
    """泛化率不足 → 写入会话级缓存（per-project），等待人工 Reviewer 确认后晋升

    F-020: 缓存损坏 → 隔离到 .corrupt 保留现场后重建 (待人审条目孤悬可手工
    恢复); 旧实现"损坏当空读入→覆写"会把待审条目无声清空。"""
    cache_path = _session_cache_path()
    cache = {"_meta": {}, "entries": []}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict) or not isinstance(loaded.get("entries", []), list):
                raise ValueError("顶层须为含 entries 数组的对象")
            cache = loaded
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as e:
            corrupt = cache_path + ".corrupt"
            try:
                os.replace(cache_path, corrupt)
                print(f"Warning: session_fix_cache.json 损坏, 原文件移至 "
                      f"{corrupt}: {e}", file=sys.stderr)
            except OSError:
                print(f"Warning: session_fix_cache.json 损坏且隔离失败: {e}",
                      file=sys.stderr)
            cache = {"_meta": {}, "entries": []}

    entry = dict(new_entry)
    entry["generalization_score"] = round(score, 3)
    entry["checks_hit"] = hits
    entry["event_id"] = event_id
    entry["added_at"] = now_iso()

    # 检查不重复 (按 code)
    existing_codes = {e.get("code", "") for e in cache.get("entries", [])}
    if entry["code"] and entry["code"] in existing_codes:
        return {"status": "already_cached", "message": f"Code {entry['code']} already in session cache"}

    cache.setdefault("entries", []).append(entry)
    cache.setdefault("_meta", {})["last_updated"] = now_iso()

    with open(cache_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    return {
        "status": "cached",
        "message": f"Generalization score {score:.2f} <= 0.6 — cached to session_fix_cache.json (needs human reviewer)",
        "entry": entry,
    }


def bump_version(version: str) -> str:
    """版本号自增 patch: '1.0.0' → '1.0.1'"""
    parts = version.split(".")
    if len(parts) == 3:
        try:
            parts[2] = str(int(parts[2]) + 1)
            return ".".join(parts)
        except ValueError:
            pass
    return version


def grow(event_id: str, unmatched_entry: dict, diagnosis: dict) -> dict:
    """
    五重门控全过 → 写入 keil-error-db.json

    Args:
        event_id: 事件 ID (用于门控检查)
        unmatched_entry: keil_analyze 中未匹配的错误条目
        diagnosis: Drafter 的诊断结果

    Returns:
        {"status": "ok|blocked", "message": str, "entry": {...}}
    """
    # 先检查门控
    gate_result = check_gates(event_id)
    if not gate_result["all_passed"]:
        return {
            "status": "blocked",
            "message": f"Gating failed at: {gate_result['failed_at']}",
            "gates": gate_result["gates"],
        }

    # 加载事件确认 build 和 verify
    event = load_event(event_id)

    # 泛化守卫: 静态相似度检测, 泛化率 <= 0.6 (命中 >= 2 项) 不入全局库
    score, hits = generalization_score(unmatched_entry, diagnosis)
    if score <= 0.6:
        provisional = {
            "code": unmatched_entry.get("code", ""),
            "meaning": diagnosis.get("meaning", ""),
            "causes": diagnosis.get("causes", []),
            "fixes": diagnosis.get("fixes", []),
            "severity": diagnosis.get("severity", "warn"),
            "category": diagnosis.get("category", "unknown"),
            "keil_specific": diagnosis.get("keil_specific", True),
            "source": "ai_generated",
            "reviewed_by": "drafter_reviewer",
            "added_at": now_iso(),
            "verified_build": True,
            "verified_runtime": True,
            "type": unmatched_entry.get("type", "error"),
            "pattern": unmatched_entry.get("pattern", unmatched_entry.get("code", "")),
        }
        return _cache_entry(event_id, provisional, score, hits)

    # 构造新条目
    new_entry = {
        "code": unmatched_entry.get("code", ""),
        "type": unmatched_entry.get("type", "error"),
        "pattern": unmatched_entry.get("pattern", unmatched_entry.get("code", "")),
        "meaning": diagnosis.get("meaning", ""),
        "causes": diagnosis.get("causes", []),
        "fixes": diagnosis.get("fixes", []),
        "severity": diagnosis.get("severity", "warn"),
        "category": diagnosis.get("category", "unknown"),
        "keil_specific": diagnosis.get("keil_specific", True),
        "source": "ai_generated",
        "reviewed_by": "drafter_reviewer",
        "added_at": now_iso(),
        "verified_build": True,
        "verified_runtime": True,
    }

    # 加载数据库
    if not os.path.exists(ERROR_DB_PATH):
        return {"status": "error", "message": f"keil-error-db.json not found at {ERROR_DB_PATH}"}

    # F-020: 知识库损坏 → 明确报错拒绝写入 (旧实现裸 traceback; 任何
    # "当空读入继续写"的容错都会把整库清空, 这里数据安全优先)
    try:
        with open(ERROR_DB_PATH, 'r', encoding='utf-8') as f:
            db = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"status": "error",
                "message": f"keil-error-db.json 不可解析, 拒绝写入以免清空知识库: {e}"}
    if not isinstance(db, dict):
        return {"status": "error",
                "message": "keil-error-db.json 顶层须为 JSON 对象, 拒绝写入"}

    # 检查不重复
    existing_codes = {e.get("code", "") for e in db.get("errors", [])}
    if new_entry["code"] in existing_codes:
        return {
            "status": "blocked",
            "message": f"Error code {new_entry['code']} already exists in database",
        }

    # 追加
    db.setdefault("errors", []).append(new_entry)

    # 更新元数据
    meta = db.setdefault("_meta", {})
    old_version = meta.get("version", "0.0.0")
    meta["version"] = bump_version(old_version)
    meta["ai_generated_count"] = meta.get("ai_generated_count", 0) + 1
    meta["last_updated"] = now_iso()

    # 写入
    with open(ERROR_DB_PATH, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "message": f"Added error {new_entry['code']} to keil-error-db.json (v{meta['version']})",
        "entry": new_entry,
    }


def main():
    parser = argparse.ArgumentParser(description="知识库自动增长")
    parser.add_argument("--event-id", required=True, help="事件 ID 用于门控检查")
    parser.add_argument("--check", action="store_true", help="仅检查门控状态")
    parser.add_argument("--unmatched", help="JSON 字符串: 未匹配的错误条目")
    parser.add_argument("--diagnosis", help="JSON 字符串: Drafter 的诊断")
    args = parser.parse_args()

    if args.check:
        result = check_gates(args.event_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not args.unmatched or not args.diagnosis:
        print(json.dumps({"status": "error", "message": "Both --unmatched and --diagnosis required for grow mode"}))
        sys.exit(1)

    try:
        unmatched = json.loads(args.unmatched)
        diagnosis = json.loads(args.diagnosis)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"JSON parse error: {e}"}))
        sys.exit(1)

    result = grow(args.event_id, unmatched, diagnosis)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
