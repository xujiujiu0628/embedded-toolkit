#!/usr/bin/env python3
"""
Keil 构建日志智能分析器
解析 Keil MDK 编译日志，匹配错误/警告知识库，输出结构化诊断结果。

用法:
    python keil_analyze.py <log_file> [--db <error_db.json>] [--json] [--brief]

输出:
    JSON 格式的诊断结果，包含每个错误/警告的：
    - 原始信息（文件、行号、错误码、消息）
    - 知识库匹配（中文解释、原因、修复建议）
    - 严重级别
"""

import json
import re
import sys
import os
from pathlib import Path
from collections import defaultdict

# legacy/keil/ → parents[2] = scripts/ (wb_common 所在)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wb_common import TOOLKIT_ROOT  # noqa: E402


def load_error_db(db_path: str) -> dict:
    """加载错误知识库 JSON 文件"""
    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"errors": [], "warnings": []}


def normalize_code(raw_code: str) -> str:
    """去除 ARMCC 错误码前缀和后缀变体，统一为纯数字/字母码。
    如 #111-D -> 111, L6218E -> L6218, #177-D -> 177"""
    # 去掉前缀 #
    code = raw_code.lstrip('#')
    # 去掉后缀字母变体 (如 -D, E, W, U)
    code = re.sub(r'[-\s]*[A-Za-z]+$', '', code)
    return code.upper()


def parse_compiler_message(line: str) -> dict | None:
    """解析 ARMCC 编译器输出行，提取结构化信息。"""
    # 匹配模式: path(line): level: #code[-variant]: message
    pattern = r'^(.+?)\((\d+)\):\s*(warning|error):\s*#(\d+(?:-\w+)?)[:\s]+(.+)'
    m = re.match(pattern, line, re.IGNORECASE)
    if not m:
        return None

    raw_code = m.group(4)
    return {
        "file": m.group(1).strip(),
        "line": int(m.group(2)),
        "level": m.group(3).lower(),
        "code": normalize_code(raw_code),
        "code_raw": f"#{raw_code}",
        "message": m.group(5).strip(),
        "raw": line.strip()
    }


def parse_linker_error(line: str) -> dict | None:
    """
    解析 ARM 链接器错误行。
    格式: Error: L6218E: Undefined symbol foo (referred from main.o).
           Warning: L6314W: No section matched ...
    """
    pattern = r'(Error|Warning):\s*(L\d+[EWU]?):\s*(.+)'
    m = re.match(pattern, line, re.IGNORECASE)
    if not m:
        return None

    level = "error" if m.group(1).lower() == "error" else "warning"
    code = m.group(2)
    return {
        "file": None,
        "line": None,
        "level": level,
        "code": code,
        "message": m.group(3).strip(),
        "raw": line.strip()
    }


def parse_general_error(line: str) -> dict | None:
    """
    解析其他常见错误格式。
    格式: *** error 65: access violation ...
           *** TOOLS.INI: TOOLCHAIN NOT INSTALLED ...
           No Algorithm found for ...
    """
    # UV4 general error
    m = re.match(r'\*\*\*\s*(error\s+\d+):?\s*(.+)', line, re.IGNORECASE)
    if m:
        code = "error_" + re.sub(r'\s+', '_', m.group(1).strip().lower())
        return {
            "file": None,
            "line": None,
            "level": "error",
            "code": code,
            "message": m.group(2).strip(),
            "raw": line.strip()
        }

    # No Algorithm found
    m = re.match(r'(No Algorithm found for.+)', line)
    if m:
        return {
            "file": None,
            "line": None,
            "level": "error",
            "code": "no_algorithm",
            "message": m.group(1).strip(),
            "raw": line.strip()
        }

    # TOOLS.INI error
    m = re.match(r'\*\*\*\s*(TOOLS\.INI:.+)', line)
    if m:
        return {
            "file": None,
            "line": None,
            "level": "error",
            "code": "tools_ini",
            "message": m.group(1).strip(),
            "raw": line.strip()
        }

    # ERRORLEVEL line
    m = re.match(r'.*ERRORLEVEL\s+(\d+)', line)
    if m:
        return {
            "file": None,
            "line": None,
            "level": "error",
            "code": f"uv4_{m.group(1)}",
            "message": f"UV4 返回 ERRORLEVEL {m.group(1)}",
            "raw": line.strip()
        }

    return None


