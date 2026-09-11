#!/usr/bin/env python3
"""fsd_coverage.py — FSD 需求 ↔ expectations.json 断言对账 (F-113)。

互锁链第 1→2 站的机器看守 (spec embedded-handoff
2026-09-11-fsd-coverage-reconciler-design.md): 考题从 FSD 抄进考卷
(expectations.json) 此前靠人肉, 漏抄/多抄/同 ID 异义全部沉默。本工具把
三判据接上机器:

  C1  孤儿断言 (expectations id 在 FSD 无出处)            -> ERROR
  C2  需求无断言 (FSD 需求既无 expectations 条目又无豁免)   -> ERROR
  C3  豁免不完备 (waived 条目缺 reason / 缺 id 对齐)        -> ERROR
  对照表: 双侧 id + 标题/desc 并排输出——同 ID 语义漂移从
  "不可见"升级为"必须过目" (v1 对语义层部的全部承诺, 审读者一眼扫)。

分工纪律 (spec §3):
  - xfail = 断言已建、功能未实现的欠条; waived = 此需求不走 verify 闭环
    的豁免登记。两级互不混用。
  - lint (expectations_lint) 管清单自洽; 本工具管跨文件对账——输入面不同,
    故独立脚本。退出码风格对齐 lint: 0 干净/警告, 1 违规, 2 用法/缺文件。

语义边界如实声明: 本工具对账 **ID 集合与豁免登记**, 不校验语义等价。

用法:
  python scripts/fsd_coverage.py --project <工程根>
  python scripts/fsd_coverage.py --project . --json
  python scripts/fsd_coverage.py <fsd.md> <expectations.json>   (显式两文件)
"""
import argparse
import json
import os
import re
import sys

from wb_common import find_project_root

# FSD 需求标题: ### FR-MPU-01：地址探测 / ## FR-KEY-02: 长短按识别 / ### NFR-01：性能
# (容全/半角冒号; FR 带域段可选, NFR 无域段; 只在行首标题层级匹配,
#  代码块围栏内不计——见 parse_fsd)
_FSD_ID_RE = re.compile(
    r'^#{2,4}\s+((?:FR(?:-[A-Z]+)?|NFR)-\d+)\s*[:：]\s*(.*)$')


def parse_fsd(md_text):
    """FSD Markdown -> [{id, title}]。跳过 ``` 围栏 (模板含 YAML 示例块)。
    同 ID 重复出现取首个 (ID 稳定纪律, 重复本身是 FSD 卫生问题, 不在本工具
    判权范围内——如实报重复对账项即可)。"""
    reqs = []
    seen = set()
    in_fence = False
    for line in md_text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _FSD_ID_RE.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            reqs.append({"id": m.group(1), "title": m.group(2).strip()})
    return reqs


def load_waived(manifest_obj):
    """从 expectations.json 顶层对象取 waived 数组 (可能缺键——旧清单宽容,
    loader 对未知顶层键不报错的原状保持)。返回 {id: waiver}。"""
    out = {}
    for w in (manifest_obj or {}).get("waived", []) or []:
        if isinstance(w, dict) and isinstance(w.get("id"), str):
            out[w["id"]] = w
    return out


def diff(fsd_reqs, exp_ids, waived):
    """三判纯函数 (IO 归调用方)。fsd_reqs=[{id,title}], exp_ids=[str],
    waived={id: waiver}. 返回 (errors, warnings, table_rows)。
    table_rows: [{id, fsd_title, exp_desc|—, waived}]。"""
    errors = []
    warnings = []
    fsd_ids = [r["id"] for r in fsd_reqs]
    fsd_set = set(fsd_ids)
    exp_set = set(exp_ids)

    # C3 先行: 豁免完备性 (waived 引用不存在的 FSD 需求 / 缺 reason)
    for wid, w in sorted(waived.items()):
        if wid not in fsd_set:
            errors.append(f"C3: 豁免 {wid} 无对应 FSD 需求 (孤儿豁免)")
        reason = w.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"C3: 豁免 {wid} 缺 reason — 豁免必须给理由")

    # C1 孤儿断言
    for eid in exp_ids:
        if eid not in fsd_set:
            errors.append(f"C1: 断言 {eid} 无 FSD 出处 (孤儿断言)")

    # C2 需求无断言 (xfail 已建条目算"有断言", 不欠账)。
    # 判据边界 (spec §2/§3): C2 只对 **FR-** (功能需求) 判 ERROR——NFR 多为
    # 性能/构建约束, 天然不走 capture 断言 (其一由 physical_gate/host 测试覆盖),
    # 一刀切判死会制造假红 (首跑实证: mpu6050-oled NFR×4)。NFR 无覆盖 → WARNING。
    covered = exp_set | set(waived.keys())
    for rid in fsd_ids:
        if rid in covered:
            continue
        if rid.startswith("FR-"):
            errors.append(f"C2: 需求 {rid} 无断言且无豁免 (欠账)")
        else:
            warnings.append(f"C2: NFR {rid} 无断言无豁免 (非功能约束, 如实提醒)")

    # 对照表 (漂移审读面)
    title_by_id = {r["id"]: r["title"] for r in fsd_reqs}
    rows = []
    for rid in fsd_ids:
        rows.append({"id": rid, "fsd_title": title_by_id.get(rid, ""),
                     "waived": rid in waived,
                     "asserted": rid in exp_set})
    return errors, warnings, rows


