#!/usr/bin/env python3
"""scripts/ 覆盖缺口 lint — 取代旧的"行数红线"假命题 (F-049, 2026-09-02 方案四-3).

为什么替换"行数红线":
  - 行数是假命题: 一个 200 行 const array 和一个 200 行状态机, 风险天差地别
  - 工程师为了过红线把一个文件拆成三个, 反向劣化可读性
  - 真正的高风险点 (没测试的关键逻辑) 反过来过得很开心

覆盖缺口是真问题:
  - 工程师加了新模块, 忘了给测试加 hook, PC 测试编译过/运行过/但路径没测
  - 现在要等真机复现才发现 → 一周后

判定口径 (F-072 修订, 2026-09-08):

  旧口径 (F-049) 只看"tests 是否直接 import 该模块名", 与真实行覆盖率双向脱节:
    假阳: expectations.py 有 24 例测试, 但都经 verify 再导出 (import verify),
          旧口径把它报成"未覆盖", 而真实覆盖 95%;
    假阴: 模块仅被 import 但逻辑从未执行, 旧口径算"已覆盖"。

  新口径双模式:
  1. static-reachability (默认, 零依赖): seeds = tests 直接 import 的模块名,
     沿 scripts 内部 import 图做可达闭包 —— 复现本仓"拆分件再导出"惯例
     (F-029/F-055~F-061) 的间接覆盖。仍是静态近似: "可达"≠"每行都执行过"。
  2. coverage-data (--coverage-data 指向 coverage 的 .coverage 数据文件):
     用 coverage 包逐文件重算 executed/stmts, 文件级"是否至少执行过一条语句"
     与真实行覆盖率同源 —— 这是与真实覆盖率一致的正解, 静态模式是它的
     零依赖下位替代。

用法:
  python scripts/coverage_lint.py                          # 静态模式: 报告 + exit 0
  python scripts/coverage_lint.py --strict                 # 门禁: 发现未覆盖 exit 1
  python scripts/coverage_lint.py --json                   # JSON 输出 (含 mode 字段)
  python scripts/coverage_lint.py --coverage-data .coverage # 真实覆盖比对
  python scripts/coverage_lint.py --scripts-dir <d> --tests-dir <d>

退出码: 0 = 干净/仅报告; 1 = --strict 且有未覆盖; 2 = 用法/环境错误
(含 --coverage-data 给了但 coverage 包缺失或数据文件不存在)
"""
import argparse
import ast
import json
import os
import sys


# 工具自检豁免: coverage_lint.py 自己的测试就是 coverage_lint_test.py
# 豁免名单也接受 "未来要被新工具的测试覆盖" 之类, 当前只豁免自身
SELF_EXEMPT = {"coverage_lint.py"}

# 目录豁免: 2026-09-05 (F-067b) Keil 退役区拆 archive 后, legacy/ 目录
# 保留为空 (见 scripts/legacy/README.md), 不再有受跟踪文件。未来再有
# 退役工具置入 legacy/ 时按需重新加入此豁免, 避免误报。
DIR_EXEMPT: set[str] = set()


