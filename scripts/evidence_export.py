r"""evidence export (F-151, 总工单 v2 N-4) — verify 结果/发布记录 → job summary。

把 verify --json 或发布记录渲染成 Markdown 摘要, 写入 GITHUB_STEP_SUMMARY
(CI 测试页直接可读); 环境变量不在场时回落 --out 文件 (本地/非 CI 场景)。
`if: always()` 安全: 输入缺失/非法只退出码报错, 不抛 traceback (CI 摘要
步骤在失败运行里也执行, 不能让它把绿变红)。

脱敏纪律 (统一走 redact()): 摘要**不带本机绝对路径** (盘符/POSIX 家目录
一律 <path>, toolkit 根 <toolkit>), **不读也不落 machine.json 内容** —
摘要可能进公开 CI 页面, 本机路径属于 SENSITIVE_FINDINGS 口径的脱敏面。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from wb_common import TOOLKIT_ROOT

# Windows 盘符路径 / POSIX 家目录族路径 → <path>
_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|*?\]\)]*")
_UNIX_PATH_RE = re.compile(r"(?<![\w])/(?:home|Users|mnt|root|opt|srv)\b[^\s\"'<>]*")

_STATUS_MARK = {"pass": "✅ PASS", "xfail": "⏭ XFAIL (欠条)",
                "xpass": "❌ XPASS (判红)", "fail": "❌ FAIL"}


def redact(text: str, extra_roots: tuple[str, ...] = ()) -> str:
    """统一脱敏: 本机绝对路径 → <path>, toolkit 根 → <toolkit>。

    对渲染后的 Markdown 整体跑; extra_roots 为额外前缀 (workspace 根等),
    长者先替换防半截。machine.json 内容从不被读取, 也无从进入摘要。"""
    for root in sorted({r for r in extra_roots if r}, key=len, reverse=True):
        text = text.replace(root, "<toolkit>")
    text = _DRIVE_PATH_RE.sub("<path>", text)
    text = _UNIX_PATH_RE.sub("<path>", text)
    return text


def render_verify_summary(result: dict) -> str:
    """verify --json 结果 → Markdown 摘要 (四态表 + records + 失败留痕)。"""
    status = result.get("status", "unknown")
    ok = status == "ok"
    lines = [
        "## embedded-toolkit verify 报告",
        "",
        f"- **判定**: {'✅ OK' if ok else '❌ ' + status}",
        f"- **证据等级**: `{result.get('evidence', 'static')}`"
        "（仿真/静态证据不进发布门禁）",
    ]
    if result.get("elapsed_sec"):
        lines.append(f"- **实测耗时**: {result['elapsed_sec']}s")
    if result.get("post_reset"):
        lines.append(f"- **判定后复位**: {result['post_reset']}")
    if result.get("junit_xml_error"):
        lines.append(f"- ⚠️ JUnit 报告写失败: {result['junit_xml_error']}")
    if result.get("error"):
        lines.append(f"- **失败**: {result['error']}")

    verify_s = (result.get("steps") or {}).get("verify") or {}
    rows = verify_s.get("results")
    if rows is not None:
        lines += ["", "| 期望 | 判定 | 说明 |", "|---|---|---|"]
        for r in rows:
            mark = _STATUS_MARK.get(r.get("status"), r.get("status", "?"))
            detail = str(r.get("detail", "")).replace("|", "\\|")
            lines.append(f"| {r.get('id', '?')} | {mark} | {detail} |")
    records = result.get("records") or []
    if records:
        kv = ", ".join(
            f"`{k}={v}`" for rec in records
            for k, v in rec.items() if k != "id")
        lines += ["", f"- **record 提取**: {kv}"]
    captured = result.get("captured_output", "")
    if captured:
        snippet = captured[:500] + ("…" if len(captured) > 500 else "")
        lines += ["", "<details><summary>采集输出（前 500 字符）</summary>",
                  "", "```text", snippet, "```", "", "</details>"]
    return "\n".join(lines) + "\n"


def render_release_summary(record: dict) -> str:
    """发布记录 → Markdown 摘要 (tag/锚点/证据/fidelity 契约)。"""
    lines = [
        f"## 发布 {record.get('tag', '?')}",
        "",
        f"- **git_head**: `{str(record.get('git_head', ''))[:12]}`"
        f" @ `{record.get('branch', '?')}`",
        f"- **证据等级**: `{record.get('evidence', '?')}`",
    ]
    if record.get("production_approved_at"):
        lines.append(f"- **批准投产**: {record['production_approved_at']}")
    waived = record.get("xfail_waived") or []
    if waived:
        lines.append(f"- **xfail 豁免**: {', '.join(waived)}")
    boundaries = record.get("fidelity_boundaries") or []
    limitations = record.get("limitations") or []
    if boundaries:
        lines += ["", "**Fidelity 边界**:"] + \
            [f"- {b}" for b in boundaries]
    if limitations:
        lines += ["", "**已知局限**:"] + [f"- {l}" for l in limitations]
    rows = record.get("results") or []
    if rows:
        lines += ["", "| 期望 | 判定 |", "|---|---|"]
        for r in rows:
            mark = _STATUS_MARK.get(r.get("status"), r.get("status", "?"))
            lines.append(f"| {r.get('id', '?')} | {mark} |")
    signature = record.get("signature")
    if signature is not None and not signature:
        lines += ["", "_signature: 留空（签名机制登记未实现）_"]
    return "\n".join(lines) + "\n"


def write_summary(md: str, out_path: str | None = None) -> dict:
    """写摘要: GITHUB_STEP_SUMMARY 优先 (追加); env 不在场或写失败才回落
    --out (缺省 job-summary.md)。返回 {ok, written, error?}。"""
    written, errors = [], []
    gh = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if gh:
        try:
            parent = os.path.dirname(os.path.abspath(gh))
            os.makedirs(parent, exist_ok=True)
            with open(gh, "a", encoding="utf-8") as f:
                f.write(md)
            written.append(gh)
        except OSError as e:
            errors.append(f"{gh}: {e}")
    if not written:
        # env 不在场或写失败 → 回落 (GH 成功时不产生多余的本地文件)
        fallback = out_path or "job-summary.md"
        try:
            parent = os.path.dirname(os.path.abspath(fallback))
            os.makedirs(parent, exist_ok=True)
            with open(fallback, "a", encoding="utf-8") as f:
                f.write(md)
            written.append(fallback)
        except OSError as e:
            errors.append(f"{fallback}: {e}")
    return {"ok": bool(written), "written": written, "error": "; ".join(errors)}


def _load_json(path: str) -> dict:
    """读 JSON; '-' = stdin。解析失败抛 ValueError (main 捕获转 exit 2)。"""
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层须为对象")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="verify 结果/发布记录 → GITHUB_STEP_SUMMARY (F-151)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--verify-file", default=None, metavar="PATH",
                     help="verify --json 的输出文件 ('-' = stdin)")
    src.add_argument("--release-record", default=None, metavar="PATH",
                     help="发布记录路径 (.workbench/releases/<tag>.json)")
    ap.add_argument("--out", default=None, metavar="PATH",
                    help="GITHUB_STEP_SUMMARY 不在场时的回落输出 (默认 "
                         "job-summary.md)")
    ap.add_argument("--project", default=None,
                    help="工程根 (额外脱敏前缀; 默认 TOOLKIT_ROOT)")
    args = ap.parse_args()

    try:
        if args.verify_file:
            md = render_verify_summary(_load_json(args.verify_file))
        else:
            md = render_release_summary(_load_json(args.release_record))
    except (ValueError, OSError) as e:
        print(f"错误: 输入不可用: {e}", file=sys.stderr)
        return 2

    md = redact(md, extra_roots=(args.project or "", TOOLKIT_ROOT))
    rs = write_summary(md, out_path=args.out)
    if not rs.get("ok"):
        print(f"错误: 摘要写入失败: {rs.get('error')}", file=sys.stderr)
        return 1
    print(f"[OK] 摘要已写入: {', '.join(rs['written'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
