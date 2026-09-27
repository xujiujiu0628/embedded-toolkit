r"""F-198 (WB-20260927-05) 同族清尾四件钉 — T1 gen_systick/gen_adc stdint
自足 + T2 merge_into_ref peripherals 裸下标 + T3 mcp resolve_project 库根
闸 + T4 atomic_write_json 失败路径 .tmp 清理。

事实源 = WB-20260927-03 报告 §七 P-1/P-2/P-3 + WB-20260926-04 报告 §一 L-8。
先钉后修: 四病各红 (修前), 撤销实验复现; 正常面反向金钉常绿两侧, 修程
若动正常路径 wire 形态即红。

零 mock (不入 test_stub_ratchet 判据面); T1 gcc 面本机 arm-gcc 在场实跑
否则 skipUnless 显式跳过 (F-195 T6 同口径); T3 库根闸只读判定 (F-015
残留 config 本体是 data 面裁决, 本单零翻动); T4 全程 tempdir。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402
import mcp_server  # noqa: E402
import svd_to_json  # noqa: E402
import wb_common  # noqa: E402

TK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ════════════════════════════ T1 (F-195 P-1 同族第三/四笔) ════════════════════════════

GCC_TIMEOUT = 30

# 最小 stub: 无 #include <stdint.h> 预置 (F-078 smoke stub 预置 stdint 恰好
# 掩盖自足缺口 — 本钉剥掉预置, gen_systick/gen_adc 的裸 uint 直接编译红)。
# 面 = F-195 T6 _MINI_STUB 同构 + SysTick/ADC 族符号。
_MINI_STUB = r"""#pragma once
#define __DSB() ((void)0)
#define __WFI() ((void)0)
typedef struct { volatile unsigned int CR, CFGR, CIR, APB2RSTR, APB1RSTR,
    AHBENR, APB2ENR, APB1ENR, BDCR, CSR; } RCC_TypeDef;
typedef struct { volatile unsigned int CRL, CRH, IDR, ODR, BSRR, BRR, LCKR;
} GPIO_TypeDef;
typedef struct { volatile unsigned int CTRL, LOAD, VAL, CALIB; } SysTick_Type;
typedef struct { volatile unsigned int SR, DR, SMPR1, SMPR2, HTR, LTR,
    SQR1, SQR2, SQR3, CR1, CR2; } ADC_TypeDef;
#define RCC     ((RCC_TypeDef *)    0x40021000UL)
#define GPIOA   ((GPIO_TypeDef *)   0x40010800UL)
#define ADC1    ((ADC_TypeDef *)    0x40012400UL)
#define SysTick ((SysTick_Type *)   0xE000E010UL)
#define RCC_APB2ENR_IOPAEN     (1UL << 2)
#define RCC_APB2ENR_ADC1EN     (1UL << 9)
#define SysTick_CTRL_ENABLE    (1UL << 0)
#define SysTick_CTRL_TICKINT   (1UL << 1)
#define SysTick_CTRL_CLKSOURCE (1UL << 2)
"""


def _find_arm_gcc():
    exe = None
    try:
        gcc_path = (wb_common.load_machine().get("gcc_path") or "").strip()
    except Exception:
        gcc_path = ""
    if gcc_path:
        cand = os.path.join(
            gcc_path,
            "arm-none-eabi-gcc.exe" if sys.platform == "win32"
            else "arm-none-eabi-gcc")
        if os.path.isfile(cand):
            exe = cand
    return exe


_MINI_GCC = _find_arm_gcc()


class GenSystickAdcStdintSelfEmitTests(unittest.TestCase):
    """T1: gen_systick (uint32_t×3) / gen_adc (uint16_t/uint32_t×3) 帮手
    stdint 自足 (F-195 T6 usart/spi 同族第三/四笔)。

    平台无关红面: include 前置 (块首自发射, 恰一次, 先于首个 uintN_t);
    gcc 红面: 无 stdint 预置 stub 下 -fsyntax-only (修前裸 uint 编译红)。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.stub = os.path.join(cls.tmp, "mini_stub.h")
        with open(cls.stub, "w", encoding="ascii") as f:
            f.write(_MINI_STUB)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_include_precedes_first_uint_use_exactly_once(self):
        for name, gen in (
                ("systick", lambda: gen_periph.gen_systick(1000)),
                ("adc", lambda: gen_periph.gen_adc("ADC1", 1, "PA1"))):
            with self.subTest(case=name):
                out = gen()
                self.assertEqual(out.count("#include <stdint.h>"), 1,
                                 f"{name}: 恰好自发射一次 (已含则不重复)")
                self.assertLess(
                    out.index("#include <stdint.h>"),
                    re.search(r"uint(8|16|32|64)_t", out).start(),
                    f"{name}: include 必须先于首个 uintN_t 引用 (块首)")

    def _syntax_check(self, name, code):
        # 机械变换与 F-078 smoke / F-195 T6 同口径: 剥行首 static 后包进
        # 函数 (GNU C 嵌套函数; #include 在函数体内即原地展开)。
        stripped = re.sub(r"(?m)^static ", "", code)
        wrapped = "void gen_smoke_probe(void) {\n" + stripped + "\n}\n"
        r = subprocess.run(
            [_MINI_GCC, "-fsyntax-only", f"-I{self.tmp}",
             "-include", self.stub, "-x", "c", "-"],
            input=wrapped.encode("utf-8"), capture_output=True,
            timeout=GCC_TIMEOUT)
        stderr = r.stderr.decode("utf-8", "replace")
        self.assertEqual(
            r.returncode, 0,
            f"'{name}' 在无 stdint 预置 stub 下编译失败:\n{stderr[:1500]}")

    @unittest.skipUnless(_MINI_GCC, "arm-none-eabi-gcc 不在场 (machine.json)")
    def test_systick_compile_without_preset_stdint(self):
        self._syntax_check("systick", gen_periph.gen_systick(1000))

    @unittest.skipUnless(_MINI_GCC, "arm-none-eabi-gcc 不在场 (machine.json)")
    def test_adc_compile_without_preset_stdint(self):
        self._syntax_check("adc", gen_periph.gen_adc("ADC1", 1, "PA1"))


