# -*- coding: utf-8 -*-
r"""handoff_guard — 外部智能体代管分支的沙盒禁线机器判据。

用途：换回协议第一步。扫描 `git diff base...branch`，判定 handoff 分支是否越过
"只码不碰硬件"的沙盒边界。输出 JSON，退出码 clean=0 / blocked=1。

三级判据（设计：维护者私有仓 D:\claude\embedded-handoff\docs\superpowers\specs\
2026-08-30-agent-handoff-design.md 第 5 节）：
  L1 文件禁线（硬阻断）：machine.json、hooks/、本脚本自身
  L2 硬件模式（阻断）：openocd 调用、烧录命令、串口打开、RTT 端口 19021、gdb 连硬件
  L3 主流程警告（不阻断）：改 verify.py/release.py 却无 tests/ 伴随改动

误杀防御（swd_probe 教训——判据内容导向）：
  - 只扫新增行；prose 文件（.md/.txt）与 tests/、fixtures/ 完全豁免 L2
  - 若同一 L2 规则在基础版本该文件里已存在（既有硬件层维护），降级为警告不阻断
  - 威胁模型是"善意的陌生智能体犯糊涂"，不防蓄意编码绕过——真机防线仍是换回人审+用户插板
"""
import argparse
import json
import re
import subprocess
import sys

# ---------- L1：文件禁线 ----------
FORBIDDEN_EXACT = {"machine.json", "scripts/handoff_guard.py"}
FORBIDDEN_PREFIX = ("hooks/",)

# ---------- L2：硬件模式（规则 = 同一条新增行须命中全部子正则） ----------
L2_RULES = [
    ("openocd_call", [r"openocd",
                      r"(?:-f\s|--command|\bflash\b|\bverify\b|target\s+remote|\binit\b|\bresume\b|\bhalt\b|init\.tcl)"]),
    ("flash_cmd", [r"flash\s+write_image|flash\s+protect|mass_erase|program\s+\S+\.(?:hex|bin)\s+verify"]),
    ("serial_open", [r"serial\.Serial\(|Serial\([\"']COM|import\s+serial\b|pyserial"]),
    ("rtt_port", [r"\b19021\b"]),
    ("gdb_remote", [r"target\s+remote\s+\S+|gdbserver"]),
]
L2_COMPILED = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in L2_RULES]

# 仅这些"代码语境"参与 L2 扫描；其余扩展名（.md/.txt 等 prose）豁免
CODE_EXTS = {".py", ".sh", ".bat", ".cmd", ".c", ".h", ".cpp", ".mk", ".tcl", ".cfg", ".json"}
L2_ALLOW_DIRS = {"tests", "fixtures"}

# ---------- L3：主流程文件 ----------
MAIN_FLOW_FILES = {"scripts/verify.py", "scripts/release.py"}

_COMMIT_HDR = re.compile(r"^@@COMMIT@@ ([0-9a-f]+) ([0-9a-f]+)$")
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$")


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo] + list(args),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失败: %s" % (" ".join(args), (r.stderr or "").strip()))
    return r.stdout


def _norm(path):
    return path.replace("\\", "/").lstrip("./")


def _in_allowlist(path):
    parts = _norm(path).split("/")
    return any(p in L2_ALLOW_DIRS for p in parts[:-1])


def _is_code(path):
    base = _norm(path).rsplit("/", 1)[-1]
    if base == "Makefile":
        return True
    return re.search(r"\.[A-Za-z0-9]+$", base) and \
        re.search(r"\.[A-Za-z0-9]+$", base).group(0).lower() in CODE_EXTS


def _l2_hit(line):
    """返回该行命中的规则名列表（须全子正则命中）。"""
    hits = []
    for name, pats in L2_COMPILED:
        if all(p.search(line) for p in pats):
            hits.append(name)
    return hits


def _base_has_rule(repo, base, path, rule_name):
    """基础版本的该文件里是否已存在同规则（内容导向降级判据）。"""
    try:
        content = _git(repo, "show", "%s:%s" % (base, path), check=True)
    except RuntimeError:
        return False  # 基础版本无此文件 = 新增 → 无降级资格
    pats = dict(L2_COMPILED)[rule_name]
    return all(any(p.search(ln) for ln in content.splitlines()) for p in pats)


