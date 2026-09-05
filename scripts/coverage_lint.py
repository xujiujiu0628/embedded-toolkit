#!/usr/bin/env python3
"""scripts/ 覆盖缺口 lint — 取代旧的"行数红线"假命题 (F-049, 2026-09-02 方案四-3).

为什么替换"行数红线":
  - 行数是假命题: 一个 200 行 const array 和一个 200 行状态机, 风险天差地别
  - 工程师为了过红线把一个文件拆成三个, 反向劣化可读性
  - 真正的高风险点 (没测试的关键逻辑) 反过来过得很开心

覆盖缺口是真问题:
  - 工程师加了新模块, 忘了给测试加 hook, PC 测试编译过/运行过/但路径没测
  - 现在要等真机复现才发现 → 一周后

本工具做一件事: 扫 scripts/ 下 .py, 列出"未被任何 test_*.py 通过 import
或函数引用"的文件, 默认仅报告 (exit 0), --strict 时作为门禁 (exit 1).

用法:
  python scripts/coverage_lint.py                          # 默认: 报告 + exit 0
  python scripts/coverage_lint.py --strict                 # 门禁: 发现未覆盖 exit 1
  python scripts/coverage_lint.py --json                   # JSON 输出
  python scripts/coverage_lint.py --scripts-dir <d>       # 自定义 scripts 目录
  python scripts/coverage_lint.py --tests-dir <d>         # 自定义 tests 目录
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
            p = os.path.join(root, fn)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=p)
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # import a.b.c → 取根模块 a
                        root_mod = alias.name.split(".")[0]
                        if root_mod:
                            mods.add(root_mod)
                elif isinstance(node, ast.ImportFrom):
                    # F-049 自审 (2026-09-03) 修: 此前 from-import 同时塞
                    # module 名 + alias 名, 相对 import 时还误把 import
                    # 进来的名字算成"被引用", 假阳/假阴都有. 修法:
                    #   - module 非空: 取 module 根段
                    #   - module 为空 (from . import x 形态): 取 alias 根段
                    #   - alias 名字 (函数/类/变量) 一律不进 mods, 避免假阳
                    target = None
                    if node.module:
                        target = node.module.split(".")[0]
                    elif node.level > 0 and node.names:
                        # 相对 import 且 module 为空: from . import helper
                        target = node.names[0].name.split(".")[0]
                    if target:
                        mods.add(target)
    return mods


def _find_uncovered_scripts(scripts_dir: str, tests_dir: str) -> list[str]:
    """列出 scripts_dir 下"未被 tests_dir 任何 import" 的 .py 文件.

    判定:
      1. 模块名匹配: scripts/foo.py → 引用集合含 'foo'
      2. 目录豁免: legacy/ 子树跳过
      3. 文件自豁免: SELF_EXEMPT 跳过
    返回: 相对 scripts_dir 的路径列表, 按字典序.
    """
    refs = _find_referenced_modules(tests_dir)
    uncovered: list[str] = []
    if not os.path.isdir(scripts_dir):
        return uncovered
    for root, dirs, files in os.walk(scripts_dir):
        # 目录豁免: 在 dirs 里移除, os.walk 不再下钻
        dirs[:] = [d for d in dirs if d not in DIR_EXEMPT]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, scripts_dir).replace(os.sep, "/")
            if fn in SELF_EXEMPT:
                continue
            module = fn[:-3]  # strip .py
            if module in refs:
                continue
            uncovered.append(rel)
    uncovered.sort()
    return uncovered


def _format_text_report(uncovered: list[str], scripts_dir: str) -> str:
    """人读报告: 列出未覆盖文件 + 总结行."""
    if not uncovered:
        return f"coverage_lint: 全部覆盖 (scripts_dir={scripts_dir})"
    lines = [f"coverage_lint: {len(uncovered)} 个未覆盖文件 "
             f"(scripts_dir={scripts_dir}, 用 --strict 启用门禁):"]
    for f in uncovered:
        lines.append(f"  - {f}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="scripts/ 覆盖缺口 lint (取代旧行数红线, F-049)")
    parser.add_argument("--scripts-dir", default=os.path.dirname(
        os.path.abspath(__file__)),
        help=f"scripts 目录 (默认: 本文件所在目录 = {os.path.dirname(os.path.abspath(__file__))})")
    parser.add_argument("--tests-dir", default=None,
                        help="tests 目录 (默认从 scripts-dir 同级 ../tests 推断)")
    parser.add_argument("--strict", action="store_true",
                        help="存在未覆盖文件时 exit 1 (CI 门禁用)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.tests_dir is None:
        # 默认: <repo>/tests (scripts-dir 同级)
        args.tests_dir = os.path.join(
            os.path.dirname(args.scripts_dir), "tests")

    uncovered = _find_uncovered_scripts(args.scripts_dir, args.tests_dir)
    if args.json:
        out = {"tool": "coverage_lint", "scripts_dir": args.scripts_dir,
               "tests_dir": args.tests_dir, "uncovered": uncovered,
               "strict": args.strict, "uncovered_count": len(uncovered)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(uncovered, args.scripts_dir))
    return 1 if (args.strict and uncovered) else 0


if __name__ == "__main__":
    sys.exit(main())
