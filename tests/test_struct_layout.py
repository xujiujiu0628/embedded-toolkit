r"""examples 结构体成员偏移 vs ref.json 静态断言钉 (F-213)。

背景: F-213 三处结构体布局错误 (NVIC 五数组无保留间隙 / CAN 滤波器区
-0x20 且组数 28 应为 14 / BKP 的 RTCCR-CR-CSR 排在 DR42 之后), 真机上
写入保留区静默失效, 而 host mock 以同一错布局重定向静态内存, 结构上
无法自证——正是本仓「HAL_OK != 字节正确」「B 类静默是敌人」叙事要消灭
的失败模式。本钉把"手写层布局 == 数据层登记"变成机检。

## 为什么用 offsetof 而不是解析 C 语法

本钉问的是**编译器的答案**, 不是我们以为的答案。生成 C 片段用
offsetof() 取真实成员偏移, 编译运行后与 ref.json 比对。解析 C 文本会
在多行声明/数组维度/嵌套结构体上出错, 而 offsetof 不会。

## ref.json ↔ 结构体 的口径归一 (本钉的核心, 也是最初被低估的部分)

ref.json 与头文件并非同一表达口径, 朴素比对会自带大量假阳性。四类差异
逐条归一, 每条都有出处, 全部在本文件集中声明:

1. **基址口径 (BKP)**: ref.json peripherals.BKP.base = 0x40006C04 且
   DR1.offset = "0x0" (以 DR1 为 origin); 头文件按外设基址 0x40006C00
   表示, DR1 = +0x04。两者绝对地址相等, 差一个常数 0x04。ref.json 该
   条自带 note(GAP-D-2) 说明此惯例。归一: BKP 的 offset 加 4。

2. **键名前缀 (CAN)**: ref.json 里控制域寄存器带前缀 (CAN_MCR/CAN_BTR),
   滤波器寄存器不带 (F0R1/F13R2)。归一: CAN 键统一剥 "CAN_" 前缀再比。

3. **基址形态 (GPIO)**: ref.json peripherals.GPIO.base 是聚合字符串
   "A:0x... B:0x...", GPIOA..GPIOG 才是单值。归一: 只用 GPIOA 比对,
   聚合条目不参与。

4. **成员集合差异 (TIM1/TIM2/TIM6/TIM7)**: 结构体是共用布局, 但
   TIM1/8 多 BDTR+RCR (高级定时器), TIM6/7 少 CCR1-4/DCR/DMAR。归一:
   只比对**两侧都有**的成员, 单侧成员不参与 (否则假阳性)。

## 覆盖边界 (诚实声明, 不假装全覆盖)

- 只比对两侧都存在同名成员的项; ref.json 有而结构体没有的寄存器 (如
  TIM12-14 的分类差异) **不比对**——它们不落在本头文件的结构体布局里。
- 未被任何结构体引用的外设 (FSMC/DMA2/DBG/USB 等) 不参与。
- 本钉钉的是**偏移一致**, 不钉寄存器位域语义 (那是 ref.json 自洽性
  的另一条线)。
"""
import json
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER_DIR = os.path.join(ROOT, "examples", "f103-common")
HEADER = os.path.join(HEADER_DIR, "f103_regs.h")
REF_JSON = os.path.join(ROOT, "data", "stm32f103-ref.json")


def _load_ref():
    with open(REF_JSON, encoding="utf-8") as f:
        return json.load(f)


