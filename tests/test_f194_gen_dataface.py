r"""F-194 (WB-20260927-02) 生成器与数据面三修的钉 — 先钉后修, 钉 commit 首跑红.

三件 (销 WB-05 残量 M-1/L-1/L-4, 对账单 = WB-20260926-04 报告 §一):

  T1  phase_minus_one 消费 available_on_c8 三态 —
      false → UNAVAILABLE (verdict BLOCKED) / true → OK 逐字节不变 /
      字段缺失 → 代码内白名单封闭集 {GPIO, NVIC, SysTick} 内 OK+注记,
      集外单列 WARN 不静默 (F-186 显式豁免纪律, 先例 =
      test_ref_bus_crosscheck.CLOCK_EXEMPTION_SNAPSHOT 封闭集快照钉).

  T2  gen_periph --pin 入口单点校验 ^P[A-G](1[0-5]|[0-9])$ 大写严格 —
      修前三病例 (证据 = 报告 case_pinP/PA20/pa0 修前采档): `--pin P`
      裸 IndexError traceback / `--pin PA20` 与 PA12 同半字节 (CRH<<16)
      静默碰撞 rc=0 / `--pin pa0` 产 IOPaEN·GPIOa 垃圾名 rc=0。
      修后干净 ERROR rc=1 (走 _emit 统一出口); PA12/PB6 正常路径金样
      逐字节不变; 库态 pin_port/pin_num 宽松语义不动 (F-185 P-3 先例).

  T3  生成的 i2c 帮手自足性 (路线 b: 帮手降级不依赖 error_chain) —
      旧输出 8 处引用 error_chain_t/ERR_PLAIN(×6)/ERR_OK 且零定义零
      include (F-078 烟测 stub 恰好供定义, 掩盖此病), 照抄进工程即编译
      失败。修后帮手 int 返回 (0=OK, 负值=超时码, 语义入注释) + 自发射
      #include <stdint.h> (仿 gen_usart unistd 自足先例 F-131)。
      钉 = 引用名零出现 + 无 error-chain 定义的最小 CMSIS stub 过
      gcc -fsyntax-only (本机 arm-gcc 在场实测; 缺席 skipUnless 同 F-078).

零 mock — 全部纯函数注入或 CLI 子进程, 不入 test_stub_ratchet 判据面.
"""
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
import phase_minus_one  # noqa: E402
from wb_common import load_ref  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts", "gen_periph.py")


def _cli(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", SCRIPT] + argv,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, env=env)


# T2 金样 (修前 CLI stdout 逐字节采档, 见报告金比对节) — 校验加闸不得
# 扰动合法引脚输出 (第一契约)。
GOLDEN_PA12 = ('/* PA12 — 通用推挽输出 50MHz */\n'
               'RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;\n'
               '__DSB();\n'
               'GPIOA->CRH &= ~(0xFUL << 16);\n'
               'GPIOA->CRH |=  (0x3UL << 16);\n')
GOLDEN_PB6 = ('/* PB6 — 通用推挽输出 50MHz */\n'
              'RCC->APB2ENR |= RCC_APB2ENR_IOPBEN;\n'
              '__DSB();\n'
              'GPIOB->CRL &= ~(0xFUL << 24);\n'
              'GPIOB->CRL |=  (0x3UL << 24);\n')


class T1AvailableOnC8TriStateTests(unittest.TestCase):
    """T1 (WB-05 M-1): check_chip_support 三态消费 + 白名单封闭集."""

    @classmethod
    def setUpClass(cls):
        cls.ref = load_ref()

    def test_false_peripheral_no_longer_fake_ok(self):
        # 22 个 false 外设的 C8 工程前置闸必须拦 (样本含报告判例 TIM5/FSMC;
        # 状态定名 UNAVAILABLE, 语义 = 不在目标芯片 → BLOCKED, 论证见报告)
        for name in ("TIM5", "FSMC", "SDIO", "UART4"):
            out = phase_minus_one.check_chip_support(name, self.ref)
            self.assertEqual(out["status"], "UNAVAILABLE", name)
            self.assertIn("not available", out["detail"], name)
            self.assertIn("available_on_c8", out["detail"], name)

    def test_true_peripheral_ok_unchanged_byte_for_byte(self):
        # is True 态逐字节不变 (30 个 true 外设零波及)
        out = phase_minus_one.check_chip_support("I2C1", self.ref)
        self.assertEqual(out,
                         {"status": "OK",
                          "detail": "I2C1 in knowledge base (FULL coverage)"})

    def test_system_peripheral_whitelist_closed_set_snapshot(self):
        # F-186 纪律: 封闭集快照钉 — 第四成员入场 = 过设计 (改代码+改本钉)。
        # 数据侧缺字段集与白名单双向互证 (多/少都红)。
        self.assertEqual(phase_minus_one.SYSTEM_PERIPHERALS,
                         {"GPIO", "NVIC", "SysTick"})
        missing = {k for k, v in self.ref["peripherals"].items()
                   if "available_on_c8" not in v}
        self.assertEqual(missing, {"GPIO", "NVIC", "SysTick"})

    def test_field_absent_in_whitelist_annotated_ok(self):
        # GPIO OK 不回归: status 仍 OK, detail 加 system-peripheral 注记
        for name in ("GPIO", "NVIC", "SysTick"):
            out = phase_minus_one.check_chip_support(name, self.ref)
            self.assertEqual(out["status"], "OK", name)
            self.assertIn("system-peripheral, field absent", out["detail"], name)

    def test_field_absent_outside_whitelist_warns_not_silent(self):
        # 缺字段且不在白名单 = 第四形态单列 WARN (不静默)。真数据三缺字段
        # 全在白名单内, 该态只能合成 ref 构造。
        ref = {"peripherals": {"FOO": {"registers": {}}},
               "_relationships": {}}
        out = phase_minus_one.check_chip_support("FOO", ref)
        self.assertEqual(out["status"], "WARN")
        self.assertIn("available_on_c8", out["detail"])

    def test_verdict_blocked_on_unavailable(self):
        # BLOCKED 参与总判定 (verdict 组装随动); 既有矩阵不回归
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "OK"}, "b": {"status": "UNAVAILABLE"}}), "BLOCKED")
        self.assertEqual(phase_minus_one.compute_verdict(
            {"a": {"status": "WARN"}}), "OK_WITH_WARNINGS")

    def test_run_check_tim5_end_to_end_blocked(self):
        # 真档端到端: run_check 全链 verdict BLOCKED (真数据只读, 零 mock)
        out = phase_minus_one.run_check("TIM5", ["PB6"])
        self.assertEqual(out["verdict"], "BLOCKED")
        self.assertEqual(out["checks"]["chip_support"]["status"], "UNAVAILABLE")


