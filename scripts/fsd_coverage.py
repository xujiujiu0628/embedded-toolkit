#!/usr/bin/env python3
"""fsd_coverage.py — FSD 需求 ↔ expectations.json 断言对账 (F-113)。

互锁链第 1→2 站的机器看守 (spec embedded-handoff
2026-09-11-fsd-coverage-reconciler-design.md): 考题从 FSD 抄进考卷
(expectations.json) 此前靠人肉, 漏抄/多抄/同 ID 异义全部沉默。本工具把
三判据接上机器:

  C0  输入损坏 (manifest 非法 JSON / 条目缺 id / 顶层非对象) -> ERROR
  C1  孤儿断言 (expectations id 在 FSD 无出处)                -> ERROR
  C2  需求无断言 (FR 既无 expectations 条目又无豁免 -> ERROR;
      NFR 无覆盖 -> WARNING——性能/构建约束天然不走 capture 断言, 首跑实证)
  C3  豁免不完备 (waived 条目非法/缺 id/缺 reason/缺 evidence)  -> ERROR
  对照表: 双侧 id + FSD 标题 + 断言 desc + 负断言标记并排输出——同 ID 语义
  漂移从"不可见"升级为"必须过目" (spec §2 对 C-漂移的全部承诺; 孤儿断言
  单独成行, F-114/H-2 补齐)。

分工纪律 (spec §3):
  - xfail = 断言已建、功能未实现的欠条; waived = 此需求不走 verify 闭环
    的豁免登记。两级互不混用。
  - lint (expectations_lint) 管清单自洽; 本工具管跨文件对账——输入面不同,
    故独立脚本。损坏输入走结构化 C0 报告而非裸 traceback (F-114/H-1)。

语义边界如实声明: 本工具对账 **ID 集合与豁免登记**, 不校验语义等价。

FSD 路径: 默认 docs/FSD.md; .workbench/config.json 的 "fsd_path" 字段可覆盖
(F-114/M-1 兑现 spec §2)。

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
    同 ID 重复出现取首个、不报错——重复属 FSD 卫生问题, 对账以去重集为准,
    判权重归规格审读 (F-114/L-4 措辞订正: 原 docstring 声称"如实报重复"
    与实现不符, 以本句为准)。"""
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
    """从 expectations.json 顶层对象取 waived -> {id: waiver} (合法项)。
    宽容函数: 非法项直接跳过不报——结构校验归 validate_waived (run_coverage
    调用面), 本函数供只想要映射的调用方。旧清单无该键 → 空 (向后兼容)。"""
    out = {}
    raw = (manifest_obj or {}).get("waived", [])
    if not isinstance(raw, list):
        return out
    for w in raw:
        if isinstance(w, dict) and isinstance(w.get("id"), str) and w["id"].strip():
            out[w["id"]] = w
    return out


def validate_waived(manifest_obj):
    """F-114/M-2: waived 数组结构校验 (非法项不得静默吞——豁免登记写坏本身
    要有声)。返回 (errors, waived_dict)。"""
    errors = []
    raw = (manifest_obj or {}).get("waived", [])
    if raw is None:
        return [], {}
    if not isinstance(raw, list):
        return ["C3: waived 顶层须为数组"], {}
    waived = {}
    for i, w in enumerate(raw):
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) \
                or not w["id"].strip():
            errors.append(f"C3: waived[{i}] 非法条目 (须为含非空 id 的对象) — "
                          "损坏豁免静默吞属禁止行为")
            continue
        if w["id"] in waived:
            errors.append(f"C3: 豁免 id 重复: {w['id']}")
            continue
        waived[w["id"]] = w
    return errors, waived


def normalize_expectations(manifest_obj):
    """expectations 数组 -> (errors, exp_items=[{id, desc, forbidden}])。
    F-114/H-1: 损坏条目报 C0 而非 KeyError 裸崩。"""
    errors = []
    items = []
    arr = (manifest_obj or {}).get("expectations")
    if not isinstance(arr, list) or not arr:
        return ["C0: expectations 须为非空数组 (先跑 expectations_lint)"], items
    for i, e in enumerate(arr):
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) \
                or not e["id"].strip():
            errors.append(f"C0: expectations[{i}] 缺合法 id (清单损坏)")
            continue
        desc = e.get("desc")
        items.append({"id": e["id"],
                      "desc": desc if isinstance(desc, str) else "—",
                      "forbidden": bool(e.get("forbidden_texts")
                                        or e.get("forbidden_patterns"))})
    return errors, items


