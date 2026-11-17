#!/usr/bin/env python3
"""物理检查清单闸 —— verify.py 碰硬件之前，先确认"接线核过了"。

起因（2026-11-17）：我反复把解释不了的现象先归给"硬件"——ST-Link 连不上
就写"克隆片老毛病"，实际是用户自己拔的线（两次）；DHT 读不到就说"传感器
坏了"，实际是 idle-low 被钳地。物理层最难排除，也最容易先入为主。规矩写进
文档靠自觉，这个闸是机械的：**没核过清单，不许烧。**

设计：

  * 清单是工程资产 —— `.workbench/physical-checklist.json`，随工程入库。
    每条必须有 id / cat / text，可选 why（当初踩的坑）与 source（引脚事实
    的出处，如 `User/MyI2C.c:16-19`）。模板不编引脚：`--init` 只写通用的
    供电/接触/极性/拔线条目，工程专属条目要有人对着代码或图填。
  * 确认是运行时状态 —— `.workbench/state/physical-attest.json`（应被
    .gitignore 覆盖，它是"这台机器、这次接线"的事，不是代码属性）。
    记录清单内容哈希 + 时间 + 谁确认的 + 一句话说明。
  * 三种失效：没确认过 / 清单改过（哈希不符）/ 超过 TTL（默认 12h）。
  * 没配清单的工程：不拦，落 `status=skipped` + 原因，并在 verify 输出里
    显示 —— 沉默的通过和沉默的拦截一样是坏设计。
  * sim 后端（全程无探针）不适用本闸。

CLI：

  python physical_checklist.py --project P              # 看状态与条目
  python physical_checklist.py --project P --init       # 生成模板（不覆盖）
  python physical_checklist.py --project P --attest --note "板已按 FSD 接好"
  python physical_checklist.py --project P --check      # 闸的退出码，不改状态

退出码：0 通过（含未配置），1 被拦，2 用法错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CHECKLIST_REL = os.path.join(".workbench", "physical-checklist.json")
# 消息里用正斜杠: reason 会进 verify 的 JSON 输出, 被金比对钉住, 不能带平台分隔符
CHECKLIST_REL_POSIX = ".workbench/physical-checklist.json"
ATTEST_REL = os.path.join(".workbench", "state", "physical-attest.json")
DEFAULT_TTL_HOURS = 12

GENERIC_ITEMS = [
    {"id": "PWR-1", "cat": "供电",
     "text": "板子有电：3V3 轨实测 3.3V±0.15V（ST-Link 供电或外部电源），外设与 MCU 共地。",
     "why": "共地没接时一切读数都像「通信坏」，先量电源能省一整轮归因。"},
    {"id": "CON-1", "cat": "接触",
     "text": "杜邦线逐根轻拉不脱；读不到器件时先整排重插一次再查代码。",
     "why": "2026-10-08 单场三次抽风，每次都是重插杜邦线 + USB 拔插解决。"},
    {"id": "CON-2", "cat": "接触",
     "text": "SWD 四线（3V3/GND/SWDIO/SWCLK）在正确排针上，没有插偏一格。",
     "why": "SWDIO/SWCLK 插偏一格的表现是「找不到探针」，与适配器损坏极像。"},
    {"id": "POL-1", "cat": "极性",
     "text": "每个模块 VCC/GND 没接反；I2C 的 SCL/SDA、SPI 的 MOSI/MISO 按模块丝印核对。",
     "why": "反接不一定立刻冒烟，可能只是设备不上线。"},
    {"id": "PROBE-1", "cat": "拔线",
     "text": "没有别的窗口/会话/工具（另一个工程、McuBuddy、OpenOCD）占着同一个探针。"
             "连不上时先问人有没有拔线，再查环境，最后才怀疑适配器。",
     "why": "2026-08-26/27 两次把「用户自己拔的线」写成「克隆 ST-Link 间歇失联」，"
            "并写进了记忆。"},
    {"id": "DEV-1", "cat": "器件",
     "text": "被测外设本身能自检：OLED 上电有画面、传感器能读出 ID/寄存器值。",
     "why": "分不清「没数据」是链路问题还是器件问题，就会在两处来回改。"},
]


# ---------------------------------------------------------------- paths

def checklist_path(project: str) -> str:
    return os.path.join(project, CHECKLIST_REL)


def attest_path(project: str) -> str:
    return os.path.join(project, ATTEST_REL)


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_checklist(project: str):
    """清单对象；没配置返回 None。结构非法抛 ValueError。"""
    path = checklist_path(project)
    if not os.path.isfile(path):
        return None
    data = _load_json(path)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: items 为空或不是数组")
    for i, it in enumerate(items):
        for key in ("id", "cat", "text"):
            if not isinstance((it or {}).get(key), str) or not it.get(key, "").strip():
                raise ValueError(f"{path}: items[{i}] 缺 {key}")
    return data


def checklist_sha(project: str) -> str:
    """清单内容哈希 —— 按解析后的规范化 JSON 算，格式化/换行不影响。"""
    data = load_checklist(project)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ttl_hours(project: str) -> float:
    try:
        data = load_checklist(project) or {}
        return float(data.get("attest_ttl_hours", DEFAULT_TTL_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_TTL_HOURS


# ---------------------------------------------------------------- evaluate

def _parse_iso(text: str):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def evaluate(project: str, now: datetime | None = None) -> dict:
    """闸的判据。返回 {status, reason, items, ...}，status ∈
    not_configured | ok | missing | changed | expired | invalid。"""
    now = now or datetime.now().astimezone()
    try:
        data = load_checklist(project)
    except ValueError as e:
        return {"status": "invalid", "reason": str(e), "items": [], "path": checklist_path(project)}
    if data is None:
        return {"status": "not_configured",
                "reason": f"未配置 {CHECKLIST_REL_POSIX}（可用 --init 生成模板）",
                "items": [], "path": checklist_path(project)}

    items = data["items"]
    base = {"items": items, "path": checklist_path(project),
            "ttl_hours": ttl_hours(project)}

    apath = attest_path(project)
    try:
        attest = _load_json(apath)
    except (OSError, ValueError):
        base.update({"status": "missing",
                     "reason": "清单没确认过：先按下方条目核对接线，再 --attest 记录"})
        return base

    if attest.get("checklist_sha256") != checklist_sha(project):
        base.update({"status": "changed",
                     "reason": "清单在确认之后被改过，旧确认作废（哈希不符）——重新核对后 --attest"})
        return base

    stamped = _parse_iso(attest.get("attested_at", ""))
    if stamped is None:
        base.update({"status": "invalid", "reason": f"{apath}: attested_at 不是合法 ISO8601"})
        return base
    if stamped.tzinfo is None:
        stamped = stamped.astimezone()

    age = now - stamped
    limit = timedelta(hours=float(attest.get("ttl_hours", base["ttl_hours"])))
    base.update({"attested_at": attest.get("attested_at"), "by": attest.get("by", "?"),
                 "note": attest.get("note", ""), "age_hours": round(age.total_seconds() / 3600, 2)})
    if age > limit:
        base.update({"status": "expired",
                     "reason": f"确认已过期（{base['age_hours']}h > {limit.total_seconds()/3600:g}h）"
                               "——接线可能被换过，重新核对后 --attest"})
        return base
    base["status"] = "ok"
    return base


def step_physical_checklist(project: str, skip: bool = False,
                            hardware_expected: bool = True,
                            now: datetime | None = None) -> dict:
    """verify.py 的 Step 0。绝不抛异常：任何异常都降级成 skipped + 原因
    （闸自己坏掉不该把整条流水线拖死，但必须留痕）。"""
    if not hardware_expected:
        return {"status": "skipped", "reason": "sim 后端：全程无探针，不适用"}
    if skip:
        return {"status": "skipped", "reason": "--skip-physical 显式跳过（本次接线未经核对）",
                "skipped_by_flag": True}
    try:
        ev = evaluate(project, now)
    except Exception as e:  # noqa: BLE001 — 闸的失败不得炸流水线
        return {"status": "skipped", "reason": f"清单闸内部错误，已放行: {e}"}

    status = ev["status"]
    if status == "not_configured":
        return {"status": "skipped", "reason": ev["reason"]}
    if status == "ok":
        return {"status": "ok", "items": len(ev["items"]), "attested_at": ev.get("attested_at"),
                "by": ev.get("by"), "age_hours": ev.get("age_hours"),
                "ttl_hours": ev.get("ttl_hours"), "note": ev.get("note", "")}
    return {"status": "blocked", "reason": ev["reason"], "checklist_path": ev.get("path"),
            "items": ev.get("items", [])}


# ---------------------------------------------------------------- actions

def attest(project: str, note: str, by: str = "user",
           now: datetime | None = None) -> dict:
    """登记一次确认。note 必填 —— 它记录"确认了什么"，不是装饰。"""
    note = (note or "").strip()
    if not note:
        raise ValueError("--attest 必须带 --note：写下这次确认的是哪块板、按哪份接线")
    if load_checklist(project) is None:
        raise ValueError(f"没有 {CHECKLIST_REL}，先 --init 再填条目")
    now = now or datetime.now().astimezone()
    payload = {
        "checklist_sha256": checklist_sha(project),
        "attested_at": now.isoformat(timespec="seconds"),
        "ttl_hours": ttl_hours(project),
        "by": by,
        "note": note,
    }
    _dump_json(attest_path(project), payload)
    return payload


def scaffold(project: str, force: bool = False) -> str:
    path = checklist_path(project)
    if os.path.isfile(path) and not force:
        raise ValueError(f"{path} 已存在（--force 才覆盖）")
    payload = {
        "version": 1,
        "attest_ttl_hours": DEFAULT_TTL_HOURS,
        "items": GENERIC_ITEMS,
    }
    _dump_json(path, payload)
    return path


# ---------------------------------------------------------------- render

def render(ev: dict) -> str:
    out = []
    status = ev["status"]
    label = {"ok": "OK", "not_configured": "NOT CONFIGURED", "missing": "NOT ATTESTED",
             "changed": "CHECKLIST CHANGED", "expired": "ATTESTATION EXPIRED",
             "invalid": "INVALID"}.get(status, status.upper())
    out.append(f"物理检查清单: {label}")
    if ev.get("reason"):
        out.append("  " + ev["reason"])
    if status == "ok":
        out.append(f"  确认于 {ev.get('attested_at')} by {ev.get('by')} "
                   f"（{ev.get('age_hours')}h 前，TTL {ev.get('ttl_hours'):g}h）")
        if ev.get("note"):
            out.append(f"  说明: {ev['note']}")
    if ev.get("items") and status != "ok":
        out.append("")
        for it in ev["items"]:
            out.append(f"  [{it['id']}] {it['cat']}: {it['text']}")
            if it.get("source"):
                out.append(f"        出处: {it['source']}")
            if it.get("why"):
                out.append(f"        为什么: {it['why']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="物理检查清单闸")
    ap.add_argument("--project", required=True, help="工程根目录（含 .workbench/）")
    ap.add_argument("--init", action="store_true", help="生成清单模板（不覆盖已有）")
    ap.add_argument("--force", action="store_true", help="配合 --init 覆盖")
    ap.add_argument("--attest", action="store_true", help="登记一次确认")
    ap.add_argument("--note", default="", help="确认说明（--attest 必填）")
    ap.add_argument("--by", default="user", help="谁确认的（默认 user）")
    ap.add_argument("--ttl-hours", type=float, default=None, help="覆盖清单里的 TTL")
    ap.add_argument("--check", action="store_true", help="只判据，不改任何状态")
    args = ap.parse_args(argv)

    project = os.path.abspath(args.project)
    if not os.path.isdir(os.path.join(project, ".workbench")):
        print(f"错误: {project} 下没有 .workbench/，不像是工程根", file=sys.stderr)
        return 2

    try:
        if args.init:
            path = scaffold(project, force=args.force)
            print(f"已生成 {path}")
            print("下一步: 把工程专属条目（引脚/极性/器件）照代码或接线图补进 items，"
                  "核对后 --attest。")
            return 0
        if args.attest:
            if args.ttl_hours is not None:
                data = load_checklist(project) or {}
                data["attest_ttl_hours"] = args.ttl_hours
                _dump_json(checklist_path(project), data)
            payload = attest(project, args.note, by=args.by)
            print(f"已登记: {attest_path(project)}")
            print(f"  sha256={payload['checklist_sha256'][:12]}…  ttl={payload['ttl_hours']:g}h  "
                  f"note={payload['note']}")
            return 0
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    ev = evaluate(project)
    print(render(ev))
    if args.check:
        return 0 if ev["status"] in ("ok", "not_configured") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
