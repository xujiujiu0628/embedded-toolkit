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

    纯函数无 IO, 返回违规 (code, msg) 二元组列表 (空 = 干净)。code ∈
    {"E10": 结构/非法正则, "E11": 自杀配置}——码随判据走, 不靠调用方嗅探
    文案 (F-114/L-1: 子串路由在文案一改即静默错码)。loader 违规即抛
    ExpectationError、lint 直取 code——判据单一事实源 (F-029)。
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
            errors.append(("E10", f"{eid}: {key} 须为非空字符串数组"))
    if not errors and isinstance(item.get("forbidden_patterns"), list):
        for p in item["forbidden_patterns"]:
            if isinstance(p, str) and p:
                try:
                    re.compile(p)
                except re.error as e:
                    errors.append(("E10",
                                   f"{eid}: forbidden_patterns 非法正则 {p!r}: {e}"))
    # E11 自杀配置: 同一字面串既要求出现又要求出现即死 → 条目永远 FAIL,
    # 典型为复制粘贴错位 (与 E9 min>max 同类: verify 运行期不报错, 只有提前查得出)
    # F-114/M-3: texts×forbidden_texts 与 patterns×forbidden_patterns 双侧都查
    # (spec F-112 §3.3 原文含 patterns, 初版只落了一半)
    for pos_key, neg_key in (("texts", "forbidden_texts"),
                             ("patterns", "forbidden_patterns")):
        pos = set(item.get(pos_key, []) or [])
        for t in item.get(neg_key, []) or []:
            if isinstance(t, str) and t in pos:
                errors.append(("E11", f"{eid}: {t!r} 同现于 {pos_key} 与 "
                               f"{neg_key} — 永远 FAIL"))
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
            raise ExpectationError(fb_errs[0][1])  # (code,msg) 元组, 取 msg
        # F-148 ②: ordered (按序命中) — 结构校验, 默认 False 零回归
        od = item.get("ordered")
        if od is not None and not isinstance(od, bool):
            raise ExpectationError(f"{eid}: ordered 须为布尔")
        # F-148 ③: record (命名捕获组 → records 数组) — 结构/搭配/互斥/命名组
        # 四重校验 (与 lint E12 同源; record 与 capture_group/min/max 互斥是
        # 工单钉死的语义: 前者全量记录, 后者首匹配定界, 二选一)
        rec = item.get("record")
        if rec is not None:
            if (not isinstance(rec, list) or not rec
                    or not all(isinstance(s, str) and s.strip() for s in rec)):
                raise ExpectationError(
                    f"{eid}: record 须为非空字符串数组 (命名捕获组名)")
            if not ok_pats:
                raise ExpectationError(f"{eid}: record 须与 patterns 搭配")
            if item.get("capture_group") is not None \
                    or item.get("min") is not None \
                    or item.get("max") is not None:
                raise ExpectationError(
                    f"{eid}: record 与 capture_group/min/max 互斥 — 记录值用 "
                    "record 全量落 records 数组, 定界断言用 capture_group, 二选一")
            groups = set(re.compile(pats[0]).groupindex)
            missing = [n for n in rec if n not in groups]
            if missing:
                raise ExpectationError(
                    f"{eid}: record 引用未定义的命名捕获组: {missing} "
                    f"(patterns[0] 须写 (?P<{missing[0]}>...) 形态)")
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
    返回 (matched, 失败细节)。

    F-148 ②: 条目带 ordered=true 时按序命中 — texts 依次 find(从上一命中
    之后), patterns 依次 search(从上一 match.end() 之后); 默认 False,
    既有"任意位置命中"语义零改动。"""
    ordered = bool(item.get("ordered"))
    texts = item.get("texts", [])
    if ordered and texts:
        pos = 0
        for t in texts:
            i = output.find(t, pos)
            if i < 0:
                return False, f"ordered: {t!r} 未在位置 {pos} 之后按序命中"
            pos = i + len(t)
    else:
        missing = [t for t in texts if t not in output]
        if missing:
            return False, f"missing texts: {missing}"
    first = None
    if ordered and item.get("patterns"):
        pos = 0
        for j, pat in enumerate(item.get("patterns", [])):
            m = re.compile(pat).search(output, pos)
            if not m:
                return False, (f"ordered: pattern {pat!r} 未在位置 {pos} 之后"
                               "按序命中")
            if j == 0:
                first = m
            pos = m.end()
    else:
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


def _extract_records(item, output):
    """F-148 ③: record 命名捕获组 — patterns[0] 全量匹配, 每次匹配一行
    {组名: 值} 记录 (字符串原样, 不做数值整形)。无 record 键返回 None。"""
    names = item.get("record")
    if not names:
        return None
    return [{n: m.group(n) for n in names}
            for m in re.finditer(item["patterns"][0], output)]


def evaluate_expectations(output, expectations):
    """四态判定纯函数 (spec §4): PASS=匹配&非xfail; XFAIL=未匹配&xfail;
    XPASS=匹配&xfail(严格红); FAIL=未匹配&非xfail。
    verdict="ok" 当且仅当所有 status ∈ {pass, xfail}。无 IO, 可单测。

    F-112 负断言优先律: forbidden 命中 → 无条件 FAIL (先于正向求值,
    亦先于 XPASS/XFAIL——禁止后果出现时, 无论该条目是否实现/是否欠条,
    都不存在"符合预期"的解释空间)。

    F-148 ① 行终止符语义 (防早判): 判定发生在采集窗超时后, 全文 (含
    未终止尾行) 都参与匹配——"未终止的值超时才判"。命中若仅存在于未终止
    尾行 (存在已终止前缀而命中避开它), 结果行标注 `unterminated_hit:
    true`: 值可能在窗口关闭瞬间被截断 (如 "mv=319" 实为 3192 的前缀),
    消费方 (CI/agent) 对数值断言应谨慎采信; 判定状态不变, 既有清单零
    回归。全文无任何终止行时不标注 (无相对信号可归因)。要消除标注,
    让固件输出行终止符 (printf 带 \\n)。

    F-148 ③: 带 record 的条目, 结果行附 `records` 数组 (patterns[0] 每次
    匹配一行 {组名: 值}); 返回值聚合 `records` = [{id, 组名: 值}, ...] 平铺。
    """
    results = []
    records = []
    committed = output[:output.rfind("\n") + 1]   # 已终止前缀 (含末 \\n)
    for item in expectations:
        hit = _forbidden_hit(item, output)
        if hit is not None:
            results.append({"id": item["id"], "status": "fail", "detail": hit})
            continue
        ok, detail = _expect_matched(item, output)
        # F-148 ①: 存在已终止前缀、而命中避开了它 = 值落在未终止尾行。
        # 全文无任何终止行时不标注 — 相对信号才有截断归因力 (半主机收尾
        # 本就常无换行), 也让既有清单零回归。
        unterminated = False
        if ok and committed:
            ok_committed, _ = _expect_matched(item, committed)
            unterminated = not ok_committed
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
        if unterminated:
            r["unterminated_hit"] = True
        entries = _extract_records(item, output)
        if entries is not None:
            r["records"] = entries
            records.extend({"id": item["id"], **e} for e in entries)
        results.append(r)
    verdict = "ok" if all(r["status"] in ("pass", "xfail") for r in results) else "fail"
    return {"results": results, "verdict": verdict,
            "xpass_ids": [r["id"] for r in results if r["status"] == "xpass"],
            "records": records}