class T2PinValidationTests(unittest.TestCase):
    """T2 (WB-05 L-1): --pin 入口单点校验, 大写严格, rc=1 干净 ERROR."""

    def _assert_clean_error(self, r, pin):
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr, "校验错误不得以裸 traceback 面世")
        self.assertIn("/* ERROR", r.stdout)
        self.assertIn("--pin", r.stdout)
        self.assertIn(pin, r.stdout)
        self.assertIn("P[A-G]", r.stdout)   # 文案点名合法形态

    def test_bare_port_flag_rejected(self):
        # 修前: pin_port 裸切片 IndexError traceback (rc=1 但裸崩)
        self._assert_clean_error(
            _cli(["--type", "gpio", "--pin", "P", "--mode", "out-pp-2mhz"]), "P")

    def test_out_of_range_pin_rejected(self):
        # 修前: PA20 与 PA12 同半字节 (CRH<<16) 静默碰撞 rc=0; PA16 同律
        self._assert_clean_error(
            _cli(["--type", "gpio", "--pin", "PA20", "--mode", "out-pp-2mhz"]),
            "PA20")
        self._assert_clean_error(
            _cli(["--type", "gpio", "--pin", "PA16", "--mode", "out-pp-2mhz"]),
            "PA16")

    def test_lowercase_pin_rejected_not_normalized(self):
        # 修前: pa0 直落 IOPaEN/GPIOa 垃圾寄存器名 rc=0; 显式拒绝不归一
        r = _cli(["--type", "gpio", "--pin", "pa0", "--mode", "out-pp-2mhz"])
        self._assert_clean_error(r, "pa0")
        self.assertNotIn("IOPaEN", r.stdout)
        self.assertNotIn("GPIOa", r.stdout)

    def test_valid_boundary_pins_accepted(self):
        # 域边界内合法: 引脚 0 与 15, 端口 A/C
        for pin in ("PA0", "PA15", "PC13"):
            r = _cli(["--type", "gpio", "--pin", pin])
            self.assertEqual(r.returncode, 0, f"{pin}: {r.stdout[:120]}")

    def test_gpio_golden_PA12_PB6_byte_for_byte(self):
        # 正常路径金比对 (修前采档): 校验加闸不得扰动合法引脚输出
        for pin, golden in (("PA12", GOLDEN_PA12), ("PB6", GOLDEN_PB6)):
            r = _cli(["--type", "gpio", "--pin", pin])
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, golden, f"{pin} 金样漂移")

    def test_library_state_stays_permissive(self):
        # F-185 P-3 先例: CLI 收口库态宽 — pin_port/pin_num 域语义不动
        self.assertEqual(gen_periph.pin_port("pa0"), "a")
        self.assertEqual(gen_periph.pin_num("PA20"), 20)


