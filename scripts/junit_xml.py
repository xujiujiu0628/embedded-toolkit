r"""JUnit XML 报告生成 (F-147, 总工单 v2 N-1) — verify --junit-xml 的底座。

动机: CI 的测试结果面板只认 JUnit XML; verify 的四态判定 (pass/xfail/
xpass/fail) 与 preflight 拒绝需要映射进 <testsuite> 才能在 GitHub Actions
test report 里可见。本模块独立于 verify.py —— verify 只做最小接线
(argparse + 唯一出口调用), 生成逻辑全部住这里以便纯函数测试。

映射契约 (总工单 v2 N-1 全文):
  - expectations 逐条 → <testcase>: pass → 直认; fail → <failure type="fail">;
    xpass → <failure type="xpass"> (XPASS 判红, 提示翻转 xfail);
    xfail 未翻转 → <skipped> (文档明写: xfail 是欠条不是通过, 报告里以
    skipped 呈现, 不计入 failures);
  - lint/preflight 拒绝 (build/flash/capture 失败、hardfault 等"没跑到
    判定"的状态): 期望清单逐条 → <skipped> + 一条 preflight <error> case
    (status/error 文本点名拒绝原因);
  - 只写实测时间: testsuite time = result.elapsed_sec (正数才写);
    testcase 不编造 per-case 时长 (无实测数据就不得虚构)。
  - 写失败不抛 — 返回错误信封给 verify 记 junit_xml_error 并拉低退出码;
    父目录自动创建。
"""
from __future__ import annotations

import os
from xml.etree import ElementTree as ET

from expectations import ExpectationError, load_expectations

SUITE_NAME = "embedded-toolkit verify"
_CLASSNAME = "expectations"


def build_cases(result: dict, expectation_ids: list[str] | None) -> list[dict]:
    """result + 期望 ID 清单 → testcase 描述列表 (纯函数)。

    每项: {name, status, kind: "case"|"preflight_error"|"skipped",
           message?, failure_type?}。"""
    cases: list[dict] = []
    verify_s = (result.get("steps") or {}).get("verify") or {}
    rows = verify_s.get("results")

    if isinstance(rows, list) and rows:
        for row in rows:
            status = row.get("status")
            case = {"name": str(row.get("id", "?")), "status": status,
                    "classname": _CLASSNAME}
            if status == "pass":
                cases.append({**case, "kind": "case"})
            elif status == "xfail":
                cases.append({**case, "kind": "skipped",
                              "message": ("xfail 未翻转 (欠条, 不计失败)"
                                          + (f": {row['detail']}"
                                             if row.get("detail") else ""))})
            elif status == "xpass":
                cases.append({**case, "kind": "failure",
                              "failure_type": "xpass",
                              "message": ("XPASS 判红 — 实现已落地, "
                                          "请翻转对应 xfail 后重跑")})
            else:   # fail
                cases.append({**case, "kind": "failure",
                              "failure_type": "fail",
                              "message": row.get("detail") or "期望未命中"})
        return cases

    # 没跑到判定 (preflight 拒绝 / hardfault / legacy 模式): 期望逐条 skipped
    # + 一条 preflight error 点名原因。
    for eid in expectation_ids or []:
        cases.append({"name": str(eid), "status": "skipped",
                      "classname": _CLASSNAME, "kind": "skipped",
                      "message": "verify 未跑到判定阶段 (preflight 拒绝)"})
    status = result.get("status", "unknown")
    error_text = result.get("error") or status
    cases.append({"name": "preflight", "classname": "verify",
                  "status": "error", "kind": "preflight_error",
                  "message": f"verify status={status}: {error_text}"[:300]})
    return cases


def render_xml(cases: list[dict], suite_time: float | None) -> str:
    """cases → JUnit XML 文本 (ElementTree 序列化, 转义交给标准库)。"""
    failures = sum(1 for c in cases if c.get("kind") == "failure")
    errors = sum(1 for c in cases if c.get("kind") == "preflight_error")
    skipped = sum(1 for c in cases if c.get("kind") == "skipped")
    attrs = {"name": SUITE_NAME, "tests": str(len(cases)),
             "failures": str(failures), "errors": str(errors),
             "skipped": str(skipped)}
    if isinstance(suite_time, (int, float)) and suite_time > 0:
        attrs["time"] = f"{suite_time:.1f}"   # 只写实测时间
    suite = ET.Element("testsuite", attrs)
    for c in cases:
        tc = ET.SubElement(suite, "testcase",
                           {"name": c["name"], "classname": c["classname"]})
        kind = c.get("kind")
        if kind == "failure":
            ET.SubElement(tc, "failure",
                          {"type": c.get("failure_type", "fail"),
                           "message": c.get("message", "")})
        elif kind == "preflight_error":
            ET.SubElement(tc, "error",
                          {"type": "preflight",
                           "message": c.get("message", "")})
        elif kind == "skipped":
            ET.SubElement(tc, "skipped",
                          {"message": c.get("message", "skipped")})
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(suite, encoding="unicode"))


def _load_expectation_ids(workspace: str | None) -> list[str] | None:
    """从 workspace 载期望清单 ID (preflight skipped 用); 载不到 → None。"""
    if not workspace:
        return None
    try:
        expectations = load_expectations(workspace)
    except (ExpectationError, OSError, ValueError):
        return None
    if not expectations:
        return None
    return [e.get("id", "?") for e in expectations]


def write_junit_report(result: dict, out_path: str,
                       workspace: str | None = None) -> dict:
    """写 JUnit 报告; 任何失败都不抛 — 返回 {ok, path?, error?} 信封,
    由 verify 记 junit_xml_error 并拉低退出码 (总工单 v2 N-1)。"""
    try:
        parent = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(parent, exist_ok=True)   # 父目录自动创建
        cases = build_cases(result, _load_expectation_ids(workspace))
        elapsed = result.get("elapsed_sec")
        suite_time = elapsed if isinstance(elapsed, (int, float)) else None
        xml_text = render_xml(cases, suite_time)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_text)
    except OSError as e:
        return {"ok": False, "error": f"JUnit 报告写失败: {e}"}
    except Exception as e:   # noqa: BLE001  (报告是旁路产物, 不得炸主流程)
        return {"ok": False, "error": f"JUnit 报告生成失败: "
                                      f"{type(e).__name__}: {e}"}
    return {"ok": True, "path": out_path,
            "cases": len(build_cases(result, _load_expectation_ids(workspace)))}
