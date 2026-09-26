r"""全局模块打桩静态棘轮 (L-2, WB-20260926-03 T1)。

## 为什么需要这道棘轮

三护栏不对称 (WB-20260925-01 L-2): F-181 是机检 (test_py_floor),
F-182/F-184 只是样板 (模块引用替换 + StubIsolationTests 身份断言钉)——
GAP-F-13 "按需收窄、不批量清扫"裁决零机检, F-188 新测试文件即回旧
pattern (test_esp_backend_gate.py 两处全局打桩), 登记计数正向漂移。
本钉把"全局打桩零新增"机器化: 清单新增即红, 清除须同步缩快照
(防"清了就忘")。

## 判据 (违规 = 对全局模块对象的属性打桩)

全局模块名集 G = scripts/*.py 顶层 import 首段并集 (树内反查, F-186
纪律禁外部记忆) − 仓内脚本模块名 (scripts/<n>.py 存在者) ∪ {"builtins"}。
patch 调用被变异的对象属于 G 即违规, 两种形态:

  A 式 (字符串目标)  mock.patch("subprocess.run") / mock.patch("os.replace")
      —— 目标首段 ∈ G; 扩展: "X.Y.Z" 且 Y ∈ G
      (mock.patch("esp_runtime.time.sleep") —— X 为仓内模块但桩实际落在
      全局 time 对象上)。两段式 "X.Y" (mock.patch("serial_mux.os")) 是
      F-184 模块引用替换的字符串形态, 合法。

  B 式 (对象目标)    mock.patch.object(<第一实参链>, …) 第一实参为
      Name(id ∈ G) (mock.patch.object(sys, "argv")) 或 Attribute 链末端段
      ∈ G (mock.patch.object(verify.subprocess, "run") —— 穿仓内引用打到
      全局 subprocess, L-2 canonical 形态;
      mock.patch.object(esp_runtime.time, "sleep") 同族)。

  合法 (零报)        B 式对象链末端为仓内脚本模块: 模块引用替换
      mock.patch.object(serial_mux, "os", stub) (F-184/GAP-F-9 钦定形态)
      与被测模块自有命名空间变异 mock.patch.object(doctor, "load_machine");
      字符串目标首段为仓内模块的两段式; mock.patch.dict (保存/恢复式,
      非属性置桩, 不在判据面)。

  判据边界 (P 面登记, 非疏漏): 仓内共享层模块对象经自身命名空间的属性
  变异 (mock.patch.object(hw_lease, "DEVICE_LOCK_DIR", …) /
  mock.patch.object(verify.esp_runtime, "step_capture_uart", …)) 不判违规
  —— F-182 劫持事故类 = 全局库对象被基础设施动态查表 (占位进程递归回
  fake → RecursionError 被吞), 仓内模块无此暴露面。收窄此面属裁决变更:
  须改判据 + 重建快照, 不许绕钉。

## 棘轮机制

BASELINE = 现存违规快照, 键 (文件, 形态, 目标) -> 次数 (L-2 "不批量清扫"
裁决维持存量, 口径与 01 报告正则粗扫 102 处不同: 本判据为 AST 全形态,
计数更大, 差异如实声明)。当前扫描 Counter 必须与 BASELINE 全等:
  · 多出 → 红 (新增违规): 改写为模块引用替换式, 或经裁决进 EXEMPTS;
  · 少了 → 红 (清除未记账): 同步缩快照, 快照 diff 即清理证据;
  · EXEMPTS = 显式豁免列表, 每键必带 note (禁静默), 键必须仍在现树
    (失效豁免 → 红提醒回收)。

## 夹具自证 (双枪)

违规样例必被咬 (A/B 两式各形态) / 合法样例必零报 / 真树扫描非空且与
快照全等 / 扫描面哨兵文件在场 / 本文件自过自家判据。F-181 "句柄式假绿"
教训的对位: 判定全部走 AST 静态节点, 不依赖 import 期句柄或运行时状态。
"""
import ast
import glob
import os
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIR = "tests"   # 非递归顶层, 与 test_py_floor 同口径 (N-1 边界随动)

# ── 全局模块名集 ──


def _local_script_modules(root=ROOT):
    """仓内脚本模块名 (scripts/<n>.py 存在)。"""
    return {os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(root, "scripts", "*.py"))}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, encoding="latin-1") as f:
            return f.read()