def _touching_commits(repo, base, branch, path):
    """哪些 commit 动了该路径（返回短 sha 列表，旧→新）。"""
    out = _git(repo, "log", "%s..%s" % (base, branch), "--reverse",
               "--format=%h", "--", path)
    return [s for s in out.split() if s]


def guard(repo, branch, base="master"):
    # 预检：两端可解析
    for ref in (base, branch):
        _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if not _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").strip():
            raise RuntimeError("分支/基线不存在: %s" % ref)

    changed = [_norm(p) for p in _git(repo, "diff", "--name-only",
                                      "%s...%s" % (base, branch)).splitlines() if p.strip()]

    blocked, warnings = [], []

    # ---- L1：文件禁线（全量 diff 判定，归属到最后触碰该文件的 commit）----
    for path in changed:
        if path in FORBIDDEN_EXACT or path.startswith(FORBIDDEN_PREFIX):
            shas = _touching_commits(repo, base, branch, path)
            blocked.append({"commit": shas[-1] if shas else "?",
                            "file": path,
                            "rule": "forbidden_file:" + path,
                            "evidence": "(文件位于禁改区)"})

    # ---- L2：逐 commit 扫新增行 ----
    log = _git(repo, "log", "%s..%s" % (base, branch), "--reverse",
               "--format=@@COMMIT@@ %H %h", "-p")
    commit = short = None
    cur_file = None
    commits_scanned = 0
    for line in log.splitlines():
        m = _COMMIT_HDR.match(line)
        if m:
            commit, short = m.group(1), m.group(2)
            commits_scanned += 1
            cur_file = None
            continue
        m = _DIFF_FILE.match(line)
        if m:
            cur_file = _norm(m.group(2))
            continue
        if line.startswith("+") and not line.startswith("+++") and cur_file:
            if not _is_code(cur_file) or _in_allowlist(cur_file):
                continue
            added = line[1:]
            for rule in _l2_hit(added):
                if _base_has_rule(repo, base, cur_file, rule):
                    warnings.append({"commit": short, "file": cur_file,
                                     "rule": rule,
                                     "note": "pre_existing_pattern（既有硬件层维护，降级）",
                                     "evidence": added.strip()[:120]})
                else:
                    blocked.append({"commit": short, "file": cur_file,
                                    "rule": rule,
                                    "evidence": added.strip()[:120]})

    # ---- L3：主流程改动无测试伴随 ----
    has_test_change = any(p == "tests" or p.startswith("tests/") for p in changed)
    if not has_test_change:
        for path in changed:
            if path in MAIN_FLOW_FILES:
                shas = _touching_commits(repo, base, branch, path)
                warnings.append({"commit": shas[-1] if shas else "?", "file": path,
                                 "rule": "main_flow_no_test",
                                 "note": "主流程改动但 tests/ 无新增/修改，人审必查",
                                 "evidence": ""})

    verdict = "blocked" if blocked else "clean"
    return {"verdict": verdict, "base": base, "branch": branch,
            "commits_scanned": commits_scanned,
            "blocked": blocked, "warnings": warnings}


def main(argv=None):
    ap = argparse.ArgumentParser(description="handoff 分支沙盒禁线扫描（换回协议第一步）")
    ap.add_argument("--repo", default=".", help="仓库路径（默认 cwd）")
    ap.add_argument("--branch", required=True, help="handoff/* 分支")
    ap.add_argument("--base", default="master", help="基线分支（默认 master）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON（机器消费）")
    args = ap.parse_args(argv)

    try:
        v = guard(args.repo, args.branch, args.base)
    except RuntimeError as e:
        print("guard 错误: %s" % e, file=sys.stderr)
        return 2

    print(json.dumps(v, ensure_ascii=False, indent=2))
    if not args.json:
        print("\n== verdict: %s | blocked=%d warnings=%d ==" %
              (v["verdict"], len(v["blocked"]), len(v["warnings"])), file=sys.stderr)
    return 1 if v["verdict"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
