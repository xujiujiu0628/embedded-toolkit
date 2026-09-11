"""期望契约层 (F-055) — verify.py 拆分件第一步（防腐方案 §3.3 步骤 2）.

职责: expectations.json 的加载与前置拦截（load_expectations）、四态判定纯函数
（evaluate_expectations）、判绿契约哈希（contract_hashes）。全部仅依赖标准库，
不做 machine 读取、不 import verify（分层禁令 #2）——import 卫生由
test_import_hygiene 经由 verify 的 import 链覆盖；行为由 test_verify_expectations
（34 例）与 test_contract_fixtures 经由 verify 再导出面钉死。

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


def check_forbidden_fields(item):
    """F-112: 负断言字段 (forbidden_texts / forbidden_patterns) 的结构与自杀配置校验。

    纯函数无 IO, 返回违规消息列表 (空 = 干净)。loader 违规即抛
    ExpectationError、lint 落 E10/E11 码——判据单一事实源 (F-029)。
    语义: forbidden_* 作用于整段捕获输出, 任一命中则该条目 FAIL 优先于
    正向匹配与 XPASS (spec 2026-09-11-negative-assertion-schema §2)。
    """
    errors = []
    eid = item.get("id") or "<no-id>"
    for key in ("forbidden_texts", "forbidden_patterns"):
        v = item.get(key)
        if v is None:
            continue
        if not isinstance(v, list) or not v or \
                not all(isinstance(s, str) and s for s in v):
            errors.append(f"{eid}: {key} 须为非空字符串数组")
    if not errors and isinstance(item.get("forbidden_patterns"), list):
        for p in item["forbidden_patterns"]:
            if isinstance(p, str) and p:
                try:
                    re.compile(p)
                except re.error as e:
                    errors.append(f"{eid}: forbidden_patterns 非法正则 {p!r}: {e}")
    # E11 自杀配置: 同一字面串既要求出现又要求出现即死 → 条目永远 FAIL,
    # 典型为复制粘贴错位 (与 E9 min>max 同类: verify 运行期不报错, 只有提前查得出)
    pos = set(item.get("texts", []) or [])
    for t in item.get("forbidden_texts", []) or []:
        if isinstance(t, str) and t in pos:
            errors.append(f"{eid}: {t!r} 同现于 texts 与 forbidden_texts — 永远 FAIL")
    return errors


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
        fb_errs = check_forbidden_fields(item)     # F-112: 结构+自杀配置, 与 lint E10/E11 同源
        if fb_errs:
            raise ExpectationError(fb_errs[0])
    return data["expectations"]


def _forbidden_hit(item, output):
    """F-112: 负断言求值 — 返回首个命中描述, 无命中返回 None。

    作用域 = 整段捕获输出 (spec §2): texts 子串 / patterns re.search。
    注意尊重调用方正则的完全控制权: 不自动注入 MULTILINE/锚定——
    "行首锚定" 是文档示范的写法纪律, 工具强制会重演 L-2 式误杀 (F-106 教训)。
    """
    for t in item.get("forbidden_texts", []) or []:
        if t in output:
            return f"forbidden hit: {t!r}"
    for p in item.get("forbidden_patterns", []) or []:
        if re.search(p, output):
            return f"forbidden hit: pattern {p!r}"
    return None


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
    verdict="ok" 当且仅当所有 status ∈ {pass, xfail}。无 IO, 可单测。

    F-112 负断言优先律: forbidden 命中 → 无条件 FAIL (先于正向求值,
    亦先于 XPASS/XFAIL——禁止后果出现时, 无论该条目是否实现/是否欠条,
    都不存在"符合预期"的解释空间)。
    """
    results = []
    for item in expectations:
        hit = _forbidden_hit(item, output)
        if hit is not None:
            results.append({"id": item["id"], "status": "fail", "detail": hit})
            continue
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