def match_against_db(entry: dict, db: dict) -> dict | None:
    """在知识库中按错误码匹配条目（跨 errors/warnings 搜索，因为 ARMCC 可能
    对同一错误码在不同设置下输出不同的 level）"""
    match_entry_code = normalize_code(entry["code"])
    for category_name in ("errors", "warnings"):
        for item in db.get(category_name, []):
            if normalize_code(item["code"]) == match_entry_code:
                return item
    return None


def parse_log(log_path: str) -> list[dict]:
    """
    解析完整的 Keil 构建日志文件，返回所有诊断条目列表。
    """
    if not os.path.exists(log_path):
        return [{"level": "error", "code": "INTERNAL",
                 "message": f"日志文件不存在: {log_path}", "file": None, "line": None,
                 "raw": "", "matched": False}]

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 尝试各解析器
        entry = parse_compiler_message(line)
        if not entry:
            entry = parse_linker_error(line)
        if not entry:
            entry = parse_general_error(line)

        if entry:
            entries.append(entry)

    return entries


def analyze(log_path: str, db_path: str | None = None) -> dict:
    """
    完整分析流程：解析日志 → 匹配知识库 → 生成报告
    """
    # 默认知识库路径
    if db_path is None:
        db_path = os.path.join(TOOLKIT_ROOT, "data", "keil-error-db.json")

    db = load_error_db(db_path)
    entries = parse_log(log_path)

    # 匹配知识库
    matched_count = 0
    for entry in entries:
        matched = match_against_db(entry, db)
        entry["matched"] = matched is not None
        if matched:
            matched_count += 1
            entry["diagnosis"] = {
                "meaning": matched.get("meaning", ""),
                "causes": matched.get("causes", []),
                "fixes": matched.get("fixes", []),
                "severity": matched.get("severity", "unknown"),
                "category": matched.get("category", "unknown"),
                "keil_specific": matched.get("keil_specific", False)
            }
        else:
            entry["diagnosis"] = {
                "meaning": "未在知识库中找到，需 AI 分析",
                "causes": [],
                "fixes": [],
                "severity": "warn" if entry["level"] == "warning" else "critical",
                "category": "unknown",
                "keil_specific": False
            }

    # 统计
    errors = [e for e in entries if e["level"] == "error"]
    warnings = [e for e in entries if e["level"] == "warning"]
    unmatched = [e for e in entries if not e["matched"]]

    # 构建结果
    result = {
        "status": "ok" if len(errors) == 0 else "error",
        "summary": {
            "total_entries": len(entries),
            "errors": len(errors),
            "warnings": len(warnings),
            "matched": matched_count,
            "unmatched": len(unmatched),
            "needs_ai_analysis": len(unmatched) > 0
        },
        "by_severity": {
            "critical": len([e for e in entries if e.get("diagnosis", {}).get("severity") == "critical"]),
            "warn": len([e for e in entries if e.get("diagnosis", {}).get("severity") == "warn"]),
            "info": len([e for e in entries if e.get("diagnosis", {}).get("severity") == "info"]),
        },
        "by_category": defaultdict(int),
        "errors": errors,
        "warnings": warnings,
        "unmatched_entries": unmatched,
        "_meta": {
            "log_file": log_path,
            "db_file": db_path,
            "db_version": db.get("_meta", {}).get("version", "unknown"),
            "analyzer_version": "1.0.0"
        }
    }

    # 填充分类统计
    for e in entries:
        cat = e.get("diagnosis", {}).get("category", "unknown")
        result["by_category"][cat] += 1

    return result


