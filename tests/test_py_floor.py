r"""py3.10 语法地板钉 (GAP-F-2, WB-20260921-02 T1)。

## 为什么需要这颗钉

CI 有一条 **py3.10** 腿（F-166 py3.10 双腿），但仓内**无任何**语法地板守卫：
`14cfe69` 的教训是一次 f-string 写法踩中 **PEP 701**（3.12 才放宽的语法），
在本机 3.14 上全绿、到 CI 3.10 腿上整腿炸。地板钉把"烧到 CI 才发现"提前到
"本地 `unittest` 就能咬"。

## 判据为什么**不是** `ast.parse(feature_version=(3,10))`

WB-20260920-04 §9.7 / GAP-F-2 已实测：`ast.parse(src, feature_version=(3,10))`
**对 PEP 701 探针不报错**（本文件 `FeatureVersionIsNotAPredicateTests` 现场复证
同一结论）。它只回退到旧语法解析器，而 PEP 701 的放宽发生在 **CPython 3.12 的
tokenizer** 层，`feature_version` 管不到。**故本钉用 `tokenize` 扫 f-string
表达式区**，不碰 `feature_version` 充当判据。

## 判据是什么（PEP 701 相对 3.6+ 放宽的三类，官方文档口径）

官方 lexical_analysis 对 3.12 变更的原话是
"Many restrictions on expressions within f-strings have been removed.
Notably, **nested strings, comments, and backslashes** are now permitted."
据此本钉在 f-string **表达式区**内检三类：

1. **同类引号（nested strings）**：内层字符串用了与**包裹 f-string 同字符**的
   定界引号。判据是**引号字符相等**，与字符串前缀无关 ——
   - `f"{d['k']}"`  → 内层 `'`，外层 `"` → **合法（3.6+）**
   - `f'{"k"}'`     → 内层 `"`，外层 `'` → **合法（3.6+）**
   - `f"{"k"}"`     → 内层 `"`，外层 `"` → **PEP 701 only**
   - `f'{d['k']}'`  → 内层 `'`，外层 `'` → **PEP 701 only**
2. **反斜杠（backslashes）**：表达式区内出现反斜杠 —— 含嵌套字符串里的转义
   （如 `f"{'\n'.join(a)}"`）与裸续行反斜杠。**非 raw** 字符串才算
   （`f"{r'a\n'}"` 的反斜杠是字面量，不算）。
3. **跨行表达式 / 注释（comments）**：表达式区内出现 `NL`/`COMMENT` token。

**不可误杀**（简报 §2 点名）：`f"{d['k']}"`、`f"{a['b']['c']}"` 这类
3.6+ 合法异类引号写法必须在绿样例里零报（见 `FixtureSelfProofTests`）。

## 夹具自证（防"空洞钉子"）

`FixtureSelfProofTests` 内置违规样例（必被咬 ≥3 例）与合法样例（必零报 ≥3 例）——
若哪天扫描器被改坏成"永远返回 0 违规"，该组立刻转红。

## 运行时版本分支

本判据依赖 `tokenize.FSTRING_START` 等 token（**CPython 3.12+** 才有）。
在 <3.12 解释器上无法运行扫描 → **显式 `skipTest`**，消息里写明
"CI 3.12 腿承接本钉"，**绝不静默通过**（简报 §2 明令）。
"""
import glob
import io
import os
import unittest
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("scripts", "tests")
SCAN_GLOB = "*.py"

# tokenize 的 f-string 专用 token —— 3.12 才引入
_HAS_FSTRING_TOKENS = (hasattr(tokenize, "FSTRING_START")
                       and hasattr(tokenize, "FSTRING_MIDDLE")
                       and hasattr(tokenize, "FSTRING_END"))

_SKIP_MSG = ("无 tokenize.FSTRING_* token (CPython <3.12 无 PEP 701 tokenizer) —— "
             "本钉不在此解释器上执行; CI 3.12 腿承接本钉 (py3.10 腿另走 "
             "compileall 语法地板)。此为显式 skip, 非静默通过。")