# ════════════════════════════ T2 (F-195 P-2) ════════════════════════════

class MergeIntoRefPeripheralsGuardTests(unittest.TestCase):
    """T2: merge_into_ref 的 ref["peripherals"] 裸下标 (svd_to_json.py:273)
    — 缺键/非对象 → 显式 ValueError 点名键 (修前裸 KeyError traceback),
    与 F-195 T5 _meta 面同式; 正常 merge 路径行为不变 (反向钉)。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.ref_path = os.path.join(self.ws, "ref.json")

    def _write_ref(self, obj):
        with open(self.ref_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    _DATA = {"USART1": {"base": "0x40013800", "bus": "APB2", "desc": "usart",
                        "registers": {"SR": {"offset": "0x00"}}}}

    def test_missing_peripherals_explicit_error_not_bare_keyerror(self):
        self._write_ref({"_meta": {"version": "2.0.0", "chip": "T",
                                   "peripheral_count": 0}})
        with self.assertRaises(ValueError,
                               msg="peripherals 缺键应显式 ValueError "
                                   "而非裸 KeyError"):
            svd_to_json.merge_into_ref(self._DATA, self.ref_path)
        # 报错路径同样不得损坏原文件
        with open(self.ref_path, "rb") as f:
            self.assertIn(b"_meta", f.read())

    def test_non_object_peripherals_rejected_too(self):
        self._write_ref({"_meta": {"version": "2.0.0", "chip": "T",
                                   "peripheral_count": 0},
                         "peripherals": ["not", "a", "dict"]})
        with self.assertRaises(ValueError,
                               msg="peripherals 非对象应同式拒绝"):
            svd_to_json.merge_into_ref(self._DATA, self.ref_path)

    def test_normal_merge_path_unchanged(self):
        # 反向钉: 正常 merge (骨架带空 peripherals) 语义不变 —
        # 新外设入库 + available_on_c8 注记 + peripheral_count 随动。
        self._write_ref({"_meta": {"version": "2.0.0", "chip": "T",
                                   "peripheral_count": 1},
                         "peripherals": {"GPIOA": {
                             "base": "0x40010800",
                             "registers": {"CR": {"offset": "0x00"}}}}})
        added, total = svd_to_json.merge_into_ref(self._DATA, self.ref_path)
        self.assertEqual((added, total), (1, 2))
        with open(self.ref_path, encoding="utf-8") as f:
            ref = json.load(f)
        self.assertIn("USART1", ref["peripherals"])
        self.assertTrue(ref["peripherals"]["USART1"]["available_on_c8"])
        self.assertEqual(ref["_meta"]["peripheral_count"], 2)


# ════════════════════════════ T3 (WB-05 L-8) ════════════════════════════

class ResolveProjectToolkitRootGateTests(unittest.TestCase):
    """T3: resolve_project 库根本身 → McpToolError (WB-05 L-8 防线落空收口)。

    库根 .workbench/config.json 是 F-015 时代残留 (data 面裁决, 本单不碰
    残留本体) — 闸在 resolve_project 侧收口, 不依赖残留是否在场。正常
    工程路径/不存在路径行为不变 (撤销实验的反向钉)。"""

    def test_toolkit_root_rejected(self):
        with self.assertRaises(mcp_server.McpToolError,
                               msg="库根本身不是工程, 必须拒绝"):
            mcp_server.resolve_project(mcp_server.TOOLKIT_ROOT)

    def test_toolkit_root_variants_rejected(self):
        # 尾斜杠 / "." 段 / (Windows) 大小写盘符 — 归一后同判。
        variants = [
            mcp_server.TOOLKIT_ROOT + os.sep,
            mcp_server.TOOLKIT_ROOT + os.sep + ".",
        ]
        if os.name == "nt":
            drive, tail = os.path.splitdrive(mcp_server.TOOLKIT_ROOT)
            variants.append(drive.lower() + tail)      # 大小写盘符
            variants.append(drive + tail.swapcase())   # 大小写路径段
        for v in variants:
            with self.subTest(variant=v):
                with self.assertRaises(mcp_server.McpToolError,
                                       msg=f"库根变体必须拒绝: {v}"):
                    mcp_server.resolve_project(v)

    def test_valid_project_still_resolves(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        os.makedirs(os.path.join(ws, ".workbench"))
        with open(os.path.join(ws, ".workbench", "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"builder": "gcc"}, f)
        self.assertEqual(mcp_server.resolve_project(ws),
                         os.path.abspath(ws))

    def test_missing_dir_still_rejected(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        with self.assertRaises(mcp_server.McpToolError):
            mcp_server.resolve_project(os.path.join(ws, "nope"))


# ════════════════════════════ T4 (F-195 P-3) ════════════════════════════

class AtomicWriteJsonFailureCleanupTests(unittest.TestCase):
    """T4: atomic_write_json dump/序列化中途失败 → {path}.{pid}.tmp 残骸
    清理 (F-023 家族既有行为收口; F-133/j runtime 侧同口径)。

    wb_common 是共享层第一单入场改 (消费方: svd_to_json/feedback_db/
    checkpoint_ledger/release; runtime_common.save_json_file 为 F-133/j
    已收的并行实现, 口径对齐) — 正常路径逐字节
    反向金钉强制: 产物 == json.dumps(ensure_ascii=False, indent=2) 的
    UTF-8/LF 形态 (无尾随换行), 修程若动成功路径即红。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.target = os.path.join(self.ws, "out.json")

    def _tmp_names(self):
        return [n for n in os.listdir(self.ws) if ".tmp" in n]

    def test_serialization_failure_cleans_tmp_and_reraises(self):
        with open(self.target, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"keep": 1}, f)
        snapshot = open(self.target, "rb").read()
        bad = {"set": {1, 2}}   # set 不可序列化 → json.dump 中途 TypeError
        with self.assertRaises(TypeError, msg="异常必须原样上抛不吞不裹"):
            wb_common.atomic_write_json(self.target, bad)
        with open(self.target, "rb") as f:
            self.assertEqual(f.read(), snapshot, "失败路径原文件逐字节完好")
        self.assertEqual(self._tmp_names(), [],
                         "失败路径不得残留 .tmp (修前残骸实锤)")

    def test_normal_path_bytes_match_old_form(self):
        # 反向金钉 (共享层首改强制): 正常写产物与旧实现逐字节同。
        data = {"b": 2, "a": [1, 2], "中": "文", "nested": {"x": None,
                                                            "y": True}}
        wb_common.atomic_write_json(self.target, data)
        with open(self.target, "rb") as f:
            raw = f.read()
        expected = json.dumps(data, ensure_ascii=False,
                              indent=2).encode("utf-8")
        self.assertEqual(raw, expected,
                         "正常写与旧实现逐字节同 (成功路径语义零动)")
        self.assertNotIn(b"\r\n", raw, "LF-only 口径不变 (F-022)")
        self.assertEqual(self._tmp_names(), [], "成功路径无 .tmp 残留")


if __name__ == "__main__":
    unittest.main()