# (结构体类型名, ref.json 外设名, 基址归一常数)
#   常数 = 加到 ref.json offset 上才是"外设相对"口径。
#   BKP 4 = ref.json 以 DR1 为 origin (0x0), 外设相对 DR1@0x04。
_STRUCT_MAP = [
    ("RCC_TypeDef", "RCC", 0),
    ("GPIO_TypeDef", "GPIOA", 0),
    ("USART_TypeDef", "USART1", 0),
    ("TIM_TypeDef", "TIM1", 0),
    ("ADC_TypeDef", "ADC1", 0),
    ("I2C_TypeDef", "I2C1", 0),
    ("SPI_TypeDef", "SPI1", 0),
    ("SysTick_Type", "SysTick", 0),
    ("NVIC_Type", "NVIC", 0),
    ("DMA_Channel_TypeDef", "DMA1", 0),
    ("FLASH_TypeDef", "FLASH", 0),
    ("EXTI_TypeDef", "EXTI", 0),
    ("AFIO_TypeDef", "AFIO", 0),
    ("IWDG_TypeDef", "IWDG", 0),
    ("WWDG_TypeDef", "WWDG", 0),
    ("CRC_TypeDef", "CRC", 0),
    ("CAN_TypeDef", "CAN", 0),
    ("DAC_TypeDef", "DAC", 0),
    ("RTC_TypeDef", "RTC", 0),
    ("PWR_TypeDef", "PWR", 0),
    ("SDIO_TypeDef", "SDIO", 0),
    ("BKP_TypeDef", "BKP", 4),      # 口径 1
]

# ref.json 键名 → 结构体成员名的显式改名表 (不能机械归一的少数项)
_RENAME = {
    # SysTick: ref.json 用架构全名, 结构体用缩写
    "SYST_CSR": "CTRL", "SYST_RVR": "LOAD",
    "SYST_CVR": "VAL", "SYST_CALIB": "CALIB",
}

# 结构体里成组的保留段 (不参与比对, 只需保证其后成员偏移正确)
_SKIP_MEMBER = re.compile(r"^RESERVED\d*$")


def _canon_ref_key(key: str) -> str:
    """CAN 口径 2: 剥 CAN_ 前缀。"""
    return key[4:] if key.startswith("CAN_") else key