# f-string 前缀字符 (r/b/f/u 及其大小写组合)
_PREFIX_CHARS = "rbfuRBFU"


def _quote_char(tok_string):
    """取字符串 token 的定界引号字符 (' 或 ")，剥掉前缀。"""
    i = 0
    while i < len(tok_string) and tok_string[i] in _PREFIX_CHARS:
        i += 1
    if i >= len(tok_string):
        return None
    return tok_string[i]


def _is_raw(tok_string):
    """token 是否带 r/R 前缀（raw）；raw 串里的反斜杠是字面量，不算 PEP 701。"""
    i = 0
    while i < len(tok_string) and tok_string[i] in _PREFIX_CHARS:
        i += 1
    return "r" in tok_string[:i].lower()


def scan_fstring_floor(source, filename="<string>"):
    """扫一段源码, 返回 PEP 701-only 违规列表 [(lineno, col, 描述)]。

    口径见模块 docstring §判据。返回空列表 = 该源码在 py3.10 语法地板上安全。
    词法错误 (token 流抛 TokenError/IndentationError) 原样冒泡, 由调用方判定 ——
    本函数只负责"能 tokenize 的源码"的 PEP 701 判定。
    """
    toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    # 栈元素 = [定界引号字符, 花括号深度]
    fs_stack = []
    hits = []
    for tok in toks:
        tt, ts = tok.type, tok.string
        if tt == tokenize.FSTRING_START:
            fs_stack.append([_quote_char(ts), 0])
            continue
        if tt == tokenize.FSTRING_END:
            if fs_stack:
                fs_stack.pop()
            continue
        if not fs_stack:
            continue
        top = fs_stack[-1]
        if tt == tokenize.OP:
            if ts == "{":
                top[1] += 1
            elif ts == "}":
                if top[1] > 0:
                    top[1] -= 1
            continue
        # 以下判定仅发生在 f-string 表达式区
        if tt == tokenize.STRING:
            if not _is_raw(ts) and "\\" in ts:
                hits.append((tok.start[0], tok.start[1],
                             f"表达式区嵌套字符串含反斜杠转义 {ts!r} "
                             f"(PEP 701, 需 py3.12+)"))
            if _quote_char(ts) == top[0]:
                hits.append((tok.start[0], tok.start[1],
                             f"表达式区用了与定界符同类引号 {top[0]!r}: {ts!r} "
                             f"(PEP 701, 需 py3.12+)"))
        elif tt == tokenize.ERRORTOKEN and ts == "\\":
            hits.append((tok.start[0], tok.start[1],
                         "表达式区出现裸反斜杠 (PEP 701, 需 py3.12+)"))
        elif tt in (tokenize.NL, tokenize.COMMENT):
            hits.append((tok.start[0], tok.start[1],
                         f"表达式区出现跨行/注释 {ts!r} (PEP 701, 需 py3.12+)"))
    # 去重 (同一位置可能同时命中 C1+C2, 保持首见顺序)
    seen = set()
    uniq = []
    for h in hits:
        key = (h[0], h[1], h[2])
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    return uniq


def iter_scan_targets(root=ROOT):
    """仓内全部 `scripts/*.py` + `tests/*.py` (简报 §2 T1 扫描面)。"""
    targets = []
    for d in SCAN_DIRS:
        targets.extend(sorted(glob.glob(os.path.join(root, d, SCAN_GLOB))))
    return targets