def _script_top_imports(root=ROOT):
    """scripts/*.py 顶层 import 首段并集 (树内反查)。"""
    names = set()
    for p in sorted(glob.glob(os.path.join(root, "scripts", "*.py"))):
        tree = ast.parse(_read(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    names.add(node.module.split(".")[0])
    return names


def global_module_names(root=ROOT):
    """G = scripts 顶层 import 首段 ∪ builtins − 仓内脚本模块名。"""
    return ((_script_top_imports(root) | {"builtins"})
            - _local_script_modules(root))


# ── 扫描器 ──


def _dotted(node):
    """Attribute/Name 链的文本; 链中混入非 Name/Attribute 节点返回 None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _patch_kind(node):
    """ast.Call -> "patch" | "object" | "multiple" | None。

    识别 mock.patch* / unittest.mock.patch* / 裸 patch* (from-import) 链;
    mock.patch.dict 不在判据面 (保存/恢复式, 非属性置桩)。"""
    f = node.func
    if isinstance(f, ast.Name) and f.id == "patch":
        return "patch"
    if isinstance(f, ast.Attribute) and f.attr in ("patch", "object",
                                                   "multiple"):
        # mock.patch.object 的 AST 是 ((mock.patch).object) — 基链是
        # "mock.patch" 而非 "mock"; 裸 patch (from-import) 基链是 "patch"。
        if _dotted(f.value) in ("mock", "unittest.mock", "mock.patch",
                                "unittest.mock.patch", "patch"):
            return f.attr
    return None


def scan_source(src, gnames):
    """扫一段源码, 返回违规 [(form, target)]。form: "A" 字符串式 / "B" 对象式。"""
    hits = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        kind = _patch_kind(node)
        if not kind or not node.args:
            continue
        if kind in ("patch", "multiple"):
            a0 = node.args[0]
            if not (isinstance(a0, ast.Constant)
                    and isinstance(a0.value, str)):
                continue
            comps = a0.value.split(".")
            if comps[0] in gnames or (len(comps) >= 3 and comps[1] in gnames):
                hits.append(("A", a0.value))
        else:   # object
            chain = _dotted(node.args[0])
            if chain is None:
                continue
            if chain.split(".")[-1] not in gnames:
                continue
            attr = ""
            if (len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                attr = "." + node.args[1].value
            hits.append(("B", chain + attr))
    return hits


def collect(root=ROOT):
    """扫 tests/*.py, 返回 (文件相对路径列表, Counter[(rel, form, target)])。"""
    gnames = global_module_names(root)
    counter = Counter()
    files = []
    for p in sorted(glob.glob(os.path.join(root, SCAN_DIR, "*.py"))):
        rel = SCAN_DIR + "/" + os.path.basename(p)
        files.append(rel)
        for form, target in scan_source(_read(p), gnames):
            counter[(rel, form, target)] += 1
    return files, counter


# ── 棘轮快照 (冻结于 WB-20260926-03, 基线 master 5a89ce9) ──

BASELINE = {
    ('tests/test_capture_rtt.py', 'B', 'capture_rtt.socket.create_connection'): 3,
    ('tests/test_capture_rtt.py', 'B', 'capture_rtt.subprocess.Popen'): 4,
    ('tests/test_capture_rtt.py', 'B', 'capture_rtt.time.sleep'): 4,
    ('tests/test_capture_semihosting.py', 'B', 'capture_semihosting.subprocess.Popen'): 1,
    ('tests/test_capture_sim.py', 'B', 'sys.argv'): 1,
    ('tests/test_checkpoint_ledger.py', 'A', 'builtins.open'): 1,
    ('tests/test_checkpoint_ledger.py', 'B', 'sys.argv'): 2,
    ('tests/test_cube_usercode.py', 'A', 'os.replace'): 3,
    ('tests/test_cube_usercode.py', 'B', 'cube_usercode.shutil.copy2'): 1,
    ('tests/test_doctor.py', 'B', 'openocd_runtime.subprocess.run'): 4,
    ('tests/test_doctor.py', 'B', 'openocd_runtime.time.sleep'): 3,
    ('tests/test_doctor.py', 'B', 'verify.subprocess.run'): 1,
    ('tests/test_esp_backend_gate.py', 'B', 'physical_gate.subprocess.Popen'): 1,
    ('tests/test_esp_backend_gate.py', 'B', 'sys.argv'): 1,
    ('tests/test_esp_backend_gate.py', 'B', 'verify.subprocess.run'): 1,
    ('tests/test_esp_config_failfast.py', 'B', 'sys.argv'): 1,
    ('tests/test_esp_config_failfast.py', 'B', 'verify.subprocess.run'): 1,
    ('tests/test_esp_runtime.py', 'A', 'serial.Serial'): 5,
    ('tests/test_esp_runtime.py', 'B', 'esp_runtime.time.sleep'): 5,
    ('tests/test_esp_runtime.py', 'B', 'esp_runtime.time.time'): 4,
    ('tests/test_evidence_export.py', 'B', 'sys.argv'): 1,
    ('tests/test_f190_release_chain.py', 'B', 'sys.argv'): 1,
    ('tests/test_fixture_doctor.py', 'A', 'subprocess.run'): 4,
    ('tests/test_gcc_build.py', 'B', 'gcc_build.shutil.which'): 2,
    ('tests/test_gcc_build.py', 'B', 'gcc_build.sys.argv'): 2,
    ('tests/test_gdb_server_orphan_cleanup.py', 'B', 'sys.argv'): 2,
    ('tests/test_gen_periph.py', 'B', 'gen_periph.os.getcwd'): 1,
    ('tests/test_gen_periph.py', 'B', 'sys.argv'): 7,
    ('tests/test_gen_timer_entry_gate.py', 'B', 'sys.argv'): 1,
    ('tests/test_hardfault_sticky_clear.py', 'B', 'hardfault.subprocess.run'): 1,
    ('tests/test_hil_origin_guard.py', 'B', 'sys.argv'): 2,
    ('tests/test_hw_lease.py', 'B', 'openocd_run.subprocess.run'): 1,
    ('tests/test_hw_lease.py', 'B', 'sys.argv'): 1,
    ('tests/test_json_exit_code_contract.py', 'B', 'serial_mux.shutil.which'): 1,
    ('tests/test_json_exit_code_contract.py', 'B', 'sys.argv'): 1,
    ('tests/test_junit_xml.py', 'B', 'sys.argv'): 1,
    ('tests/test_mcp_server.py', 'B', 'mcp_server.subprocess.run'): 5,
    ('tests/test_mcp_server.py', 'B', 'sys.argv'): 1,
    ('tests/test_mcp_server.py', 'B', 'sys.stdin'): 1,
    ('tests/test_mux_alive_probe.py', 'B', 'os.kill'): 4,
    ('tests/test_mux_alive_probe.py', 'B', 'serial_runtime.os.name'): 4,
    ('tests/test_openocd_cfg_param.py', 'B', 'capture_rtt.socket.create_connection'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'capture_rtt.subprocess.Popen'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'capture_rtt.time.sleep'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'capture_semihosting.subprocess.Popen'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'hardfault.subprocess.run'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'hardfault.time.sleep'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'openocd_runtime.subprocess.run'): 7,
    ('tests/test_openocd_cfg_param.py', 'B', 'physical_gate.subprocess.Popen'): 3,
    ('tests/test_openocd_cfg_param.py', 'B', 'physical_gate.time.sleep'): 3,
    ('tests/test_openocd_telnet_failfast.py', 'A', 'subprocess.run'): 2,
    ('tests/test_p2_edge_pack.py', 'A', 'os.replace'): 1,
    ('tests/test_p2_edge_pack.py', 'B', 'physical_gate.subprocess.run'): 1,
    ('tests/test_p2_edge_pack.py', 'B', 'sys.argv'): 1,
    ('tests/test_physical_gate.py', 'B', 'physical_gate.subprocess.Popen'): 2,
    ('tests/test_physical_gate.py', 'B', 'physical_gate.time.sleep'): 1,
    ('tests/test_release.py', 'B', 'release.subprocess.run'): 2,
    ('tests/test_rm_lookup_human_output.py', 'B', 'sys.argv'): 1,
    ('tests/test_serial_dedup.py', 'B', 'sys.stderr'): 2,
    ('tests/test_serial_dedup.py', 'B', 'sys.stdout'): 1,
    ('tests/test_serial_log_record.py', 'B', 'serial_log.sys.argv'): 1,
    ('tests/test_verify_evidence.py', 'B', 'sys.argv'): 1,
    ('tests/test_verify_failure_paths.py', 'B', 'verify.subprocess.Popen'): 1,
    ('tests/test_verify_failure_paths.py', 'B', 'verify.subprocess.run'): 5,
    ('tests/test_verify_failure_paths.py', 'B', 'verify.sys.platform'): 1,
    ('tests/test_verify_failure_paths.py', 'B', 'verify.time.sleep'): 1,
    ('tests/test_verify_main_success_path.py', 'B', 'sys.argv'): 2,
    ('tests/test_verify_mainflow_retry.py', 'A', 'verify.time.sleep'): 2,
    ('tests/test_verify_mainflow_retry.py', 'B', 'sys.argv'): 1,
    ('tests/test_verify_post_reset.py', 'B', 'openocd_runtime.subprocess.run'): 2,
    ('tests/test_verify_post_reset.py', 'B', 'sys.argv'): 2,
    ('tests/test_writeback_guards.py', 'B', 'runtime_common.os.replace'): 1,
    ('tests/test_zero_cov_finish.py', 'B', 'sys.stdout'): 1,
}

# 显式豁免列表: {(rel, form, target): note}。进入即须裁决 + note, 禁静默;
# 条目失效 (现树已无此桩) 会转红提醒回收。
EXEMPTS = {
    ("tests/test_release.py", "B", "sys.argv"):
        "WB-20260926-03 T3 钉需进程内驱动 release.main() 注入 argv — "
        "argparse 直读全局 sys.argv, 仓内无替换缝; sys.argv patch 系全仓"
        "既有惯用形态 (baseline sys.argv 族 20+ 处), 本单 3 处为唯一新增, "
        "随钉落盘经裁决豁免。",
}


class RatchetSnapshotTests(unittest.TestCase):
    """真树扫描与快照全等 —— 棘轮本体。"""

    def test_scan_matches_baseline(self):
        files, counter = collect()
        current = {k: v for k, v in counter.items() if k not in EXEMPTS}
        added = sorted(set(current) - set(BASELINE))
        removed = sorted(set(BASELINE) - set(current))
        changed = sorted(k for k in set(current) & set(BASELINE)
                         if current[k] != BASELINE[k])
        msg = []
        if added:
            msg.append("新增全局打桩 (改模块引用替换式, 或经裁决进 EXEMPTS+note):\n  "
                       + "\n  ".join(f"{k[0]} {k[1]}:{k[2]}" for k in added))
        if removed:
            msg.append("违规被清除但快照未缩 (防\"清了就忘\", 同步缩快照):\n  "
                       + "\n  ".join(f"{k[0]} {k[1]}:{k[2]}" for k in removed))
        if changed:
            msg.append("既有条目次数漂移:\n  "
                       + "\n  ".join(f"{k[0]} {k[1]}:{k[2]} "
                                     f"{BASELINE[k]} -> {current[k]}"
                                     for k in changed))
        self.assertEqual(current, BASELINE, "\n\n".join(msg))

    def test_exempts_are_explicit_and_live(self):
        files, counter = collect()
        for key, note in EXEMPTS.items():
            with self.subTest(key=key):
                self.assertTrue(str(note).strip(),
                                "豁免必须带 note (禁静默)")
                self.assertIn(key, counter,
                              "豁免条目已不在现树 — 回收该 EXEMPTS 条目")

    def test_scan_surface_sanity(self):
        files, counter = collect()
        self.assertGreaterEqual(len(files), 80,
                                f"扫描面异常偏小 ({len(files)} 文件) — "
                                "glob 可能没找到树")
        file_set = set(files)
        for sentinel in ("tests/test_esp_backend_gate.py",      # L-2 canonical
                         "tests/test_serial_mux_lifecycle.py",  # F-182 样板
                         "tests/test_stub_ratchet.py"):         # 本文件
            self.assertIn(sentinel, file_set,
                          f"哨兵文件不在扫描面: {sentinel}")

    def test_baseline_is_nonempty(self):
        """快照总量地板: 防判据被改窄后快照静默缩水 (双锁, 改判据须同改此处)。"""
        total = sum(BASELINE.values())
        self.assertGreaterEqual(
            total, 100,
            f"快照总量 {total} < 100 — 判据或扫描面被收窄? "
            "收窄属裁决变更, 须重建快照并同改本地板。")

    def test_self_dogfood_zero(self):
        """本文件自过自家判据 (py_floor SelfDogfoodTests 同款)。"""
        hits = scan_source(_read(os.path.abspath(__file__)),
                           global_module_names())
        self.assertEqual(hits, [], f"本钉自身踩了自家判据: {hits}")


# ── 夹具自证 (双枪) ──

# (源码样例, 期望形态, 期望目标) —— 违规样例必被咬
VIOLATION_SAMPLES = [
    ('mock.patch("subprocess.run")', "A", "subprocess.run"),
    ('mock.patch("os.replace", fake)', "A", "os.replace"),
    ('mock.patch("serial.Serial", fake)', "A", "serial.Serial"),
    ('mock.patch("builtins.open", fake)', "A", "builtins.open"),
    ('mock.patch("time.time")', "A", "time.time"),
    ('mock.patch("esp_runtime.time.sleep", fake)', "A",
     "esp_runtime.time.sleep"),
    ('mock.patch("verify.subprocess.run", fake)', "A",
     "verify.subprocess.run"),
    ('mock.patch.multiple("subprocess", Popen=fake)', "A", "subprocess"),
    ('patch("subprocess.run")', "A", "subprocess.run"),
    ('@mock.patch("time.time")\ndef f():\n    pass', "A", "time.time"),
    ('mock.patch.object(sys, "argv", ["x"])', "B", "sys.argv"),
    ('mock.patch.object(os, "kill")', "B", "os.kill"),
    ('mock.patch.object(verify.subprocess, "run", fake)', "B",
     "verify.subprocess.run"),
    ('mock.patch.object(esp_runtime.time, "sleep", fake)', "B",
     "esp_runtime.time.sleep"),
    ('mock.patch.object(serial_runtime.os, "name", "nt")', "B",
     "serial_runtime.os.name"),
    ('mock.patch.object(runtime_common.os, "replace", fake)', "B",
     "runtime_common.os.replace"),
]

# 合法样例必零报 (F-184 钦定形态 + 判据边界)
LEGAL_SAMPLES = [
    'mock.patch.object(serial_mux, "os", stub)',
    'mock.patch.object(serial_mux, "subprocess", stub)',
    'mock.patch.object(capture_sim, "subprocess")',
    'mock.patch.object(openocd_run, "subprocess", stub)',
    'mock.patch.object(doctor, "load_machine", fake)',
    'mock.patch.object(esp_runtime, "step_capture_uart", fake)',
    'mock.patch.object(verify.esp_runtime, "step_capture_uart", fake)',
    'mock.patch.object(hw_lease, "DEVICE_LOCK_DIR", tmp)',
    'mock.patch.object(serial_runtime, "datetime", fake)',
    'mock.patch("rm_lookup.load_ref", fake)',
    'mock.patch("serial_mux.os")',
    'mock.patch("wb_common.load_machine", fake)',
    'mock.patch.dict(os.environ, {"A": "B"})',
]


class GlobalNameSetTests(unittest.TestCase):
    """全局模块名集的地板与边界 (防派生逻辑被改坏成空集/含仓内名)。"""

    def test_core_global_names_present(self):
        g = global_module_names()
        for name in ("os", "sys", "subprocess", "shutil", "time", "socket",
                     "serial", "json", "builtins"):
            self.assertIn(name, g, f"全局模块名集缺 {name} — 派生逻辑失效")

    def test_local_script_names_excluded(self):
        g = global_module_names()
        for name in ("verify", "release", "doctor", "esp_runtime", "rm_lookup",
                     "serial_mux", "wb_common", "runtime_common", "hw_lease",
                     "openocd_runtime", "mcp_server", "gcc_build"):
            self.assertNotIn(name, g,
                             f"仓内脚本模块 {name} 不得进全局模块名集")


class FixtureSelfProofTests(unittest.TestCase):
    """双枪: 违规样例必被咬, 合法样例必零报。"""

    def test_violation_samples_are_all_caught(self):
        self.assertGreaterEqual(len(VIOLATION_SAMPLES), 10,
                                "违规样例不足 — 双枪失效")
        g = global_module_names()
        missed = []
        for src, form, target in VIOLATION_SAMPLES:
            got = scan_source(src, g)
            if (form, target) not in got:
                missed.append(f"期望 {form}:{target}, 实得 {got}: {src!r}")
        self.assertEqual(missed, [], "违规样例未被检出 (夹具失效):\n  "
                         + "\n  ".join(missed))

    def test_legal_samples_are_all_clean(self):
        self.assertGreaterEqual(len(LEGAL_SAMPLES), 10,
                                "合法样例不足 — 双枪失效")
        g = global_module_names()
        false_alarms = []
        for src in LEGAL_SAMPLES:
            hits = scan_source(src, g)
            if hits:
                false_alarms.append(f"{src!r} -> {hits}")
        self.assertEqual(false_alarms, [],
                         "合法形态被误杀 (F-184 钦定形态不得报):\n  "
                         + "\n  ".join(false_alarms))

    def test_each_violation_form_has_a_catcher(self):
        """A/B 两式各有样例命中 (防只剩单式退化)。"""
        g = global_module_names()
        forms = set()
        for src, form, _target in VIOLATION_SAMPLES:
            if scan_source(src, g):
                forms.add(form)
        self.assertIn("A", forms, "A 式 (字符串目标) 无样例命中")
        self.assertIn("B", forms, "B 式 (对象目标) 无样例命中")


if __name__ == "__main__":
    unittest.main()
