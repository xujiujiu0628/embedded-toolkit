#!/usr/bin/env python3
"""发布门禁 — git tag 前以 clean rebuild 字节完整重跑闭环验证

借鉴 Embedded-AI-Harness #2 (发布字节复跑), spec 2026-08-26 §6。
门禁序列 (任一失败即中止):
  G0   git 仓 + 工作树 clean + 本地无同名 tag + 无同 HEAD 记录
  G0.5 SWD 连通性预检 (秒级, 区分"环境未备"与"固件真坏")
  G1   subprocess 重跑 verify.py --json --rebuild --gate-run, 须全绿
  G2   无未翻转 xfail (--allow-xfail 显式豁免留痕)
  G3   发布记录落盘 -> 复核 HEAD 未变 -> annotated tag -> 失败回滚记录

用法:
  python release.py --tag v1.0.0 [--project DIR] [--dry-run] [--allow-xfail]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wb_common import (TOOLKIT_ROOT, atomic_write_json, find_project_root,  # noqa: E402
                       load_machine, toolkit_version)
from openocd_runtime import swd_probe  # noqa: E402  (F-041: 下沉共享层, doctor 与 G0.5 同源)

VERIFY = os.path.join(TOOLKIT_ROOT, "scripts", "verify.py")


def _git(args_, cwd):
    r = subprocess.run(["git"] + args_, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30, cwd=cwd)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def g0_checks(ws, tag):
    """G0: 返回违规消息列表 (空 = 通过)。拒绝键: 本地 tag 已存在
    或 存在 git_head 相同的既有记录 (不同 HEAD 的旧记录视为可覆盖)。"""
    rc, out, _ = _git(["rev-parse", "--is-inside-work-tree"], ws)
    if rc != 0 or out != "true":
        return [f"不是 git 仓库: {ws}"]
    errs = []
    rc, dirty, _ = _git(["status", "--porcelain"], ws)
    if rc != 0 or dirty:
        errs.append("工作树不干净 (先 commit; git status --porcelain 非空)")
    rc, out, _ = _git(["tag", "-l", tag], ws)
    if rc == 0 and out:
        errs.append(f"本地 tag 已存在: {tag}")
    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    rec_p = os.path.join(ws, ".workbench", "releases", f"{tag}.json")
    if os.path.exists(rec_p):
        try:
            with open(rec_p, encoding="utf-8") as f:
                old_head = json.load(f).get("git_head", "")
            if old_head == head:
                errs.append(f"同 HEAD 已有发布记录: {rec_p}")
        except Exception:
            errs.append(f"既有发布记录不可解析: {rec_p}")
    return errs


def gate1(ws, timeout):
    """G1: subprocess 重跑 verify (clean rebuild + 清单判定), 返回 JSON 结果。
    验证的就是开发者日常那条命令 — 门禁公信力所在。"""
    cmd = [sys.executable, VERIFY, "--json", "--rebuild",
           "--gate-run",
           "--task-origin", "schedule",
           "--require-schedule-origin",
           "--timeout", str(timeout)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=600, cwd=ws)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "verify 重跑超时 (600s)"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        tail = ((r.stderr or "") + (r.stdout or ""))[-300:]
        return {"status": "error", "error": f"verify 输出不可解析: {tail}"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _gcc_version():
    m = load_machine()
    gcc_path = (m.get("gcc_path") or "").strip()
    exe = os.path.join(gcc_path, "arm-none-eabi-gcc.exe") if gcc_path \
        else "arm-none-eabi-gcc"
    try:
        r = subprocess.run([exe, "--version"], capture_output=True,
                           text=True, timeout=10)
        lines = (r.stdout or "").splitlines()
        return lines[0][:80] if lines else "unknown"
    except Exception:
        return "unknown"


def run_gates(ws, tag, allow_xfail, timeout, openocd_exe,
              allow_non_hw_evidence=False):
    """跑 G0~G2。返回 (ok, 人读消息, ctx)；ctx 含 verify 结果/results/waived/
    evidence。"""
    errs = g0_checks(ws, tag)
    if errs:
        return False, "G0 失败:\n  " + "\n  ".join(errs), {}
    ok, msg = swd_probe(openocd_exe)
    if not ok:
        return False, f"G0.5 SWD 预检失败 (环境未备?): {msg}", {}
    res = gate1(ws, timeout)
    if res.get("status") != "ok":
        return False, (f"G1 verify 未绿: {res.get('error', res.get('status'))}\n"
                       "  修复后重试; 现场见 .workbench/build/last_failure.json"), {}
    results = (res.get("steps", {}).get("verify", {}) or {}).get("results")
    if results is None:
        return False, "G1 结果缺 results 数组 (该工程是否未建 expectations.json?)", {}
    reds = [r["id"] for r in results if r["status"] == "fail"]
    if reds:
        return False, f"G1 有 FAIL 条目: {', '.join(reds)}", {}
    xfailed = [r["id"] for r in results if r["status"] == "xfail"]
    if xfailed and not allow_xfail:
        return False, ("G2 存在未翻转 xfail: " + ", ".join(xfailed) +
                       "\n  实现并翻转后重试; 或 --allow-xfail 显式豁免 (留痕入档)"), {}
    waived = list(xfailed)
    # F-128 (工单二 A-1) / F-146 (T2 命名对齐 AEL): G2 证据等级门 — 仿真/
    # 静态证据不得支撑发布 ("仿真通过永不升级为硬件等价声明")。
    # 旧版 verify 无 evidence 键按 static 处理, 同样拦 (升 toolkit 后重发)。
    evidence = res.get("evidence", "static")
    if evidence != "hardware_validated" and not allow_non_hw_evidence:
        return False, (f"G2 证据等级 {evidence!r} != hardware_validated — "
                       "非真机证据不得进发布门禁\n"
                       "  或 --allow-non-hardware-evidence 显式豁免"
                       " (evidence_waiver 留痕入档, 审计 R8 可见)"), {}
    return True, "G0~G2 全过", {"verify_result": res, "results": results,
                                "waived": waived, "evidence": evidence,
                                "evidence_waiver": bool(
                                    evidence != "hardware_validated")}


# F-146: 各证据等级的 fidelity 边界声明 (AEL claim+fidelity 的落档形态) —
# 发布记录必须自带"这证据证明了什么/没证明什么", 不许只落一个裸等级值。
_FIDELITY_BOUNDARIES = {
    "hardware_validated":
        "真机 capture 输出匹配判定; 不构成产品级/认证级/长期可靠性声明",
    "simulation_validated":
        "仿真后端通过; 不升级为硬件等价声明 (仿真与真机是平级判定后端, 各证各的)",
    "static":
        "仅构建/静态证据; 无任何运行时行为判定",
    "production_approved":
        "hardware_validated 基础上经 release_audit --approve 人工批准投产",
}


def build_record(ws, tag, results, waived, contracts=None, evidence="static",
                 evidence_waiver=False, fidelity_boundaries=None,
                 limitations=None):
    """构建发布记录。evidence 为 F-128/F-146 证据分级透传 (G1 verify 输出);
    evidence_waiver 仅在 G2 证据门被显式豁免时为 True (留痕, 审计 R8 可见);
    fidelity_boundaries 默认按证据等级落边界声明, limitations 默认空列表
    (不虚报), signature 留空占位 (签名机制登记不实现)。"""
    artifacts = {}
    state_p = os.path.join(ws, ".workbench", "state.json")
    arts = {}
    if os.path.exists(state_p):
        try:
            with open(state_p, encoding="utf-8") as f:
                arts = json.load(f).get("last_build", {}).get("artifacts", {})
        except Exception:
            arts = {}
    for key in ("hex_file", "elf_file"):
        rel = arts.get(key, "")
        abs_p = os.path.join(ws, rel) if rel else ""
        if rel and os.path.exists(abs_p):
            artifacts[key.replace("_file", "")] = {
                "path": rel, "sha256": sha256_file(abs_p)}
    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    _, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    return {
        "tag": tag,
        "git_head": head,
        "branch": branch or "?",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "build_mode": "clean_rebuild",
        "artifacts": artifacts,
        # F-018: 判绿锚点 — results 由哪份 expectations/config 内容产生 (来自
        # G1 verify 输出的 contract_hashes; 旧版 verify 无此键时落空字典, R7 警告)
        "contracts": contracts or {},
        "results": results,
        "xfail_waived": waived,
        "evidence": evidence,   # F-146: hardware_validated | simulation_validated | static | production_approved
        # F-146: fidelity 契约 — 记录自带"证据证明了什么/没证明什么"
        "fidelity_boundaries": (list(fidelity_boundaries)
                                if fidelity_boundaries is not None
                                else [_FIDELITY_BOUNDARIES.get(
                                    evidence, f"未知证据等级 {evidence!r}")]),
        "limitations": list(limitations) if limitations is not None else [],
        "signature": "",   # 留空占位: 签名机制登记不实现 (总工单 v2 A-1)
        **({"evidence_waiver": True} if evidence_waiver else {}),
        "tools": {"toolkit": toolkit_version(),
                  "python": sys.version.split()[0],
                  "gcc": _gcc_version()},
    }


def finalize(ws, tag, record):
    """G3+tag 安全序列: 写记录 -> 复核 HEAD 未变且无其他改动 -> 打 annotated
    tag -> 任一步失败回滚删除记录。注意: 记录文件自身造成的 dirty 是预期内的
    (releases/ 入库策略), 只拦截"其他"改动。成功后 git add 记录供用户提交。"""
    rec_dir = os.path.join(ws, ".workbench", "releases")
    os.makedirs(rec_dir, exist_ok=True)
    rec_p = os.path.join(rec_dir, f"{tag}.json")
    atomic_write_json(rec_p, record)  # F-022: 发布记录是 R7/M2 取证锚, 撕裂即报废
    rec_rel = os.path.relpath(rec_p, ws).replace(os.sep, "/")

    def _rollback():
        os.remove(rec_p)
        try:
            os.rmdir(rec_dir)   # 回滚后不留空目录 (审计 L6)
        except OSError:
            pass

    _, head, _ = _git(["rev-parse", "HEAD"], ws)
    # -uall: 未跟踪目录展开为单文件 — 否则新仓首发布时 porcelain 只给
    # "?? .workbench/" 目录行, 记录文件会被误判为 foreign 而回滚
    _, dirty, _ = _git(["status", "--porcelain", "-uall"], ws)
    foreign = [l for l in dirty.splitlines()
               if l.strip() and not l.strip().endswith(rec_rel)]
    if head != record["git_head"] or foreign:
        _rollback()
        print(f"打 tag 前复核失败: HEAD 变动或出现其他改动 ({foreign}), 记录已回滚",
              file=sys.stderr)
        return False
    r = subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"release {tag} (record: {rec_rel})"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30, cwd=ws)
    if r.returncode != 0:
        _rollback()
        print(f"打 tag 失败, 记录已回滚: {(r.stderr or '').strip()}",
              file=sys.stderr)
        return False
    _git(["add", rec_rel], ws)
    return True


def main():
    ap = argparse.ArgumentParser(description="发布门禁 — 全绿才许打 tag")
    ap.add_argument("--tag", required=True, help="版本 tag, 如 v1.0.0")
    ap.add_argument("--project", default=None, help="工程根目录 (默认向上发现)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑 G0~G2, 不落记录不打 tag")
    ap.add_argument("--allow-xfail", action="store_true",
                    help="豁免未翻转 xfail (ID 记入发布档案)")
    ap.add_argument("--allow-non-hardware-evidence",
                    dest="allow_non_hw_evidence", action="store_true",
                    help="豁免 G2 证据等级门 (F-128: 仿真/静态证据) — "
                         "evidence_waiver 留痕入档, 审计 R8 降级警告")
    ap.add_argument("--timeout", type=int, default=10, help="采集超时秒数")
    args = ap.parse_args()

    ws = args.project or find_project_root(os.getcwd())
    if not ws:
        print("错误: 未找到工程根 (含 .workbench/config.json)", file=sys.stderr)
        sys.exit(1)
    ws = os.path.abspath(ws)
    if not os.path.isdir(ws):
        print(f"错误: --project 目录不存在: {ws}", file=sys.stderr)
        sys.exit(1)
    openocd_exe = load_machine()["openocd_exe"]

    ok, msg, ctx = run_gates(ws, args.tag, args.allow_xfail,
                             args.timeout, openocd_exe,
                             allow_non_hw_evidence=args.allow_non_hw_evidence)
    print(msg)
    if not ok:
        sys.exit(1)

    record = build_record(
        ws, args.tag, ctx["results"], ctx["waived"],
        contracts=(ctx.get("verify_result") or {}).get("contract_hashes"),
        evidence=ctx.get("evidence", "static"),
        evidence_waiver=bool(ctx.get("evidence_waiver")))
    # 审计 M2: hex 哈希是"烧的字节→验的字节→入档字节"互锁的锚,
    # state.json 读不到 artifacts 时静默落档会让证据链无声断裂 → 强制中止
    if "hex" not in record["artifacts"]:
        print("错误: 发布记录缺 hex 哈希证据 (state.json last_build.artifacts "
              "不可用) — clean rebuild 的字节未入档, 拒绝发布", file=sys.stderr)
        sys.exit(1)
    if args.dry_run:
        print(f"[dry-run] 将写 .workbench/releases/{args.tag}.json 并打 tag "
              f"{args.tag}; results={len(record['results'])} 条, "
              f"xfail_waived={record['xfail_waived']}, "
              f"evidence={record['evidence']}"
              + (", evidence_waiver=True" if record.get("evidence_waiver") else "")
              + f", artifacts={list(record['artifacts'])}")
        sys.exit(0)

    if not finalize(ws, args.tag, record):
        sys.exit(1)
    print(f"[OK] 已发布 {args.tag}: 记录 .workbench/releases/{args.tag}.json;"
          " push 请自行执行")


if __name__ == "__main__":
    main()