def _parse_header_members():
    """从 f103_regs.h 抽 (结构体名 -> [成员名...])。

    只解析顶层 typedef struct ... } Name; 的成员声明块; 嵌套匿名 struct
    (CAN 的 TXM/RXM) 整体记为一个成员块跳过——它们不在比对范围 (ref.json
    以 TI0R 等平铺登记, 已在组内偏移上被前后成员夹逼验证)。
    """
    with open(HEADER, encoding="utf-8") as f:
        text = f.read()
    # 去掉块注释与行注释, 避免注释里的 typedef 被误认
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)

    out = {}
    for m in re.finditer(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", text, re.S):
        body, name = m.group(1), m.group(2)
        if "{" in body:                 # 含嵌套匿名 struct → 整体跳过
            continue
        members = []
        for decl in body.split(","):
            decl = decl.strip()
            if not decl:
                continue
            mm = re.match(r"^(?:volatile\s+)?(?:const\s+)?\w+\s+(\w+)", decl)
            if mm:
                members.append(mm.group(1))
        if members:
            out[name] = members
    return out


def _member_names(ref_regs):
    """ref.json 寄存器名 → 候选结构体成员名列表 (含改名表)。"""
    names = set()
    for k in ref_regs:
        ck = _canon_ref_key(k)
        names.add(_RENAME.get(ck, ck))
    return names


def _host_gcc():
    """定位 host gcc。找不到返回 None (调用方降级到编译期断言路径)。"""
    exe = "gcc.exe" if os.name == "nt" else "gcc"
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    return None


def _arm_gcc():
    """定位 arm-none-eabi-gcc。CI 只装它 (不装 host gcc), 故需要这条降级路径。"""
    for name in ("arm-none-eabi-gcc.exe", "arm-none-eabi-gcc"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d:
                continue
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    # machine.json 的 gcc_path 也是权威来源
    mj = os.path.join(ROOT, "machine.json")
    if os.path.isfile(mj):
        try:
            with open(mj, encoding="utf-8") as f:
                gp = json.load(f).get("gcc_path", "")
            cand = os.path.join(gp, "arm-none-eabi-gcc.exe" if os.name == "nt"
                                else "arm-none-eabi-gcc")
            if gp and os.path.isfile(cand):
                return cand
        except (OSError, ValueError):
            pass
    return None


def _static_assert_probe(pairs, tmpdir):
    """降级路径: 生成 _Static_assert 片段用交叉编译器**编译期**校验。

    CI 只装 arm-none-eabi (装不了 host gcc 也跑不了 ARM 二进制), 运行探针
    在那里必然不可用。此路径不运行任何东西——编译通过即断言成立, 编译失败
    即断言不成立, 由编译器把错值与期望值一并报出。
    """
    gcc = _arm_gcc()
    if not gcc:
        return None
    lines = []
    for i, (struct, mem, expect) in enumerate(pairs):
        lines.append(
            '_Static_assert(offsetof(%s, %s) == 0x%X, '
            '"%s.%s 应为 0x%X");' % (struct, mem, expect, struct, mem, expect))
    src = ('#include <stddef.h>\n#include "f103_regs.h"\n'
           + "\n".join(lines) + "\n")
    cpath = os.path.join(tmpdir, "sa.c")
    with open(cpath, "w", encoding="utf-8") as f:
        f.write(src)
    return subprocess.run(
        [gcc, "-c", "-I", HEADER_DIR, cpath, "-o", os.path.join(tmpdir, "sa.o")],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)


class StructLayoutOffsetTests(unittest.TestCase):
    """结构体成员偏移 == ref.json 登记偏移 (经口径归一)。

    实现方式: 生成 C 片段用 offsetof() 取编译器认定的真实偏移, 与 ref.json
    比对。任一项不符即红。
    """

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.ref = _load_ref()["peripherals"]
        cls.members = _parse_header_members()
        cls.checked = {}          # 结构体 -> [(member, ref_key, expect)]
        for struct, periph, adj in _STRUCT_MAP:
            if struct not in cls.members:
                continue
            if periph not in cls.ref:
                continue
            regs = cls.ref[periph]["registers"]
            canon = {}
            for k in regs:
                ck = _canon_ref_key(k)
                canon[_RENAME.get(ck, ck)] = (k, regs[k]["offset"])
            pairs = []
            for mem in cls.members[struct]:
                if _SKIP_MEMBER.match(mem):
                    continue
                if mem not in canon:
                    # 数组成员的**起始**偏移可由其首元素推得: ref.json 以
                    # 平铺名登记 (F0R1 对应结构体的 F[0][0])。这类成员单列,
                    # 由 test_critical_offsets_are_pinned / CAN 专用例兜住,
                    # 不参与逐名比对 (否则需要按维度展开, 复杂度不换收益)。
                    continue
                ref_key, off = canon[mem]
                pairs.append((mem, ref_key, int(off, 16) + adj))
            if pairs:
                cls.checked[struct] = pairs

    def _offsets_for(self, struct, member_names):
        """编译运行取 offsetof 真值。返回 {member: offset}。"""
        gcc = _host_gcc()
        if not gcc:
            self.skipTest("未找到 host gcc, 结构体偏移钉无法执行")
        exprs = "".join(
            '    printf("%s=%%zu\\n", offsetof(%s, %s));\n' % (mem, struct, mem)
            for mem in member_names)
        src = (
            "#include <stdio.h>\n#include <stddef.h>\n"
            '#include "f103_regs.h"\n'
            "int main(void){\n" + exprs + "    return 0;\n}\n")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cpath = os.path.join(td, "probe.c")
            exe = os.path.join(td, "probe.exe" if os.name == "nt" else "probe")
            with open(cpath, "w", encoding="utf-8") as f:
                f.write(src)
            r = subprocess.run(
                [gcc, "-pipe", "-I", HEADER_DIR, cpath, "-o", exe],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
            if r.returncode != 0:
                self.fail(f"{struct}: offsetof 探针编译失败\n{r.stderr[-1500:]}")
            run = subprocess.run([exe], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60)
        out = {}
        for line in run.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = int(v.strip())
        return out

    def test_struct_member_offsets_match_ref_json(self):
        """逐结构体核对成员偏移。任何错位都红——这正是 F-213 三处缺陷的钉。"""
        self.assertTrue(self.checked, "口径归一后无可比对项, 归一逻辑有误")
        mismatches = []
        for struct in sorted(self.checked):
            actual = self._offsets_for(struct, [m for m, _, _ in self.checked[struct]])
            for mem, ref_key, expect in self.checked[struct]:
                got = actual.get(mem)
                if got is None:
                    mismatches.append(
                        f"{struct}.{mem}: 探针未返回该项 (ref.json {ref_key})")
                elif got != expect:
                    mismatches.append(
                        f"{struct}.{mem}: 结构体偏移 0x{got:X} != "
                        f"ref.json {ref_key} 偏移 0x{expect:X}")
        self.assertEqual(
            mismatches, [],
            "结构体布局与 ref.json 登记不一致 (F-213 口径: BKP 基址归一 +4, "
            "CAN 剥 CAN_ 前缀, 单侧成员不比):\n" + "\n".join(mismatches))

    def test_critical_offsets_are_pinned(self):
        """三处缺陷的定点钉——防止"归一后碰巧抵消"式假绿。

        这三项是 F-213 实锤修复过的, 且各自代表一种错法(漏保留间隙/错位+错组数
        /成员顺序错), 值得单独钉住绝对值。

        口径: 一律用**外设相对**(= 结构体自身的口径), 不复用 ref.json 的
        BKP origin 口径。两者差 0x04 (见 _STRUCT_MAP 的 +4 归一), 此处若混用
        会把正确实现判成错——本钉开发时即踩过一次。
        """
        pins = [
            ("NVIC_Type", "ICER", 0x80),
            ("NVIC_Type", "IP", 0x300),
            ("CAN_TypeDef", "F", 0x240),
            ("BKP_TypeDef", "RTCCR", 0x2C),
            ("BKP_TypeDef", "CR", 0x30),
            ("BKP_TypeDef", "CSR", 0x34),
        ]
        for struct, mem, expect in pins:
            # 独立于逐名比对集: 定点钉问的是编译器的绝对答案, 不依赖归一层
            actual = self._offsets_for(struct, [mem])
            self.assertEqual(actual.get(mem), expect,
                             f"{struct}.{mem} 绝对偏移应为 0x{expect:X}, "
                             f"实得 {actual.get(mem)}")

    def test_can_filter_bank_count_is_14(self):
        """CAN 滤波器组数必须是 14 (ref.json F0R1..F13R2 = 0x70 字节)。

        F-213 只修偏移不修组数的话, F[28][2] 会从 0x240 铺到 0x2FF,
        越过外设末端 0x70 字节——把静默错位换成越界踩踏。
        """
        gcc = _host_gcc()
        if not gcc:
            self.skipTest("未找到 host gcc")
        import tempfile
        src = (
            "#include <stdio.h>\n#include <stddef.h>\n"
            '#include "f103_regs.h"\n'
            "int main(void){\n"
            '    printf("sizeof_F=%zu\\n", sizeof(((CAN_TypeDef*)0)->F));\n'
            '    printf("off_F=%zu\\n", offsetof(CAN_TypeDef, F));\n'
            "    return 0;\n}\n")
        with tempfile.TemporaryDirectory() as td:
            cpath = os.path.join(td, "probe.c")
            exe = os.path.join(td, "probe.exe" if os.name == "nt" else "probe")
            with open(cpath, "w", encoding="utf-8") as f:
                f.write(src)
            r = subprocess.run(
                [gcc, "-pipe", "-I", HEADER_DIR, cpath, "-o", exe],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
            if r.returncode != 0:
                self.fail(f"CAN 滤波器探针编译失败\n{r.stderr[-1500:]}")
            run = subprocess.run([exe], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60)
        vals = dict(l.split("=", 1) for l in run.stdout.split() if "=" in l)
        self.assertEqual(int(vals["off_F"]), 0x240,
                         "CAN.F 起始偏移应为 0x240 (F0R1)")
        self.assertEqual(int(vals["sizeof_F"]), 14 * 2 * 4,
                         "CAN.F 应为 14 组 × 2 字 = 112 字节 (0x70)")


class CrossCompilerStaticAssertTests(unittest.TestCase):
    """CI 路径: 无 host gcc 时用 arm-none-eabi 编译期断言 (不 skip)。

    CI (.github/workflows/ci.yml:92,114) 只装 gcc-arm-none-eabi, 没有 host
    gcc, 也无法运行 ARM 二进制。故运行探针在那里不可用——若无此降级路径,
    本钉会在 CI 上静默 skip, 等于没有钉。本例不依赖"能否运行", 只依赖
    "能否编译", 故在 CI 上必然执行。
    """

    # F-213 三处缺陷的定点值 + 其余结构体的代表值, 一并编译期钉死
    PINS = [
        ("NVIC_Type", "ISER", 0x00), ("NVIC_Type", "ICER", 0x80),
        ("NVIC_Type", "ISPR", 0x100), ("NVIC_Type", "ICPR", 0x180),
        ("NVIC_Type", "IABR", 0x200), ("NVIC_Type", "IP", 0x300),
        ("CAN_TypeDef", "F", 0x240),
        ("BKP_TypeDef", "RTCCR", 0x2C), ("BKP_TypeDef", "CR", 0x30),
        ("BKP_TypeDef", "CSR", 0x34),
        ("RCC_TypeDef", "CR", 0x00), ("RCC_TypeDef", "BDCR", 0x20),
        ("FLASH_TypeDef", "ACR", 0x00), ("FLASH_TypeDef", "WRPR", 0x20),
        ("IWDG_TypeDef", "KR", 0x00), ("IWDG_TypeDef", "SR", 0x0C),
        ("RTC_TypeDef", "CRH", 0x00), ("RTC_TypeDef", "ALRL", 0x24),
        ("AFIO_TypeDef", "MAPR2", 0x1C),
        ("EXTI_TypeDef", "PR", 0x14),
        ("CRC_TypeDef", "CR", 0x08),
        ("WWDG_TypeDef", "SR", 0x08),
        ("SysTick_Type", "CTRL", 0x00), ("SysTick_Type", "CALIB", 0x0C),
    ]

    def test_critical_offsets_hold_under_cross_compiler(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = _static_assert_probe(self.PINS, td)
            if r is None:
                self.skipTest("既无 host gcc 也无 arm-none-eabi-gcc, "
                              "无法执行结构体偏移钉 (CI 装 gcc-arm-none-eabi, "
                              "本地两条路径任一可用即执行)")
            self.assertEqual(
                r.returncode, 0,
                "结构体偏移静态断言不成立 (F-213 回归):\n"
                + (r.stderr or "")[-3000:])


class RefJsonConventionDocTests(unittest.TestCase):
    """口径归一的元纪律: 归一表必须与 ref.json 实际形态对得上。

    若 ref.json 将来改了基址惯例或键名风格, 这些会红, 提醒同步更新归一层,
    而不是让假阳性淹没真阳性。
    """

    def test_bkp_base_convention_is_documented(self):
        periph = _load_ref()["peripherals"]["BKP"]
        self.assertEqual(int(periph["base"], 16), 0x40006C04)
        self.assertEqual(int(periph["registers"]["DR1"]["offset"], 16), 0x0)
        self.assertIn("note", periph,
                      "BKP 口径差异必须有 note 说明 (归一层据此 +4)")
        bkp_adj = [a for s, p, a in _STRUCT_MAP if p == "BKP"]
        self.assertEqual(bkp_adj, [4], "BKP 基址归一常数应恒为 +4")

    def test_can_key_prefix_is_mixed(self):
        """CAN 键名确实混用前缀——若上游统一了, 归一层可简化并更新本钉。"""
        regs = _load_ref()["peripherals"]["CAN"]["registers"]
        prefixed = [k for k in regs if k.startswith("CAN_")]
        unprefixed = [k for k in regs if not k.startswith("CAN_")]
        self.assertTrue(prefixed, "CAN 控制域应带 CAN_ 前缀")
        self.assertTrue(unprefixed, "CAN 滤波器域应不带前缀")


if __name__ == "__main__":
    unittest.main()