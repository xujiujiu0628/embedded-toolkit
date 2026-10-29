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
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


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


def mutate_and_run(project: str, expect_red: str, edit: str,
                   find: str, replace: str, run_verify, timeout: int) -> dict:
    """改一处 → 该期望必须变红 → 还原 → 必须整体复绿。

    project: 工程根目录; edit: 相对工程根的目标文件。
    expect_red: 变异后必须变红的期望 id。
    run_verify: 无参可调用, 返回 verify 的 JSON (含 status / results)。
    timeout: 由调用方注入的 runner 自行消费 (本函数不用), 保留以便签名稳定。

    返回 {"ok": bool, ...}; 不 ok 时必有 "error"。run_verify 抛出的异常
    不在此拦截, 但文件已由 finally 还原。
    """
    path = os.path.join(project, edit)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"目标文件不存在: {path}"}
    original = _read_text(path)
    hits = original.count(find)
    if hits != 1:
        return {"ok": False,
                "error": f"find 串在 {edit} 中出现 {hits} 次 (须唯一)"}
    try:
        _write_text(path, original.replace(find, replace, 1))
        red = run_verify()
        red_ids = [r["id"] for r in (red.get("results") or [])
                   if r.get("status") == "fail"]
        if expect_red not in red_ids:
            return {"ok": False,
                    "error": f"变异后未变红在 {expect_red} (实际红: {red_ids})"}
    finally:
        _write_text(path, original)
    green = run_verify()
    if green.get("status") != "ok":
        return {"ok": False,
                "error": f"还原后未转绿: status={green.get('status')}"}
    return {"ok": True, "expect_red": expect_red, "edit": edit,
            "find": find, "replace": replace,
            "summary": f"mutation bite OK: {edit} '{find}'→'{replace}' "
                       f"red on {expect_red}, restored green"}


def _run_verify_cli(project: str, timeout: int):
    """把 verify.py 的 CLI 包成 run_verify 回调 (JSON 解析失败降级为 error)。"""
    def run():
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "verify.py"),
             "--project", project, "--json", "--timeout", str(timeout)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            return json.loads(proc.stdout or "")
        except json.JSONDecodeError:
            return {"status": "error", "results": [],
                    "error": (proc.stdout or "")[-300:]}
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