def diff(fsd_reqs, exp_items, waived):
    """三判纯函数 (IO 归调用方)。fsd_reqs=[{id,title}], exp_items=
    [{id,desc,forbidden}] (normalize_expectations 产物), waived={id: waiver}.
    返回 (errors, warnings, table_rows)。
    table_rows: 双侧并排 [{id, fsd_title, exp_desc, forbidden, asserted,
    waived, orphan}]——FSD 需求全列 + 孤儿断言成行 (F-114/H-2)。"""
    errors = []
    warnings = []
    fsd_ids = [r["id"] for r in fsd_reqs]
    fsd_set = set(fsd_ids)
    exp_by_id = {}
    for it in exp_items:
        exp_by_id.setdefault(it["id"], it)
    exp_ids = list(exp_by_id.keys())
    exp_set = set(exp_ids)

    # C3 先行: 豁免完备性 (孤儿豁免 / 缺 reason / 缺证据指向)
    for wid, w in sorted(waived.items()):
        if wid not in fsd_set:
            errors.append(f"C3: 豁免 {wid} 无对应 FSD 需求 (孤儿豁免)")
        for field in ("reason", "evidence"):
            v = w.get(field)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"C3: 豁免 {wid} 缺 {field} — 豁免必须给理由与证据指向")

    # C1 孤儿断言 (豁免只服务 C2 欠账; 有断言无出处不属可豁免面——孤儿豁免
    # 本身就是 C3 违规, 见 spec 勘误注)
    for eid in exp_ids:
        if eid not in fsd_set:
            errors.append(f"C1: 断言 {eid} 无 FSD 出处 (孤儿断言)")

    # C2 需求无断言 (xfail 已建条目算"有断言", 不欠账)。
    # NFR (性能/构建约束) 无覆盖 → WARNING 非 ERROR——一刀切判死会制造假红
    # (首跑实证: mpu6050-oled NFR×4)。现役 FSD 无 Must/Should 标注,
    # 分级判据按 FR/NFR 前缀 (F-114/M-4 登记: spec 原文 Must/Should 分级
    # 未实现, 以本句为准)。
    covered = exp_set | set(waived.keys())
    for rid in fsd_ids:
        if rid in covered:
            continue
        if rid.startswith("FR-"):
            errors.append(f"C2: 需求 {rid} 无断言且无豁免 (欠账)")
        else:
            warnings.append(f"C2: NFR {rid} 无断言无豁免 (非功能约束, 如实提醒)")

    # 对照表 (漂移审读面): FSD 侧全列 + 孤儿断言行
    title_by_id = {r["id"]: r["title"] for r in fsd_reqs}
    rows = []
    for rid in fsd_ids:
        it = exp_by_id.get(rid)
        rows.append({"id": rid, "fsd_title": title_by_id.get(rid, ""),
                     "exp_desc": it["desc"] if it else "—",
                     "forbidden": bool(it and it["forbidden"]),
                     "asserted": rid in exp_set,
                     "waived": rid in waived, "orphan": False})
    for eid in exp_ids:
        if eid not in fsd_set:
            it = exp_by_id[eid]
            rows.append({"id": eid, "fsd_title": "—",
                         "exp_desc": it["desc"], "forbidden": it["forbidden"],
                         "asserted": True, "waived": False, "orphan": True})
    return errors, warnings, rows


def reconcile(fsd_text, manifest_obj):
    """对账主体 (纯数据进, 结构化结果出)。manifest 非 dict 报 C0 不崩。"""
    if not isinstance(manifest_obj, dict):
        return {"verdict": "error",
                "errors": ["C0: expectations 顶层须为 JSON 对象"],
                "warnings": [], "table": []}
    reqs = parse_fsd(fsd_text)
    c0_errors, exp_items = normalize_expectations(manifest_obj)
    w_errors, waived = validate_waived(manifest_obj)
    errors, warnings, rows = diff(reqs, exp_items, waived)
    errors = w_errors + c0_errors + errors
    verdict = "error" if errors else ("warn" if warnings else "clean")
    return {"verdict": verdict, "errors": errors, "warnings": warnings,
            "table": rows,
            "counts": {"fsd": len(reqs), "assertions": len(exp_items),
                       "waived": len(waived)}}


