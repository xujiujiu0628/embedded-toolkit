r"""rm_lookup `--pins` 消费面钉 (F-199, WB-20260927-07 — GAP-F-21① 同单兑现)。

数据面唯一事实源 = data/pin-mapping-f103.json (F-193 入册 CAN 四行,
本单零数据写)。本钉五面:

  1. **已入册金比对**  人读四列 (脚/功能/列位/source) 与 JSON rows 逐字
     == 数据档入册值 (期望值全部从数据档反查, F-186 纪律);
     反替换钉: DS5319 Rev 20 表内拼写 CANRX/CANTX (F-193 P③) 不得回写
     替换入册规范名 CAN_RX/CAN_TX — 消费面输出禁现 CANRX/CANTX;
  2. **未入册**  "未入册" 显式指认 + 当前入册集 (顶层块键动态导出,
     禁硬编码) + CHANGELOG F-189/F-193 指路; exit 0 (查询无果不是错误);
  3. **精确匹配**  查询词 upper() 精确匹配顶层块名 (can→CAN), 禁模糊;
  4. **JSON 双形态**  已入册 {query, registered, rows[pin,function,column,
     source]} / 未入册 {query, registered, known};
  5. **缺档/损坏**  PinMappingError 点名文件与原因 (F-198 T2 同式),
     CLI 报错面 rc=1 + Error 行, 禁裸 traceback。

驱动先例 test_rm_lookup_human_output.py: subprocess + 函数直调。
零 mock/零 patch (F-192 棘轮 BASELINE 73 键/157 处/38 文件零漂移,
新增即红) — CLI 面走真进程, 库面走直调, 输出捕获走 contextlib。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import rm_lookup  # noqa: E402
from wb_common import TOOLKIT_ROOT  # noqa: E402

MAPPING_PATH = os.path.join(TOOLKIT_ROOT, "data", "pin-mapping-f103.json")
SCRIPT = os.path.join(TOOLKIT_ROOT, "scripts", "rm_lookup.py")

_PINS_API = ("search_pins", "load_pin_mapping", "format_pins_result",
             "run_pins_mode", "PinMappingError")


def _load_mapping():
    with open(MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)


def _run_process(argv):
    """真进程驱动 (零 argv 打桩); 子进程同守 safe-delete 前置。"""
    env = {**os.environ, "CODEBUDDY_SAFE_DELETE_ENABLED": "0"}
    return subprocess.run([sys.executable, "-X", "utf8", SCRIPT] + argv,
                          capture_output=True, timeout=60,
                          encoding="utf-8", errors="replace", env=env)


class PinsLandedMixin:
    """未实现态 = 全红 (简报②先红); T1 实现 commit 转绿。"""

    def setUp(self):
        missing = [n for n in _PINS_API if not hasattr(rm_lookup, n)]
        if missing:
            self.fail("rm_lookup --pins 消费面未实现 (缺 "
                      + ", ".join(missing) + "; T1 实现 commit 转绿)")


class RegisteredHumanOutputPins(PinsLandedMixin, unittest.TestCase):
    """已入册人读面: 四列逐字金比对 + 反 CANRX/CANTX 替换钉。"""

    def setUp(self):
        super().setUp()
        self.doc = _load_mapping()

    def test_can_human_rows_verbatim_gold(self):
        out = _run_process(["--pins", "CAN"]).stdout
        self.assertIn("=== pin-mapping: CAN ===", out)
        for pin, entry in self.doc["CAN"].items():
            want = (f"  {pin:<6} {entry['function']:<10} "
                    f"{entry['column']:<12} {entry['source']}")
            self.assertIn(want, out,
                          f"{pin} 行人读输出与入册值不符 (逐字金比对)")

    def test_human_output_keeps_registered_spelling(self):
        """F-193 P③ 反替换钉: 表内拼写不得回写替换入册规范名。"""
        out = _run_process(["--pins", "CAN"]).stdout
        self.assertIn("CAN_RX", out)
        self.assertIn("CAN_TX", out)
        self.assertNotIn("CANRX", out)
        self.assertNotIn("CANTX", out)

    def test_lowercase_query_matches_same_rows(self):
        out = _run_process(["--pins", "can"]).stdout
        self.assertIn("=== pin-mapping: CAN ===", out)
        for pin in self.doc["CAN"]:
            self.assertIn(pin, out)


class RegisteredJsonPins(PinsLandedMixin, unittest.TestCase):
    """JSON 已入册形态: {query, registered, rows} 逐字段 == 入册值。"""

    def setUp(self):
        super().setUp()
        self.doc = _load_mapping()

    def test_json_registered_structure_and_rows_gold(self):
        r = _run_process(["--json", "--pins", "CAN"])
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        result = json.loads(r.stdout)
        self.assertEqual(set(result),
                         {"query", "registered", "rows"})
        self.assertEqual(result["query"], "CAN")
        self.assertIs(result["registered"], True)
        want_rows = [
            {"pin": pin, "function": e["function"], "column": e["column"],
             "source": e["source"]}
            for pin, e in self.doc["CAN"].items()]
        self.assertEqual(result["rows"], want_rows)

    def test_json_output_keeps_registered_spelling(self):
        r = _run_process(["--json", "--pins", "CAN"])
        self.assertIn("CAN_RX", r.stdout)
        self.assertNotIn("CANRX", r.stdout)
        self.assertNotIn("CANTX", r.stdout)


class UnregisteredPins(PinsLandedMixin, unittest.TestCase):
    """未入册面: 显式指认 + 动态入册集 + 指路; rc=0 (无果不是错误)。"""

    def setUp(self):
        super().setUp()
        self.doc = _load_mapping()
        self.known = sorted(k for k in self.doc if k != "_meta")

    def test_unregistered_human_names_known_set_and_pointer(self):
        r = _run_process(["--pins", "GPIO"])
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = r.stdout
        self.assertIn("未入册", out)
        self.assertIn("GPIO", out)
        self.assertIn("当前入册外设集: " + ", ".join(self.known), out)
        self.assertIn("CHANGELOG F-189/F-193", out)

    def test_unregistered_json_structure_dynamic_known(self):
        r = _run_process(["--json", "--pins", "TIM2"])
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        result = json.loads(r.stdout)
        self.assertEqual(set(result),
                         {"query", "registered", "known"})
        self.assertEqual(result["query"], "TIM2")
        self.assertIs(result["registered"], False)
        # 集来自文件而非硬编码: CAN ∈ known 且 len == 文件外设块数 (简报口径)
        self.assertIn("CAN", result["known"])
        self.assertEqual(len(result["known"]), len(self.known))

    def test_known_set_tracks_mapping_dict_not_hardcode(self):
        """构造自证: 同一查询词喂不同 dict, known 随 dict 变 — 非硬编码。"""
        base = {"_meta": {"version": "x"},
                "CAN": {"PA11": {"function": "CAN_RX",
                                 "column": "alternate",
                                 "source": "web:DS5319:§3:Table 5:p31"}}}
        r1 = rm_lookup.search_pins("NOPE", base)
        self.assertEqual(r1["known"], ["CAN"])
        wider = dict(base)
        wider["TIM2"] = {"PA0": {"function": "CH1", "column": "additional",
                                 "source": "web:DS5319:§3:Table 5:p27"}}
        r2 = rm_lookup.search_pins("NOPE", wider)
        self.assertEqual(r2["known"], ["CAN", "TIM2"])

    def test_nonexistent_value_rc_zero(self):
        r = _run_process(["--pins", "ZZZ_NO_SUCH_PERIPH"])
        self.assertEqual(r.returncode, 0,
                         f"查询无果不是错误: rc={r.returncode}")
        self.assertIn("未入册", r.stdout)


class ExactMatchPins(PinsLandedMixin, unittest.TestCase):
    """查询词 upper() 精确匹配; 禁模糊 (禁 _relationships/记忆推导)。"""

    def setUp(self):
        super().setUp()
        self.doc = _load_mapping()

    def test_upper_exact_match(self):
        result = rm_lookup.search_pins("can", self.doc)
        self.assertIs(result["registered"], True)
        self.assertEqual({row["pin"] for row in result["rows"]},
                         set(self.doc["CAN"]))

    def test_substring_is_not_fuzzy_matched(self):
        self.assertIs(rm_lookup.search_pins("CA", self.doc)["registered"],
                      False, "子串不得模糊命中 CAN")
        self.assertIs(rm_lookup.search_pins("CAN2", self.doc)["registered"],
                      False)


class MissingOrCorruptDataPins(PinsLandedMixin, unittest.TestCase):
    """缺档/损坏: PinMappingError 点名文件与原因 (F-198 T2 同式);
    夹具全在 tmp (禁写 data/ 真档)。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_default_path_is_repo_data_file(self):
        mapping = rm_lookup.load_pin_mapping()
        self.assertIn("CAN", mapping, "默认路径未指向仓内 pin-mapping 真档")

    def test_missing_file_raises_naming_path(self):
        p = os.path.join(self.tmp, "absent-pin-mapping.json")
        with self.assertRaises(rm_lookup.PinMappingError) as ctx:
            rm_lookup.load_pin_mapping(p)
        self.assertIn(p, str(ctx.exception))
        self.assertIn("不存在", str(ctx.exception))

    def test_corrupt_file_raises_naming_path_and_reason(self):
        p = os.path.join(self.tmp, "corrupt.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{oops")
        with self.assertRaises(rm_lookup.PinMappingError) as ctx:
            rm_lookup.load_pin_mapping(p)
        msg = str(ctx.exception)
        self.assertIn(p, msg)
        self.assertIn("损坏", msg)

    def test_run_pins_mode_error_path_rc1_no_traceback(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = rm_lookup.run_pins_mode(
                "CAN", path=os.path.join(self.tmp, "nope.json"))
        self.assertEqual(rc, 1)
        self.assertIn("Error:", err.getvalue())
        self.assertIn("nope.json", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


class CliProcessPins(PinsLandedMixin, unittest.TestCase):
    """真进程 CLI 面: rc 契约 + 同级互斥。"""

    def test_cli_pins_can_rc_zero(self):
        r = _run_process(["--pins", "CAN"])
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertIn("CAN_RX", r.stdout)

    def test_cli_missing_value_rejected_by_argparse(self):
        r = _run_process(["--pins"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--pins", r.stderr)

    def test_cli_branch_mutual_exclusion(self):
        """同级互斥命中即 return: --recipe 先挂载则 recipe 赢, 输出无
        --pins 内容 (分支次序的契约钉, 与实现挂载序一致)。"""
        r = _run_process(["--pins", "CAN", "--recipe", "PWM"])
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertIn("> 配方:", r.stdout)
        self.assertNotIn("CAN_RX", r.stdout)


if __name__ == "__main__":
    unittest.main()
