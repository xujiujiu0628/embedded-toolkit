"""变异枪原语 (F-235): 改一处 → verify 必须红在指定 id → 还原 → 必须绿。

设计要点:
  - 只改一处、只改一次: find 必须在目标文件里出现且唯一, 否则拒绝执行
    (错误里带实际次数, 便于定位——出现 0 次多半是写错了串, 多次则说明
    该处不是唯一锚点, 变异会咬到别的地方)。
  - 备份用内存副本 + try/finally 还原, 不依赖 git (工程可能未提交干净,
    也不能假设变异期间工作树是干净的)。
  - 读写一律 `newline=""` + `errors="surrogateescape"`: 本工作区存在
    CR-only 行尾的工程件 (如 ch32v307-hello/Ld/Link.ld), 默认的换行翻译
    会在"改一处再还原"时把整份文件的换行改掉, 还原后仍与原始字节不同。
    newline="" 关掉翻译, surrogateescape 保住非法字节, 二者合起来保证
    字节级无损往返。
  - run_verify 由调用方注入, 单测可替换; CLI 走 subprocess 调 verify.py。
    run_verify 抛异常时 finally 照常还原, 异常原样上抛 (不吞, 调用方自己
    决定怎么报)。
  - verify 的 per-id 结果行在 `steps.verify.results` (verify.py:1464 → :1491),
    顶层没有 results; 顶层 results 只认作注入式 runner 的便利形状。legacy 工程
    (expect/expect_patterns) 压根没有 per-id 行, 只能显式拒绝——不能落成
    「未变红」这种负面结论。
  - verify 自身失败 (status ∈ error/internal_error/interrupted) 单独报并带原文,
    否则工具会把「没判成」伪装成「没有变红」, 属于伪造证据。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# verify 自身没跑成 (配置错 / 内部异常 / 用户中断) 的 status 取值
_VERIFY_BROKEN = ("error", "internal_error", "interrupted")


def _read_text(path: str) -> str:
    """字节级读回: newline="" 不做换行翻译, surrogateescape 保住非法字节。"""
    with open(path, encoding="utf-8", errors="surrogateescape",
              newline="") as f:
        return f.read()


def _write_text(path: str, text: str) -> None:
    """字节级写回: 与 _read_text 对称, 保证原件能被逐字节还原。"""
    with open(path, "w", encoding="utf-8", errors="surrogateescape",
              newline="") as f:
        f.write(text)


def _result_rows(payload: dict):
    """取 per-id 结果行; 拿不到 (legacy 信封) 返回 None。

    真实 verify.py 把结果行挂在 steps.verify.results (verify.py:1464 → :1491);
    顶层 results 只是注入式 runner 的便利形状, 两处都没有才算「没有 id 级断言」。
    """
    inner = (payload.get("steps") or {}).get("verify") or {}
    rows = inner.get("results")
    if rows is None:
        rows = payload.get("results")
    return rows


def _detail(payload: dict, limit: int = 300) -> str:
    """截取 verify 自报的错误原文 (可引用), 供失败信息携带。"""
    txt = payload.get("error") or payload.get("message") or ""
    return str(txt).strip()[-limit:]


def mutate_and_run(project: str, expect_red: str, edit: str,
                   find: str, replace: str, run_verify, timeout: int) -> dict:
    """改一处 → 该期望必须变红 → 还原 → 必须整体复绿。

    project: 工程根目录; edit: 相对工程根的目标文件。
    expect_red: 变异后必须变红的期望 id。
    run_verify: 无参可调用, 返回 verify 的 JSON (含 status / steps.verify.results)。
    timeout: 由调用方注入的 runner 自行消费 (本函数不用), 保留以便签名稳定。

    返回 {"ok": bool, ...}; 不 ok 时必有 "error"。run_verify 抛出的异常
    不在此拦截, 但文件已由 finally 还原。
    """
    path = os.path.join(project, edit)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"目标文件不存在: {path}"}
    if not find:
        return {"ok": False, "error": "find 串为空 (拒绝执行: 空串会命中一切位置)"}
    original = _read_text(path)
    hits = original.count(find)
    if hits != 1:
        return {"ok": False,
                "error": f"find 串在 {edit} 中出现 {hits} 次 (须唯一)"}
    try:
        _write_text(path, original.replace(find, replace, 1))
        red = run_verify()
        if red.get("status") in _VERIFY_BROKEN:
            return {"ok": False,
                    "error": f"变异后 verify 自身失败 "
                             f"(status={red.get('status')}): {_detail(red)}"}
        rows = _result_rows(red)
        if rows is None:
            return {"ok": False,
                    "error": f"{edit} 所在工程没有 id 级断言 (verify 未返回 "
                             f"per-id 结果行): 无法判定 {expect_red} 是否变红。"
                             f"legacy expect/expect_patterns 工程请改用显式断言"}
        red_ids = [r["id"] for r in rows if r.get("status") == "fail"]
        if expect_red not in red_ids:
            return {"ok": False,
                    "error": f"变异后未变红在 {expect_red} (实际红: {red_ids})"}
    finally:
        _write_text(path, original)
    green = run_verify()
    if green.get("status") in _VERIFY_BROKEN:
        return {"ok": False,
                "error": f"还原后 verify 自身失败 "
                         f"(status={green.get('status')}): {_detail(green)}"}
    if green.get("status") != "ok":
        msg = f"还原后未转绿: status={green.get('status')}"
        if _detail(green):
            msg += f" ({_detail(green)})"
        return {"ok": False, "error": msg}
    return {"ok": True, "expect_red": expect_red, "edit": edit,
            "find": find, "replace": replace,
            "summary": f"mutation bite OK: {edit} '{find}'→'{replace}' "
                       f"red on {expect_red}, restored green"}


def _run_verify_cli(project: str, timeout: int):
    """把 verify.py 的 CLI 包成 run_verify 回调 (非 JSON 输出降级为 error)。"""
    def run():
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "verify.py"),
             "--project", project, "--json", "--timeout", str(timeout)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            return json.loads(proc.stdout or "")
        except json.JSONDecodeError:
            # 退出码与 stderr 尾巴都留下: verify 崩掉时 traceback 才是可引证据
            tail = ((proc.stdout or "").strip() + "\n"
                    + (proc.stderr or "").strip()).strip()
            return {"status": "error", "results": [],
                    "error": f"verify.py 输出非 JSON (rc={proc.returncode}): "
                             f"{tail[-300:]}"}
    return run


def _emit(got: dict, as_json: bool) -> None:
    """输出结果 (仓内惯例: stdout 切 utf-8, 否则中文与 JSON 在 cp936 控制台被改写)。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass   # F-133/g: StringIO 等重定向流无 reconfigure — 尽力而为
    if as_json:
        print(json.dumps(got, ensure_ascii=False, indent=2), flush=True)
    else:
        print(got["summary"] if got["ok"] else f"FAIL: {got['error']}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="变异枪: 改一处 → 必须红 → 还原 → 必须绿")
    ap.add_argument("--project", required=True)
    ap.add_argument("--expect-red", required=True)
    ap.add_argument("--edit", required=True, help="相对工程根的文件路径")
    ap.add_argument("--find", required=True)
    ap.add_argument("--replace", required=True)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()
    got = mutate_and_run(args.project, args.expect_red, args.edit, args.find,
                         args.replace, _run_verify_cli(args.project, args.timeout),
                         args.timeout)
    _emit(got, args.as_json)
    return 0 if got["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