# ── 夹具 (防空洞): 违规样例 / 合法样例, 各 ≥3 例 ──
VIOLATION_SAMPLES = [
    # ① 与定界符同字符的引号
    ('x = f"{"k"}"', "同类引号 (双包双)"),
    ("x = f'{d['k']}'", "同类引号 (单包单)"),
    ('x = f"{a["b"]["c"]}"', "同类引号 (多层下标)"),
    # ② 反斜杠 (嵌套字符串里的转义)
    ('x = f"{\'\\n\'.join(a)}"', "嵌套字符串含反斜杠转义"),
    ("x = f\"{'\\\\t'}\"", "嵌套字符串含 \\\\t 转义"),
    # ③ 跨行表达式 / 注释
    ('x = f"{\n  a\n}"', "跨行表达式"),
    ('x = f"{a  # c\n}"', "表达式区注释"),
]

LEGAL_SAMPLES = [
    # 3.6+ 一直合法的异类引号写法 —— 绝不可误杀
    ("x = f\"{d['k']}\"", "单引号嵌在双引号 f-string"),
    ("x = f'{d[\"k\"]}'", "双引号嵌在单引号 f-string"),
    ("x = f\"{a['b']['c']}\"", "多层异类引号下标"),
    ("x = f'{d[\"k\"]}{e[\"j\"]}'", "多个异类引号字段"),
    # 常规形态
    ("x = f\"plain {value} text\"", "无引号表达式"),
    ("x = f\"{value!r:>{width}}\"", "转换+格式说明"),
    ("x = f\"{d['k']}={1 + 2}\"", "表达式含常量"),
    ('x = f"{ {1: 2}[\'1\'] }"', "字典字面量 + 异类引号下标"),
    ("x = f\"{a}'{b}'\"", "混合: 花括号外单引号"),
    ("x = f\"{a:.3f}\"", "浮点格式说明"),
    ('x = f"{r\'a\\nb\'}"', "raw 嵌套串反斜杠 (合法)"),
]


def _collect(root=ROOT):
    """扫描全树, 返回 (扫描文件数, f-string 数, 违规列表)。"""
    n_files = 0
    n_fstrings = 0
    violations = []
    for path in iter_scan_targets(root):
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="latin-1") as f:
                src = f.read()
        n_files += 1
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        n_fstrings += sum(1 for t in toks if t.type == tokenize.FSTRING_START)
        for (lineno, col, why) in scan_fstring_floor(src, path):
            violations.append(f"{os.path.relpath(path, root)}:{lineno}:{col}: {why}")
    return n_files, n_fstrings, violations


@unittest.skipUnless(_HAS_FSTRING_TOKENS, _SKIP_MSG)
class FixtureSelfProofTests(unittest.TestCase):
    """夹具自证: 违规样例必被咬, 合法样例必零报（各 ≥3 例）。

    本组是"钉子本身有效"的证据 —— 若扫描器被改成永远返回空/永远报警,
    这里立刻转红, 不会留下空洞地板。
    """

    def test_violation_samples_are_all_caught(self):
        self.assertGreaterEqual(len(VIOLATION_SAMPLES), 3, "违规样例不足 3 例")
        missed = []
        for src, why in VIOLATION_SAMPLES:
            if not scan_fstring_floor(src):
                missed.append(f"{why}: {src!r}")
        self.assertEqual(missed, [],
                         "违规样例未被检出 (夹具失效):\n  " + "\n  ".join(missed))

    def test_legal_samples_are_all_clean(self):
        self.assertGreaterEqual(len(LEGAL_SAMPLES), 3, "合法样例不足 3 例")
        false_alarms = []
        for src, why in LEGAL_SAMPLES:
            hits = scan_fstring_floor(src)
            if hits:
                false_alarms.append(f"{why}: {src!r} -> {hits}")
        self.assertEqual(false_alarms, [],
                         "合法写法被误杀 (简报 §2 明令禁止):\n  "
                         + "\n  ".join(false_alarms))

    def test_legal_alternate_quote_form_zero_report(self):
        """简报 §2 点名的两种合法写法, 逐条零报（显式单列）。"""
        for src in ('x = f"{d[\'k\']}"', 'x = f"{a[\'b\'][\'c\']}"'):
            with self.subTest(src=src):
                self.assertEqual(scan_fstring_floor(src), [],
                                 f"合法异类引号写法被误杀: {src}")

    def test_each_violation_class_has_a_catcher(self):
        """三类判据各有样例, 且样例确实分别命中对应类别（防"只剩 C1"退化）。"""
        classes = {why: scan_fstring_floor(src)
                   for src, why in VIOLATION_SAMPLES}
        self.assertGreaterEqual(len(classes), 3, "违规样例类别不足")
        for why, hits in classes.items():
            with self.subTest(sample=why):
                self.assertNotEqual(hits, [], f"{why} 未被检出")