def _iter_script_files(scripts_dir: str):
    if not os.path.isdir(scripts_dir):
        return
    for root, dirs, files in os.walk(scripts_dir):
        dirs[:] = [d for d in dirs if d not in DIR_EXEMPT]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def _ast_parse(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return ast.parse(f.read(), filename=path)
    except (SyntaxError, ValueError):
        return None


def _import_roots(tree) -> set[str]:
    """取一棵 AST 里全部 import 目标的根段 (与 _find_referenced_modules 同规则)."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod:
                    mods.add(root_mod)
        elif isinstance(node, ast.ImportFrom):
            target = None
            if node.module:
                target = node.module.split(".")[0]
            elif node.level > 0 and node.names:
                target = node.names[0].name.split(".")[0]
            if target:
                mods.add(target)
    return mods


def _find_referenced_modules(tests_dir: str) -> set[str]:
    """扫 tests_dir 下所有 .py, 提取 import / from-import 的模块名集合.

    用 AST 而非正则: 抗 import 跨行 / 字符串 / 注释干扰.
    语法错不抛, 跳过该文件.
    """
    mods: set[str] = set()
    if not os.path.isdir(tests_dir):
        return mods
    for root, _, files in os.walk(tests_dir):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            tree = _ast_parse(os.path.join(root, fn))
            if tree is None:
                continue
            mods |= _import_roots(tree)
    return mods


def _internal_import_graph(scripts_dir: str) -> dict[str, set[str]]:
    """scripts 内部 import 图: {模块名 stem: {它 import 的本仓脚本 stem}}.

    F-072: 复现"拆分件再导出"的间接覆盖链 (tests → verify → expectations)。
    只收 scripts_dir 树内真实存在的模块名, 外部依赖 (os/json/serial…) 不进图。
    子目录文件按 stem 记键 (与 _find_uncovered_scripts 的 stem 匹配口径一致);
    跨目录同名 stem 属已知的静态近似误差, 本工具如实声明不追求精确。
    """
    graph: dict[str, set[str]] = {}
    known: set[str] = set()
    paths: dict[str, str] = {}
    for path in _iter_script_files(scripts_dir):
        stem = os.path.splitext(os.path.basename(path))[0]
        known.add(stem)
        paths[stem] = path
    for stem, path in paths.items():
        tree = _ast_parse(path)
        if tree is None:
            graph[stem] = set()
            continue
        graph[stem] = _import_roots(tree) & known - {stem}
    return graph


def _reachable_from(seeds: set[str], graph: dict[str, set[str]]) -> set[str]:
    """seeds 沿 graph 的可达闭包 (BFS); seeds 里的未知名忽略。"""
    seen: set[str] = set()
    frontier = [s for s in seeds if s in graph]
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(n for n in graph.get(cur, ()) if n not in seen)
    return seen


def _find_uncovered_scripts(scripts_dir: str, tests_dir: str) -> list[str]:
    """列出 scripts_dir 下"从 tests 的 import 不可达"的 .py 文件.

    判定 (F-072):
      1. seeds = tests 直接 import 的模块名 ∩ scripts stem 集合
      2. covered = seeds 沿内部 import 图的可达闭包 (再导出链计为已覆盖)
      3. 目录豁免: legacy/ 子树按 DIR_EXEMPT; 文件自豁免: SELF_EXEMPT
    返回: 相对 scripts_dir 的路径列表, 按字典序.
    """
    refs = _find_referenced_modules(tests_dir)
    stems = {os.path.splitext(os.path.basename(p))[0]
             for p in _iter_script_files(scripts_dir)}
    covered = _reachable_from(refs & stems, _internal_import_graph(scripts_dir))
    uncovered: list[str] = []
    for full in _iter_script_files(scripts_dir):
        fn = os.path.basename(full)
        rel = os.path.relpath(full, scripts_dir).replace(os.sep, "/")
        if fn in SELF_EXEMPT:
            continue
        if os.path.splitext(fn)[0] in covered:
            continue
        uncovered.append(rel)
    uncovered.sort()
    return uncovered


def _uncovered_from_coverage_data(scripts_dir: str, data_file: str):
    """F-072 真实覆盖模式: 用 coverage 数据文件逐文件重算 executed/stmts.

    返回 (uncovered, pct_map): 文件级判定 = "有可执行语句且一条都没执行过"
    → uncovered。0 语句文件 (纯注释/空) 无可执行内容, 不算缺口。
    coverage 包缺失或数据文件不存在 → 抛 EnvironmentError (main() 转 exit 2)。
    """
    try:
        from coverage import Coverage
    except ImportError as e:
        raise EnvironmentError(
            "--coverage-data 需要 coverage 包 (pip install coverage); "
            "或省略该参数走静态模式") from e
    if not os.path.isfile(data_file):
        raise EnvironmentError(
            f"coverage 数据文件不存在: {data_file} —— 先跑 "
            f"`python -m coverage run --source=scripts -m unittest discover "
            f"-s tests` 生成")
    cov = Coverage(data_file=data_file)
    cov.load()
    uncovered: list[str] = []
    pct_map: dict[str, float] = {}
    for full in _iter_script_files(scripts_dir):
        fn = os.path.basename(full)
        rel = os.path.relpath(full, scripts_dir).replace(os.sep, "/")
        if fn in SELF_EXEMPT:
            continue
        try:
            _, stmts, _, missing, _ = cov.analysis2(full)
        except Exception:
            uncovered.append(rel)   # 不在测量范围 = 从未执行
            continue
        if not stmts:
            continue                # 无可执行语句, 无缺口可言
        executed = len(stmts) - len(missing)
        pct_map[rel] = round(100.0 * executed / len(stmts), 1)
        if executed == 0:
            uncovered.append(rel)
    uncovered.sort()
    return uncovered, pct_map


def _format_text_report(uncovered: list[str], scripts_dir: str, mode: str,
                        pct_map: dict | None = None) -> str:
    """人读报告: 模式 + 未覆盖文件 + (真实模式) 逐文件覆盖率."""
    head = (f"coverage_lint[{mode}]: {len(uncovered)} 个未覆盖文件 "
            f"(scripts_dir={scripts_dir}, 用 --strict 启用门禁):")
    lines = [head]
    for f in uncovered:
        if pct_map is not None and f in pct_map:
            lines.append(f"  - {f}  (executed {pct_map[f]}% of statements)")
        else:
            lines.append(f"  - {f}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="scripts/ 覆盖缺口 lint (F-072 口径: 可达闭包/真实覆盖)")
    parser.add_argument("--scripts-dir", default=os.path.dirname(
        os.path.abspath(__file__)),
        help=f"scripts 目录 (默认: 本文件所在目录 = {os.path.dirname(os.path.abspath(__file__))})")
    parser.add_argument("--tests-dir", default=None,
                        help="tests 目录 (默认从 scripts-dir 同级 ../tests 推断)")
    parser.add_argument("--strict", action="store_true",
                        help="存在未覆盖文件时 exit 1 (CI 门禁用)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--coverage-data", default=None, metavar="FILE",
                        help="coverage 数据文件 (.coverage); 给出则走真实覆盖比对, "
                             "否则静态可达闭包")
    args = parser.parse_args()

    if args.tests_dir is None:
        # 默认: <repo>/tests (scripts-dir 同级)
        args.tests_dir = os.path.join(
            os.path.dirname(args.scripts_dir), "tests")

    pct_map = None
    if args.coverage_data:
        mode = "coverage-data"
        try:
            uncovered, pct_map = _uncovered_from_coverage_data(
                args.scripts_dir, args.coverage_data)
        except EnvironmentError as e:
            print(f"coverage_lint: {e}", file=sys.stderr)
            return 2
    else:
        mode = "static-reachability"
        uncovered = _find_uncovered_scripts(args.scripts_dir, args.tests_dir)

    if args.json:
        out = {"tool": "coverage_lint", "mode": mode,
               "scripts_dir": args.scripts_dir,
               "tests_dir": args.tests_dir,
               "coverage_data": args.coverage_data,
               "uncovered": uncovered,
               "strict": args.strict, "uncovered_count": len(uncovered)}
        if pct_map is not None:
            out["coverage_pct"] = pct_map
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(uncovered, args.scripts_dir, mode, pct_map))
    return 1 if (args.strict and uncovered) else 0


if __name__ == "__main__":
    sys.exit(main())
