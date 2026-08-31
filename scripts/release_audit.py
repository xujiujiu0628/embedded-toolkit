#!/usr/bin/env python3
"""发布记录事后审计 — 补齐门禁"防糊涂不防蓄意"的最后一块 (M-3, 代管期 2026-08-30)。

release.py 在发布时保证 G0~G3 全绿 + hex 哈希强制入档; 但 releases/*.json 与
annotated tag 都是本地 git 操作, 无签名 — 事后可被手工篡改而无人察觉。本工具
对既有发布做**只读**一致性复核 (不触硬件、不改任何文件、不联网):

  R1  记录存在且 JSON 可解析
  R2  tag 存在, 且 tag 指向的 commit == 记录 git_head
  R3  hex 字节证据: 重算 sha256 与记录一致 (文件缺失降级警告 — build/ 可被清理)
  R4  results 无 FAIL/XPASS 条目, 且 xfail_waived 与 results 内 XFAIL 集合相等
  R5  记录结构完整性 (tag/git_head/timestamp/build_mode/artifacts/results/
      xfail_waived/tools 必填, tag 字段与文件名一致)
  R6  记录文件已被 git 提交入库 (未提交 = 警告级)
  R7  契约哈希锚点 (F-018): 记录 contracts 的 expectations/config sha256
      与 git show git_head: 重算一致 (不匹配 = fail; 旧记录缺绑定 = 警告)

用法:
  python scripts/release_audit.py --project <工程根> --tag v1.1.0
  python scripts/release_audit.py --project <工程根> --all
  python scripts/release_audit.py --project <工程根> --all --json

退出码: 0 = clean/warned, 1 = 存在 fail 项 (证据链断裂或被篡改), 2 = 用法/环境错误
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

from wb_common import find_project_root

REQUIRED_KEYS = ("tag", "git_head", "timestamp", "build_mode", "artifacts",
                 "results", "xfail_waived", "tools")


def _git(args_, cwd):
    r = subprocess.run(["git"] + args_, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30, cwd=cwd)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _git_bytes(args_, cwd):
    """git 命令字节输出 (R7 用: 哈希必须对原始字节算, 不经文本解码往返)"""
    r = subprocess.run(["git"] + args_, capture_output=True, timeout=30, cwd=cwd)
    return r.returncode, (r.stdout or b""), (r.stderr or b"").decode("utf-8", "replace")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check(checks, cid, status, detail):
    checks.append({"id": cid, "status": status, "detail": detail[:300]})


def audit_record(ws, tag, rel_path):
    """审计单条发布记录, 返回 {tag, record_path, checks[], verdict}。"""
    checks = []

    # R1 记录存在且可解析
    abs_p = os.path.join(ws, rel_path)
    try:
        with open(abs_p, encoding="utf-8") as f:
            record = json.load(f)
        if not isinstance(record, dict):
            raise ValueError("记录顶层须为 JSON 对象")
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as e:
        _check(checks, "R1", "fail", f"记录不可解析 ({rel_path}): {e}")
        return {"tag": tag, "record_path": rel_path,
                "checks": checks, "verdict": "failed"}
    _check(checks, "R1", "pass", f"记录可解析: {rel_path}")

    # R2 tag 存在且指向记录 HEAD
    rc, out, _ = _git(["rev-parse", "--verify", "--quiet", tag + "^{commit}"], ws)
    if rc != 0 or not out:
        _check(checks, "R2", "fail", f"tag 不存在: {tag} (本地丢 tag 或从未打过)")
    else:
        _, head, _ = _git(["rev-parse", "HEAD"], ws)
        tag_commit = out
        rec_head = record.get("git_head", "")
        if tag_commit != rec_head:
            _check(checks, "R2", "fail",
                   f"tag {tag} 指向 {tag_commit[:12]} 但记录声明 {rec_head[:12]}")
        else:
            _check(checks, "R2", "pass", f"tag 指向与记录 git_head 一致 ({rec_head[:12]})")

    # R3 hex 字节证据
    hex_info = (record.get("artifacts", {}) or {}).get("hex", {}) or {}
    hex_rel = hex_info.get("path", "")
    hex_abs = os.path.join(ws, hex_rel) if hex_rel else ""
    if not hex_rel:
        _check(checks, "R3", "fail", "记录缺 hex 哈希证据 (artifacts.hex)")
    elif not os.path.isfile(hex_abs):
        _check(checks, "R3", "warn",
               f"hex 文件不在场 ({hex_rel}) — build/ 可能已清理, 字节比对跳过")
    else:
        actual = sha256_file(hex_abs)
        if actual != hex_info.get("sha256", ""):
            _check(checks, "R3", "fail",
                   f"hex 字节被改动: 重算 {actual[:16]}.. != 记录 "
                   f"{str(hex_info.get('sha256', ''))[:16]}..")
        else:
            _check(checks, "R3", "pass", f"hex sha256 一致 ({hex_rel})")

    # R4 results 判定自洽
    results = record.get("results")
    if not isinstance(results, list) or not results:
        _check(checks, "R4", "fail", "results 缺失或为空 (发布时 G1 必产出)")
    else:
        fails = [r.get("id") for r in results if r.get("status") == "fail"]
        xpasses = [r.get("id") for r in results if r.get("status") == "xpass"]
        xfailed = sorted(r.get("id") for r in results if r.get("status") == "xfail")
        waived = sorted(record.get("xfail_waived") or [])
        if fails:
            _check(checks, "R4", "fail", f"记录含 FAIL 条目: {', '.join(map(str, fails))}")
        elif xpasses:
            _check(checks, "R4", "fail", f"记录含 XPASS 条目 (发布时必判红): {', '.join(map(str, xpasses))}")
        elif xfailed != waived:
            _check(checks, "R4", "fail",
                   f"xfail_waived 留痕与 results 不自洽: results XFAIL={xfailed} waived={waived}")
        else:
            _check(checks, "R4", "pass",
                   f"{len(results)} 条结果自洽" + (f", waived={xfailed}" if xfailed else ""))

    # R5 结构完整性
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        _check(checks, "R5", "fail", f"缺必填字段: {', '.join(missing)}")
    elif record.get("tag") != tag:
        _check(checks, "R5", "fail",
               f"记录内 tag={record.get('tag')!r} 与文件名 {tag!r} 不一致")
    else:
        _check(checks, "R5", "pass", "结构完整")

    # R6 记录已入库
    rc, out, _ = _git(["ls-files", "--", rel_path.replace(os.sep, "/")], ws)
    if rc != 0 or not out.strip():
        _check(checks, "R6", "warn", "发布记录未被 git 跟踪 (发布后未提交)")
    else:
        _check(checks, "R6", "pass", "记录已入库")

    # R7 契约哈希锚点 (F-018, 2026-08-30 R2): results 由哪份 expectations/config
    # 产生 — G0 保证发布时工作树 clean, 故记录里的哈希必须等于 git_head 处的
    # 文件内容; 不等 = 判绿依据与 tag 指向的代码错位 (篡改/搬移记录即现形)。
    contracts = record.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        _check(checks, "R7", "warn", "记录缺契约哈希绑定 (R7 之前的旧版 release.py 产物)")
    elif not record.get("git_head"):
        _check(checks, "R7", "warn", "记录无 git_head, 契约哈希无从比对")
    else:
        r7_bad = []
        r7_ok = 0
        for key, rel in (("expectations_sha256", ".workbench/expectations.json"),
                         ("config_sha256", ".workbench/config.json")):
            want = contracts.get(key)
            if not want:
                continue   # legacy 模式无清单 / 缺该键 → 子项跳过
            rc, blob, gerr = _git_bytes(["show", f"{record['git_head']}:{rel}"], ws)
            if rc != 0:
                _check(checks, "R7", "warn",
                       f"{rel} 在 git_head 不可得: {gerr.strip()[:120]}")
                continue
            actual = hashlib.sha256(blob).hexdigest()
            if actual != want:
                r7_bad.append(f"{rel} 记录={want[:12]}.. 实际={actual[:12]}..")
            else:
                r7_ok += 1
        if r7_bad:
            _check(checks, "R7", "fail",
                   "判绿依据与 git_head 内容错位: " + "; ".join(r7_bad))
        elif r7_ok:
            _check(checks, "R7", "pass", f"{r7_ok} 项契约哈希与 git_head 一致")
        else:
            _check(checks, "R7", "warn", "记录契约哈希均为空 (legacy 无清单?)")

    if any(c["status"] == "fail" for c in checks):
        verdict = "failed"
    elif any(c["status"] == "warn" for c in checks):
        verdict = "warned"
    else:
        verdict = "clean"
    return {"tag": tag, "record_path": rel_path, "checks": checks, "verdict": verdict}


def audit_project(ws, only_tag=None):
    rec_dir = os.path.join(ws, ".workbench", "releases")
    if not os.path.isdir(rec_dir):
        return {"project": ws, "records": [], "verdict": "warned",
                "error": f"无 releases 目录: {rec_dir} (该工程尚未发布过)"}
    names = sorted(n for n in os.listdir(rec_dir) if n.endswith(".json"))
    if only_tag:
        names = [n for n in names if n == f"{only_tag}.json"]
        if not names:
            return {"project": ws, "records": [], "verdict": "failed",
                    "error": f"记录不存在: {only_tag}.json"}
    records = [audit_record(ws, n[:-len(".json")], os.path.join(".workbench", "releases", n))
               for n in names]
    if any(r["verdict"] == "failed" for r in records):
        verdict = "failed"
    elif any(r["verdict"] == "warned" for r in records):
        verdict = "warned"
    else:
        verdict = "clean"
    return {"project": ws, "records": records, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser(description="发布记录事后审计 (只读, 不触硬件)")
    ap.add_argument("--project", default=None, help="工程根目录 (默认 cwd 向上发现)")
    ap.add_argument("--tag", default=None, help="只审计指定 tag (如 v1.1.0)")
    ap.add_argument("--all", dest="all_tags", action="store_true",
                    help="审计 releases/ 下全部记录")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    if not (args.tag or args.all_tags):
        print("错误: 需 --tag <X> 或 --all 之一", file=sys.stderr)
        return 2
    ws = args.project or find_project_root(os.getcwd())
    if not ws or not os.path.isdir(ws):
        print("错误: 未找到工程根 (含 .workbench/config.json)", file=sys.stderr)
        return 2
    ws = os.path.abspath(ws)

    result = audit_project(ws, only_tag=args.tag)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"发布审计: {result['project']}  ->  {result['verdict'].upper()}")
        if result.get("error"):
            print(f"  !! {result['error']}")
        for rec in result["records"]:
            print(f"  [{rec['verdict']}] {rec['tag']}")
            for c in rec["checks"]:
                if c["status"] != "pass":
                    print(f"      {c['id']} {c['status'].upper()}: {c['detail']}")
    return 1 if result["verdict"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