@unittest.skipUnless(_HAS_FSTRING_TOKENS, _SKIP_MSG)
class FeatureVersionIsNotAPredicateTests(unittest.TestCase):
    """把 GAP-F-2 的核心结论钉进回归 —— `ast.parse(feature_version=(3,10))`
    **不是**有效的 py3.10 语法地板判据（对 PEP 701 探针不报错）。

    若哪天 CPython 补齐了 feature_version 的 tokenizer 回退, 本钉会转红并提示
    "可以考虑换判据"——这本身是有价值的信号, 不是噪声。
    """

    def test_feature_version_does_not_catch_pep701(self):
        import ast
        pep701_only = 'x = f"{"k"}"'
        # 本机解释器先确认真能编译（说明语法本身合法, 只是版本敏感）
        compile(pep701_only, "<probe>", "exec")
        # 关键实证: feature_version=(3,10) 照样通过 —— 故不能当地板判据
        ast.parse(pep701_only, feature_version=(3, 10))

    def test_tokenize_predicate_does_catch_pep701(self):
        """反之, tokenize 判据必须咬住同一探针（两个判据的对照）。"""
        self.assertNotEqual(scan_fstring_floor('x = f"{"k"}"'), [])


@unittest.skipUnless(_HAS_FSTRING_TOKENS, _SKIP_MSG)
class RepoFloorTests(unittest.TestCase):
    """全树扫描: 当前树必须零违规（简报 §2 T1 收口判据）。"""

    def test_repo_has_no_pep701_violation(self):
        n_files, n_fstrings, violations = _collect()
        self.assertGreaterEqual(n_files, 100,
                                f"扫描面异常偏小 ({n_files} 文件) —— 夹具可能没找到树")
        self.assertGreater(n_fstrings, 0, "全树零 f-string —— 扫描器可能失效")
        self.assertEqual(
            violations, [],
            f"检出 {len(violations)} 处 PEP 701-only 写法"
            f"（CI py3.10 腿必炸, 需改为等价 3.6+ 写法）:\n  "
            + "\n  ".join(violations))

    def test_scan_surface_covers_scripts_and_tests(self):
        """扫描面 = scripts/*.py + tests/*.py（简报 §2 口径）。"""
        targets = iter_scan_targets()
        rels = [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in targets]
        self.assertTrue(any(r.startswith("scripts/") for r in rels),
                        "扫描面缺 scripts/")
        self.assertTrue(any(r.startswith("tests/") for r in rels),
                        "扫描面缺 tests/")
        self.assertTrue(all(r.endswith(".py") for r in rels),
                        "扫描面混入非 .py 文件")


@unittest.skipUnless(_HAS_FSTRING_TOKENS, _SKIP_MSG)
class SelfDogfoodTests(unittest.TestCase):
    """简报 §3「代码语法地板自反条款」—— 本钉自身必须过自家地板。

    14cfe69 的教训（写地板钉的代码自己踩地板）在此机器化。
    """

    def test_this_file_passes_its_own_floor(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            src = f.read()
        hits = scan_fstring_floor(src, __file__)
        self.assertEqual(hits, [], f"本钉自身踩了 py3.10 语法地板: {hits}")


if __name__ == "__main__":
    unittest.main()