def format_plain_text(result: dict) -> str:
    """将分析结果格式化为人类可读的文本"""
    s = result["summary"]
    lines = []
    lines.append("=" * 60)
    lines.append(f"Keil 构建日志分析报告")
    lines.append(f"日志文件: {result['_meta']['log_file']}")
    lines.append(f"知识库版本: {result['_meta']['db_version']}")
    lines.append("=" * 60)
    lines.append(f"\n总览: {s['errors']} 个错误, {s['warnings']} 个警告 "
                 f"(已匹配 {s['matched']}/{s['total_entries']}, "
                 f"需 AI 分析 {s['unmatched']} 个)")
    lines.append(f"严重程度: "
                 f"Critical={result['by_severity']['critical']}, "
                 f"Warn={result['by_severity']['warn']}, "
                 f"Info={result['by_severity']['info']}")

    # 打印每个条目
    all_entries = result["errors"] + result["warnings"]
    for i, entry in enumerate(all_entries, 1):
        d = entry.get("diagnosis", {})
        level_icon = "ERROR" if entry["level"] == "error" else "WARN"
        location = f"{entry['file']}:{entry['line']}" if entry.get("file") else "(无位置)"

        lines.append(f"\n{'─' * 50}")
        lines.append(f"[{i}] {level_icon} {entry['code']} [{location}]")
        lines.append(f"    {entry['message']}")
        if d.get("meaning"):
            lines.append(f"    含义: {d['meaning']}")
        if d.get("causes"):
            for cause in d["causes"]:
                lines.append(f"    可能原因: {cause}")
        if d.get("fixes"):
            for fix in d["fixes"]:
                lines.append(f"    修复建议: {fix}")
        if d.get("severity"):
            lines.append(f"    严重度: {d['severity']} | 分类: {d.get('category', '?')}")

    lines.append(f"\n{'═' * 60}")
    if s["needs_ai_analysis"]:
        lines.append(f"[!] {s['unmatched']} entries unmatched in knowledge base, suggest AI analysis.")
    else:
        lines.append(f"[OK] All entries matched in knowledge base.")
    lines.append("═" * 60)
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Keil 构建日志智能分析器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python keil_analyze.py build.log
  python keil_analyze.py build.log --json | jq .summary
  python keil_analyze.py build.log --db custom-errors.json --brief
        """
    )
    parser.add_argument("log_file", help="Keil 构建日志文件路径")
    parser.add_argument("--db", help="自定义错误知识库 JSON 文件路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--brief", action="store_true", help="仅输出总览摘要")

    args = parser.parse_args()

    try:
        result = analyze(args.log_file, args.db)
    except Exception as e:
        error_result = {
            "status": "error",
            "summary": {"total_entries": 0, "errors": 1, "warnings": 0},
            "errors": [{"level": "error", "code": "ANALYZER_FAULT",
                        "message": str(e), "file": None, "line": None, "raw": "",
                        "matched": False}],
            "warnings": [],
            "unmatched_entries": [],
            "_meta": {"log_file": args.log_file}
        }
        if args.json:
            print(json.dumps(error_result, ensure_ascii=False, indent=2,
                            default=lambda x: dict(x) if isinstance(x, defaultdict) else str(x)))
        else:
            print(f"分析器错误: {e}")
        sys.exit(1)

    # 将 defaultdict 转为普通 dict (JSON 序列化)
    result["by_category"] = dict(result["by_category"])

    if args.json:
        if args.brief:
            brief = {
                "status": result["status"],
                "summary": result["summary"],
                "by_severity": result["by_severity"],
                "_meta": result["_meta"]
            }
            print(json.dumps(brief, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2,
                            default=lambda x: dict(x) if isinstance(x, defaultdict) else str(x)))
    else:
        if args.brief:
            s = result["summary"]
            print(f"Errors: {s['errors']} | Warnings: {s['warnings']} | "
                  f"Matched: {s['matched']}/{s['total_entries']} | "
                  f"Needs AI: {s['unmatched']}")
        else:
            print(format_plain_text(result))


if __name__ == "__main__":
    main()
