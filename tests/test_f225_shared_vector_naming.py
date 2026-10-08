r"""F-225 (GAP-F-20 收口): 共享向量 TIM 的 ISR 名 —— 生成物必须落在向量表实名域内。

病灶 (F-191 P 面 P-1 登记, GAP-F-20): gen_timer_int 的向量名逻辑仅对 TIM1
特判, TIM9/12/13/14 生成 naive 名 (TIM9_IRQHandler / TIM9_IRQn)。

两环境定性 (2026-10-08 双源与真工具链实测):
  * 全 CMSIS 工程: ST 头 "painless codes migration" 别名区
    (stm32f103xb.h:10207 族 / stm32f103xg.h:11908 族) 把 naive 名映射到
    实名 — arm-none-eabi-gcc -E 逐名实测旧名侥幸绑定;
  * 样例工厂 (生成物的第一消费现场): f103-common/f103_regs.h 明言
    "无 HAL/LL/CMSIS 依赖" + startup.c 向量表用 CMSIS 实名 — 无别名区
    兜底, naive 名是**孤儿符号**: 编译链接全绿、ISR 永不执行 (C 类静默)。
    链接级实证: 实名 extern 探针引用 naive 生成物 → undefined reference。

修复 = 生成物一律发射 CMSIS 实名 (数据域 gen-maps tim_irq_name, 与 ref.json
_relationships.<P>.irq.name 互证; 实名在样例工厂与 CMSIS 两环境均绑定)。
TIM1 同步由 TIM1_UP_* 升级为 xg 口径实名 TIM1_UP_TIM10_* —— 旧名在无 CMSIS
样例环境同为孤儿 (startup.c 向量 25 = TIM1_UP_TIM10_IRQHandler)。

本文件两层钉:
  1. 命名发射面 (恒跑, 零工具链依赖);
  2. 链接绑定面 (arm-none-eabi-gcc 在场时; CI syntax-smoke job 已装工具链):
     按样例工厂环境构造 TU —— 实名探针必须链接通过; 反向 naive 探针必须
     链接失败 (双向钉)。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gen_periph  # noqa: E402
import wb_common  # noqa: E402

GCC_TIMEOUT = 30

# (IRQn 实名, Handler 实名, IRQ 号) — 来源: ref.json _relationships.<P>.irq
# (锚 stm32f103xg.h) × examples/f103-common/startup.c 向量表, 两源逐字一致。
_SHARED_AND_TIM1 = {
    "TIM1": ("TIM1_UP_TIM10_IRQn", "TIM1_UP_TIM10_IRQHandler", 25),
    "TIM9": ("TIM1_BRK_TIM9_IRQn", "TIM1_BRK_TIM9_IRQHandler", 24),
    "TIM12": ("TIM8_BRK_TIM12_IRQn", "TIM8_BRK_TIM12_IRQHandler", 43),
    "TIM13": ("TIM8_UP_TIM13_IRQn", "TIM8_UP_TIM13_IRQHandler", 44),
    "TIM14": ("TIM8_TRG_COM_TIM14_IRQn", "TIM8_TRG_COM_TIM14_IRQHandler", 45),
}

_NON_SHARED = {"TIM2": 28, "TIM3": 29, "TIM4": 30,
               "TIM5": 50, "TIM6": 54, "TIM7": 55}


class VectorNameEmissionTests(unittest.TestCase):
    """命名发射面: 生成物里的 ISR 定义与 NVIC 注释必须用 CMSIS 实名。"""

    def test_shared_vector_timers_emit_real_names(self):
        for timer, (irqn, handler, irq) in _SHARED_AND_TIM1.items():
            with self.subTest(timer=timer):
                out = gen_periph.gen_timer_int(timer, 1, 72)
                self.assertIn(f"void {handler}(void) {{", out)
                self.assertIn(f"// {irqn} = {irq}", out)

    def test_naive_names_not_emitted(self):
        for timer in _SHARED_AND_TIM1:
            with self.subTest(timer=timer):
                out = gen_periph.gen_timer_int(timer, 1, 72)
                self.assertNotIn(f"void {timer}_IRQHandler(void)", out)
                self.assertNotIn(f"// {timer}_IRQn =", out)

    def test_non_shared_timer_names_unchanged(self):
        # 修复不得波及常规命名 (TIM2~4 有金面 fixture 兜底, 此处逐字节钉)
        for timer, num in _NON_SHARED.items():
            with self.subTest(timer=timer):
                out = gen_periph.gen_timer_int(timer, 1, 72)
                self.assertIn(f"void {timer}_IRQHandler(void) {{", out)
                self.assertIn(f"// {timer}_IRQn = {num}", out)

    def test_unregistered_timer_fallback_preserved(self):
        # 库态 .get 缺省语义不变 (CLI 层另有入口闸): 未登记名维持 naive fallback
        out = gen_periph.gen_timer_int("TIM99", 1, 72)
        self.assertIn("void TIM99_IRQHandler(void) {", out)
        self.assertIn("// TIM99_IRQn = 28", out)


def _find_arm_gcc():
    """定位 arm-none-eabi-gcc (与 test_gen_syntax_smoke._find_arm_gcc 同款:
    machine.json gcc_path 优先, PATH 兜底; 探测失败返回 None)。"""
    exe = None
    try:
        gcc_path = (wb_common.load_machine().get("gcc_path") or "").strip()
    except Exception:
        gcc_path = ""
    if gcc_path:
        cand = os.path.join(gcc_path,
                            "arm-none-eabi-gcc.exe" if sys.platform == "win32"
                            else "arm-none-eabi-gcc")
        if os.path.isfile(cand):
            exe = cand
    if exe is None:
        exe = shutil.which("arm-none-eabi-gcc")
    if exe is None:
        return None
    try:
        probe = subprocess.run([exe, "--version"], capture_output=True,
                               text=True, timeout=GCC_TIMEOUT)
        if probe.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe


_ARM_GCC = _find_arm_gcc()

_REGS_DIR = os.path.join(wb_common.TOOLKIT_ROOT, "examples", "f103-common")


@unittest.skipUnless(_ARM_GCC, "arm-none-eabi-gcc 不在场 (CI 由 syntax-smoke job 安装)")
class VectorBindingLinkTests(unittest.TestCase):
    """链接绑定面: 按样例工厂环境 (无 CMSIS 裸偏移头 + 实名向量表引用) 构造
    TU —— 向量表引用的实名必须由生成物提供定义, 否则 ISR 永不执行。"""

    def _link(self, timer, probe_handler, isr_source):
        """isr_source: 生成物 ISR 段 (文件作用域); probe_handler: 向量里引用的名。"""
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "bind.c")
            elf = os.path.join(td, "bind.elf")
            with open(src, "w", encoding="utf-8") as f:
                f.write('#include "f103_regs.h"\n')
                f.write(isr_source + "\n")
                f.write(f"extern void {probe_handler}(void);\n")
                f.write(f"void (*const isr_probe_{timer}[1])(void) = "
                        f"{{ {probe_handler} }};\n")
            return subprocess.run(
                [_ARM_GCC, "-mcpu=cortex-m3", "-mthumb", "-nostdlib",
                 f"-I{_REGS_DIR}", src, "-o", elf],
                capture_output=True, text=True, timeout=GCC_TIMEOUT)

    @staticmethod
    def _isr_part(timer):
        code = gen_periph.gen_timer_int(timer, 1, 72)
        marker = "/* 3. ISR */"
        # 生成物是"贴进函数体的片段": 裸语句段不能放文件作用域, 只取
        # 文件作用域合法的 ISR 段 (与样例消费方式一致) 做链接级验证。
        assert marker in code, "gen_timer_int 输出缺 ISR 段标记 — 夹具失配"
        return code.split(marker, 1)[1]

    def test_real_name_probe_links(self):
        for timer, (_irqn, handler, _irq) in _SHARED_AND_TIM1.items():
            with self.subTest(timer=timer):
                r = self._link(timer, handler, self._isr_part(timer))
                self.assertEqual(
                    r.returncode, 0,
                    f"{timer}: 向量表实名 {handler} 未被生成物定义 "
                    f"(ISR 孤儿, 样例环境永不执行):\n{r.stderr[:1200]}")

    def test_naive_name_probe_does_not_link(self):
        # 双向钉: naive 名不再是定义 — 若它被引用必须链接失败。
        r = self._link("TIM9", "TIM9_IRQHandler", self._isr_part("TIM9"))
        self.assertNotEqual(r.returncode, 0,
                            "naive 名 TIM9_IRQHandler 竟然链接成功 — "
                            "生成物未收敛到实名单一形态")
        self.assertIn("undefined reference", r.stderr)


if __name__ == "__main__":
    unittest.main()
