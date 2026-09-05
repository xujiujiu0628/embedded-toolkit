"""期望契约层 (F-055) — verify.py 拆分件第一步（防腐方案 §3.3 步骤 2）.

职责: expectations.json 的加载与前置拦截（load_expectations）、四态判定纯函数
（evaluate_expectations）、判绿契约哈希（contract_hashes）。全部仅依赖标准库，
不做 machine 读取、不 import verify（分层禁令 #2）——import 卫生由
test_import_hygiene 经由 verify 的 import 链覆盖；行为由 test_verify_expectations
（24 例）与 test_contract_fixtures 经由 verify 再导出面钉死。

wire 兼容: verify.py `from expectations import ...` 再导出，`verify.load_expectations`
等调用面不变（与 F-029 runtime_common 同款手法）。
"""
import hashlib
import json
import math
import os
import re


class ExpectationError(ValueError):
    """期望清单非法 (id 重复 / 缺 xfail_reason / texts+patterns 并存等)"""


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def contract_hashes(workspace: str, has_manifest: bool) -> dict:
    """F-018: 判绿所依据契约的字节级哈希 — 发布记录的"判绿锚点"。

    M2 给 hex 上哈希锚定了"烧的字节", 这里锚定"拿什么判的绿": results 由
    expectations.json + config.json 的具体内容产生, 记录不绑定其哈希则
    无法事后审计 results 与哪个版本的契约对应。config 取与 load_config
    同序的第一个在场 marker; expectations 仅 manifest 模式存在。"""
    out = {}
    for marker in (".workbench/config.json", ".embeddedskills/config.json"):
        p = os.path.join(workspace, marker)
        if os.path.isfile(p):
            out["config_sha256"] = _sha256_file(p)
            break
    if has_manifest:
        out["expectations_sha256"] = _sha256_file(
            os.path.join(workspace, ".workbench", "expectations.json"))
    return out


def load_expectations(workspace):
    """加载 .workbench/expectations.json (spec 2026-08-26 §3)。

    文件不存在返回 None (调用方回退 legacy config.verify);
    清单非法抛 ExpectationError, main() 捕获后退出码 1。
    """
    path = os.path.join(workspace, ".workbench", "expectations.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # JSONDecodeError 是 ValueError 但不是 ExpectationError 子类,
        # 不转译的话 main() 的 except 接不住 → 烧录后裸 traceback (审计 M1)
        raise ExpectationError(f"清单不是合法 JSON/UTF-8: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("expectations"), list) \
            or not data["expectations"]:
        raise ExpectationError("须为含非空 expectations 数组的 JSON 对象")
    seen = set()
    for i, item in enumerate(data["expectations"]):
        where = f"expectations[{i}]"
        if not isinstance(item, dict):
            raise ExpectationError(f"{where}: 须为对象")
        eid = item.get("id")
        if not isinstance(eid, str) or not eid.strip():
            raise ExpectationError(f"{where}: id 必填且非空")
        if eid in seen:
            raise ExpectationError(f"id 重复: {eid}")
        seen.add(eid)
        if not isinstance(item.get("desc"), str) or not item["desc"].strip():
            raise ExpectationError(f"{eid}: desc 必填且非空")
        texts = item.get("texts")
        pats = item.get("patterns")
        ok_texts = isinstance(texts, list) and len(texts) > 0 and \
            all(isinstance(t, str) and t for t in texts)
        ok_pats = isinstance(pats, list) and len(pats) > 0 and \
            all(isinstance(p, str) and p for p in pats)
        if ok_texts == ok_pats:  # 并存或皆缺均非法
            raise ExpectationError(f"{eid}: texts 与 patterns 须二选一(非空字符串数组)")
        if ok_pats:
            for p in pats:
                try:
                    re.compile(p)
                except re.error as e:
                    # 惰性编译会把非法正则拖到烧录后才炸 (审计 M1)
                    raise ExpectationError(f"{eid}: 非法正则 {p!r}: {e}") from e
        if item.get("xfail") and (not isinstance(item.get("xfail_reason"), str)
                                  or not item["xfail_reason"].strip()):
            raise ExpectationError(f"{eid}: xfail=true 时 xfail_reason 必填")
        cg = item.get("capture_group")
        if cg is not None and (isinstance(cg, bool) or not isinstance(cg, int) or cg < 1):
            raise ExpectationError(f"{eid}: capture_group 须为正整数")
        if cg is not None and not ok_pats:
            # texts+capture_group 组合会在评估期 first=None AttributeError (审计 M1)
            raise ExpectationError(f"{eid}: capture_group 须与 patterns 搭配")
        for bound in ("min", "max"):
            v = item.get(bound)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v)):
                # NaN 会绕过全部边界比较恒 pass (审计 M1)
                raise ExpectationError(f"{eid}: {bound} 须为有限数值")
    return data["expectations"]


def _expect_matched(item, output):
    """单条期望匹配判定 (spec §3): texts 全命中 且 patterns 全命中;
    capture_group/min/max 数值断言作用于 patterns[0] 首个 match。
    返回 (matched, 失败细节)。"""
    missing = [t for t in item.get("texts", []) if t not in output]
    if missing:
        return False, f"missing texts: {missing}"
    first = None
    for j, pat in enumerate(item.get("patterns", [])):
        m = re.search(pat, output)
        if not m:
            return False, f"pattern 未命中: {pat!r}"
        if j == 0:
            first = m
    cg = item.get("capture_group")
    if cg is not None:
        try:
            value = float(first.group(cg))
        except (IndexError, TypeError, ValueError):
            return False, f"capture_group={cg} 提取失败"
        lo = item.get("min")
        hi = item.get("max")
        if lo is not None and value < float(lo):
            return False, f"值 {value} < min {lo}"
        if hi is not None and value > float(hi):
            return False, f"值 {value} > max {hi}"
    return True, ""


def evaluate_expectations(output, expectations):
    """四态判定纯函数 (spec §4): PASS=匹配&非xfail; XFAIL=未匹配&xfail;
    XPASS=匹配&xfail(严格红); FAIL=未匹配&非xfail。
    verdict="ok" 当且仅当所有 status ∈ {pass, xfail}。无 IO, 可单测。"""
    results = []
    for item in expectations:
        ok, detail = _expect_matched(item, output)
        xfail = bool(item.get("xfail"))
        if ok and not xfail:
            status = "pass"
        elif ok and xfail:
            status = "xpass"
        elif not ok and xfail:
            status = "xfail"
        else:
            status = "fail"
        r = {"id": item["id"], "status": status}
        if detail and status in ("fail", "xpass"):
            r["detail"] = detail
        results.append(r)
    verdict = "ok" if all(r["status"] in ("pass", "xfail") for r in results) else "fail"
    return {"results": results, "verdict": verdict,
            "xpass_ids": [r["id"] for r in results if r["status"] == "xpass"]}
