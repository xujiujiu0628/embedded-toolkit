r"""CONTRIBUTING 分层契约的机检钉 (F-100, WB-C6 / 审计 P1-10)。

背景: CONTRIBUTING.md「分层与复用」声明三条"可机检禁令（违者拒收）"，
但长期无配套机检——声明了却无法执行（F-035 想消除的盲区，审计 P1-10）。
本文件把三条禁令全部落为 AST 静态断言:

  禁令 1: Layer 0 (wb_common) / 0.5 (runtime_common) / 1 (三 runtime)
          禁止 import 任何 Layer 2 工具脚本（防依赖倒置）
  禁令 2: 生产脚本禁止 import verify（verify 是 Layer 2 编排主体，
          需要其逻辑应拆共享模块而非反向 import）
  禁令 3: scripts/legacy/** 禁止新增 runtime_common import（冻结区）

豁免（显式声明，加豁免须在本文件登记理由）:
  - Layer 1 的 wb_runtime/openocd_runtime/serial_runtime 允许 import
    Layer 0/0.5 —— 本身就是分层定义
  - tests/ 不在扫描范围
"""
import ast
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

LAYER_0 = {"wb_common"}
LAYER_05 = {"runtime_common"}
# openocd_gdb_common 虽名带 common 却是"gdb 族共享件": 只被 openocd_gdb
# (Layer 2) 消费, 自身 import openocd_runtime —— 按 F-100 登记归 Layer 1
# （CONTRIBUTING 分层图的"三 runtime"未列它, 属图示遗漏, 见 CHANGELOG F-100）
LAYER_1 = {"wb_runtime", "openocd_runtime", "serial_runtime",
           "openocd_gdb_common"}
# Layer 2 = scripts/*.py 除去 Layer 0/0.5/1 与 legacy/
ALLOWED_FOR_LOW_LAYERS = LAYER_0 | LAYER_05


def _local_imports(path: Path) -> set[str]:
    """文件内 import 的项目内顶层模块名（AST，抗字符串/注释假阳）"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods.add(n.module.split(".")[0])
    return mods & (LAYER_0 | LAYER_05 | LAYER_1 | _layer2_names())


def _layer2_names() -> set[str]:
    """Layer 2 = scripts/ 顶层全部工具脚本（不含 legacy/ 与低层）"""
    return {p.stem for p in SCRIPTS.glob("*.py")
            if p.stem not in (LAYER_0 | LAYER_05 | LAYER_1)}


class LayeringGateTests(unittest.TestCase):
    """禁令 1+2: 低层禁 import 上层 / 生产脚本禁 import verify"""

    def test_low_layers_never_import_layer2(self):
        """禁令 1: wb_common/runtime_common/族 runtime 不得 import Layer 2。
        允许的方向: Layer 1 → Layer 0/0.5 (分层定义), Layer 1 族内互引
        (如 openocd_gdb_common → openocd_runtime, 同族共享件)。"""
        low = [Path(SCRIPTS, f"{m}.py") for m in
               (LAYER_0 | LAYER_05 | LAYER_1)]
        violations = []
        for path in low:
            if path.stem in LAYER_0 or path.stem in LAYER_05:
                allowed = ALLOWED_FOR_LOW_LAYERS
            else:
                # Layer 1: 允许引 Layer 0/0.5 + 同族 Layer 1 (共享件互引)
                allowed = ALLOWED_FOR_LOW_LAYERS | LAYER_1
            illegal = _local_imports(path) - allowed - {path.stem}
            if illegal:
                violations.append(f"{path.name}: {sorted(illegal)}")
        self.assertEqual(
            violations, [],
            "低层 import 了 Layer 2（依赖倒置, CONTRIBUTING 禁令 1）:\n"
            + "\n".join(violations))

    def test_no_production_script_imports_verify(self):
        """禁令 2: 生产脚本禁止 import verify（编排主体只许被测试引用）"""
        violations = []
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.stem == "verify":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name == "verify" or a.name.startswith("verify."):
                            violations.append(f"{path.name}:{n.lineno}")
                elif isinstance(n, ast.ImportFrom) and n.module == "verify":
                    violations.append(f"{path.name}:{n.lineno}")
        self.assertEqual(
            violations, [],
            "生产脚本 import verify（CONTRIBUTING 禁令 2）:\n"
            + "\n".join(violations))

    def test_legacy_freeze_no_runtime_common(self):
        """禁令 3: scripts/legacy/** 不得 import runtime_common（冻结区）"""
        legacy = list((SCRIPTS / "legacy").rglob("*.py"))
        violations = []
        for path in legacy:
            if "runtime_common" in _local_imports(path):
                violations.append(path.name)
        self.assertEqual(
            violations, [],
            "legacy/ 新增 runtime_common import（CONTRIBUTING 禁令 3）:\n"
            + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