def _read_project(project):
    """返回 (fsd_text|None, manifest|None, notes, fatal_errors)。
    fatal_errors: 文件在但读不动/非 JSON——属损坏输入, verdict 应 error
    而非 skipped (F-114/H-1)。"""
    notes = []
    fatal = []
    fsd_rel = "docs/FSD.md"
    cfg_p = os.path.join(project, ".workbench", "config.json")
    if os.path.isfile(cfg_p):
        try:
            with open(cfg_p, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and isinstance(cfg.get("fsd_path"), str) \
                    and cfg["fsd_path"].strip():
                fsd_rel = cfg["fsd_path"].strip()      # F-114/M-1
        except Exception:
            notes.append("config.json 不可读, fsd_path 走默认 (仅提醒)")
    fsd_path = os.path.join(project, fsd_rel)
    if not os.path.isfile(fsd_path):
        notes.append(f"FSD 不存在: {fsd_path}")
        fsd_text = None
    else:
        with open(fsd_path, encoding="utf-8") as f:
            fsd_text = f.read()
    exp_path = os.path.join(project, ".workbench", "expectations.json")
    if not os.path.isfile(exp_path):
        notes.append(f"expectations.json 不存在: {exp_path} (legacy 工程? 无对账面)")
        return fsd_text, None, notes, fatal
    try:
        with open(exp_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fatal.append(f"C0: expectations.json 不可解析: {e}")
        manifest = None
    return fsd_text, manifest, notes, fatal


def run_coverage(project):
    """工程级对账, 返回 {project, verdict, errors, warnings, table, notes}。

    verdict ∈ clean/warn/error/skipped。输入**缺失** (无 FSD 或无 manifest)
    判 **skipped** 而非 error——存量工程未建 FSD 是现状非事故, 谎红会让
    HANDOFF 秒检对 legacy 工程不可用; "无对账面"如实进 warnings。输入**损坏**
    判 error (F-114/H-1: 坏文件必须响, 不裸崩也不假装跳过)。"""
    fsd_text, manifest, notes, fatal = _read_project(project)
    if fatal:
        return {"project": project, "verdict": "error", "errors": fatal,
                "warnings": [], "table": [], "notes": notes}
    if manifest is None or fsd_text is None:
        return {"project": project, "verdict": "skipped",
                "errors": [], "warnings": [f"无对账面: {n}" for n in notes],
                "table": [], "notes": notes}
    result = reconcile(fsd_text, manifest)
    result["project"] = project
    result["notes"] = notes
    return result


def _print_human(result):
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
        if r.get("orphan"):
            mark = "⚠孤儿"
        elif r.get("asserted"):
            mark = "✓断言"
        elif r.get("waived"):
            mark = "⊘豁免"
        else:
            mark = "✗欠账"
        neg = " ⛔负" if r.get("forbidden") else ""
        line = f"  [{mark}] {r['id']:<16} FSD: {r['fsd_title']}"
        if r.get("exp_desc") and r["exp_desc"] != "—":
            line += f"  ⇐ 断言: {r['exp_desc']}{neg}"
        print(line)
    if not result["errors"] and not result["warnings"]:
        print("  对账全绿")


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
    ap.add_argument("--project", default=None, help="工程根 (读 FSD + "
                    ".workbench/expectations.json, fsd 路径可经 config "
                    "fsd_path 覆盖)")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    if args.project:
        result = run_coverage(os.path.abspath(args.project))
    elif args.fsd and args.manifest:
        try:
            with open(args.fsd, encoding="utf-8") as f:
                fsd_text = f.read()
            with open(args.manifest, encoding="utf-8") as f:
                mobj = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"错误: 输入不可读: {e}", file=sys.stderr)
            return 2
        result = reconcile(fsd_text, mobj)
        result["project"] = args.fsd
        result["notes"] = []
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
        _print_human(result)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