def _read_project(project):
    """返回 (fsd_text 或 None, manifest_obj 或 None, 消息列表)。"""
    msgs = []
    fsd_path = os.path.join(project, "docs", "FSD.md")
    if not os.path.isfile(fsd_path):
        msgs.append(f"FSD 不存在: {fsd_path}")
        fsd_text = None
    else:
        with open(fsd_path, encoding="utf-8") as f:
            fsd_text = f.read()
    exp_path = os.path.join(project, ".workbench", "expectations.json")
    if not os.path.isfile(exp_path):
        msgs.append(f"expectations.json 不存在: {exp_path} (legacy 工程? 无对账面)")
        return fsd_text, None, msgs
    with open(exp_path, encoding="utf-8") as f:
        return fsd_text, json.load(f), msgs


def run_coverage(project):
    """工程级对账, 返回 {project, verdict, errors, warnings, table, notes}。

    verdict ∈ clean/warn/error/skipped。输入不可得 (无 FSD 或无 manifest)
    判 **skipped** 而非 error——存量工程未建 FSD 是现状非事故 (FSD 层是
    08-20 后立规), 谎红会让 HANDOFF 秒检对 legacy 工程不可用; "无对账面"
    如实进 warnings, 审读者知道这块没有守卫 (诚实, 不假装通过)。"""
    fsd_text, manifest, notes = _read_project(project)
    if manifest is None or fsd_text is None:
        return {"project": project, "verdict": "skipped",
                "errors": [], "warnings": [f"无对账面: {n}" for n in notes],
                "table": [], "notes": notes}
    reqs = parse_fsd(fsd_text)
    exp_ids = [e["id"] for e in manifest.get("expectations", [])]
    waived = load_waived(manifest)
    errors, warnings, rows = diff(reqs, exp_ids, waived)
    verdict = "error" if errors else ("warn" if warnings else "clean")
    return {"project": project, "verdict": verdict, "errors": errors,
            "warnings": warnings, "table": rows,
            "counts": {"fsd": len(reqs), "assertions": len(exp_ids),
                       "waived": len(waived)},
            "notes": notes}


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="FSD ↔ expectations 覆盖率对账 (离线, 不触硬件)")
    ap.add_argument("fsd", nargs="?", default=None,
                    help="FSD.md 路径 (与 expectations.json 位置参数成对使用)")
    ap.add_argument("manifest", nargs="?", default=None,
                    help="expectations.json 路径")
    ap.add_argument("--project", default=None, help="工程根 (读 docs/FSD.md + "
                    ".workbench/expectations.json)")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    if args.project:
        result = run_coverage(os.path.abspath(args.project))
    elif args.fsd and args.manifest:
        with open(args.fsd, encoding="utf-8") as f:
            reqs = parse_fsd(f.read())
        with open(args.manifest, encoding="utf-8") as f:
            manifest = json.load(f)
        errors, warnings, rows = diff(reqs,
                                      [e["id"] for e in manifest.get("expectations", [])],
                                      load_waived(manifest))
        result = {"project": args.fsd,
                  "verdict": "error" if errors else ("warn" if warnings else "clean"),
                  "errors": errors, "warnings": warnings, "table": rows}
    else:
        root = find_project_root(os.getcwd())
        if not root:
            print("错误: 未指定 --project / 两位置参数, 且 cwd 不在工程内",
                  file=sys.stderr)
            return 2
        result = run_coverage(root)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"fsd_coverage: {result['project']}  ->  {result['verdict'].upper()}")
        c = result.get("counts")
        if c:
            print(f"  FSD 需求 {c['fsd']} | 断言 {c['assertions']} | 豁免 {c['waived']}")
        for e in result["errors"]:
            print(f"  [E] {e}")
        for w in result["warnings"]:
            print(f"  [W] {w}")
        print("  --- 对照表 (漂移审读面: 一眼扫语义) ---")
        for r in result["table"]:
            mark = ("✓断言" if r.get("asserted")
                    else ("⊘豁免" if r.get("waived") else "✗欠账"))
            print(f"  [{mark}] {r['id']:<14} {r.get('fsd_title', '')}")
        if not result["errors"] and not result["warnings"]:
            print("  对账全绿")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