class T3I2cSelfSufficiencyTests(unittest.TestCase):
    """T3 (WB-05 L-4): 生成的 i2c 帮手自足性 (文本面钉)."""

    ERROR_CHAIN_NAMES = ("error_chain_t", "ERR_PLAIN", "ERR_OK")

    def test_error_chain_names_zero_occurrence(self):
        # 路线 (b) 钉: 引用名零出现 — 帮手不依赖任何外部 error-chain 契约
        for label, out in (
                ("i2c1-std", gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7")),
                ("i2c2-fast", gen_periph.gen_i2c("I2C2", 400000, "PB10", "PB11"))):
            for name in self.ERROR_CHAIN_NAMES:
                self.assertNotIn(name, out, f"{label}: {name} 残留")

    def test_helper_int_return_and_self_contained_include(self):
        out = gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7")
        self.assertIn("static int i2c1_write(", out)
        self.assertIn("return 0;", out)
        self.assertIn("#include <stdint.h>", out)
        # 超时诊断语义保留 (注释形态), 负值错误码
        self.assertIn("-1;", out)
        self.assertIn("-5;", out)


# T3 语法面 stub — 仅含 i2c 生成物可引用的 CMSIS 符号; error_chain_t/
# ERR_PLAIN/ERR_OK 故意缺席: 生成物若仍引用, 编译立即红 (病灶语法级探针)。
# 全量符号契约的烟测 stub 在 test_gen_syntax_smoke (F-078), 两处互补。
MINIMAL_STUB = r"""/* F-194 T3 最小 CMSIS stub — 仅 i2c 生成物可引用的符号。
 * error-chain 定义故意缺席: 生成物自足性 = 引用即编译红。地址值无关紧要。*/
#pragma once
#include <stdint.h>

typedef struct {
    volatile uint32_t CR, CFGR, CIR, APB2RSTR, APB1RSTR,
        AHBENR, APB2ENR, APB1ENR, BDCR, CSR;
} RCC_TypeDef;
typedef struct {
    volatile uint32_t CRL, CRH, IDR, ODR, BSRR, BRR, LCKR;
} GPIO_TypeDef;
typedef struct {
    volatile uint32_t CR1, CR2, OAR1, OAR2, DR, SR1, SR2, CCR, TRISE;
} I2C_TypeDef;

#define RCC   ((RCC_TypeDef *)  0x40021000UL)
#define GPIOB ((GPIO_TypeDef *) 0x40010C00UL)
#define I2C1  ((I2C_TypeDef *)  0x40005400UL)
#define I2C2  ((I2C_TypeDef *)  0x40005800UL)

#define RCC_APB2ENR_IOPBEN (1UL << 3)
#define RCC_APB1ENR_I2C1EN (1UL << 21)
#define RCC_APB1ENR_I2C2EN (1UL << 22)
#define __DSB() ((void)0)
"""


def _find_arm_gcc():
    """arm-none-eabi-gcc 探测 (F-078 同款: machine.json gcc_path 优先,
    PATH 兜底, --version 试活); 失败返回 None → 整组 skip 可诊断。"""
    exe = None
    try:
        gcc_path = (wb_common_load_machine().get("gcc_path") or "").strip()
    except Exception:
        gcc_path = ""
    if gcc_path:
        cand = os.path.join(gcc_path, "arm-none-eabi-gcc.exe" if sys.platform == "win32"
                            else "arm-none-eabi-gcc")
        if os.path.isfile(cand):
            exe = cand
    if exe is None:
        exe = shutil.which("arm-none-eabi-gcc")
    if exe is None:
        return None
    try:
        probe = subprocess.run([exe, "--version"], capture_output=True,
                               text=True, timeout=30)
        if probe.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe


def wb_common_load_machine():
    # 延迟导入避免模块顶部 sys.path 顺序敏感 (wb_common 同在 scripts/)
    import wb_common
    return wb_common.load_machine()


_ARM_GCC = _find_arm_gcc()


@unittest.skipUnless(_ARM_GCC, "arm-none-eabi-gcc 不在场 (CI 默认不装工具链; F-078 同守卫)")
class T3I2cSyntaxOnlyTests(unittest.TestCase):
    """T3 语法面: i2c 生成物在**无 error-chain 定义**的最小 CMSIS stub 下
    过 -fsyntax-only — 自足性的机器判据 (修前引用缺席定义必编译红)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.stub = os.path.join(cls.tmp, "f194_i2c_minimal_stub.h")
        with open(cls.stub, "w", encoding="ascii", errors="replace") as f:
            f.write(MINIMAL_STUB)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _syntax_only(self, label, code):
        # F-078 同款机械变换: 剥行首 static 后整体包进函数 (GNU C 嵌套函数
        # 合法) — 换取语法与符号契约检查, 变换不引入/不消除任何符号。
        stripped = re.sub(r"(?m)^static ", "", code)
        wrapped = "void gen_smoke_probe(void) {\n" + stripped + "\n}\n"
        r = subprocess.run(
            [_ARM_GCC, "-fsyntax-only", f"-I{self.tmp}",
             "-include", self.stub, "-x", "c", "-"],
            input=wrapped.encode("utf-8"), capture_output=True, timeout=30)
        stderr = r.stderr.decode("utf-8", "replace")
        self.assertEqual(
            r.returncode, 0,
            f"i2c 生成物 '{label}' 在最小 CMSIS stub 下未过语法检查:\n"
            f"--- gcc stderr ---\n{stderr.strip()[:1500]}")

    def test_i2c_outputs_compile_without_error_chain_definitions(self):
        for label, code in (
                ("i2c1-std", gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7")),
                ("i2c2-fast", gen_periph.gen_i2c("I2C2", 400000, "PB10", "PB11"))):
            with self.subTest(case=label):
                self._syntax_only(label, code)


if __name__ == "__main__":
    unittest.main()
