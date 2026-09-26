r"""F-195 (WB-20260927-03) 健壮面六件钉 — M-4/M-5/M-7/M-8/M-9 + F-194 P-2。

事实源 = WB-20260926-04 对账报告 §一 M-4/M-5/M-7/M-8/M-9 五节 +
WB-20260927-02 报告 §五 P-2。先钉后修: 六病各红 (修前), 撤销实验复现;
金比对反向钉 (正常输入逐字节不变) 常绿两侧, 修程若动 wire 形态即红。

零 mock (不入 test_stub_ratchet 判据面); T1 走真子进程 cp936 伪环境,
T5 全程 tempdir 副本 (data/** 零写), T6 本机 arm-gcc 在场实跑否则
skipUnless 显式跳过。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import evidence_export  # noqa: E402
import gen_periph  # noqa: E402
import junit_xml  # noqa: E402
import svd_to_json  # noqa: E402

TK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(TK_ROOT, "scripts")

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def _run_cp936(script_name, args, cwd=None):
    """cp936 伪环境子进程 (M-4 伪环境): 剥 PYTHONUTF8/PYTHONIOENCODING 后
    强制 PYTHONIOENCODING=cp936 + PYTHONUTF8=0 (-X utf8 关)。修前中文
    JSON 输出走 GBK 字节, 父端按 utf-8/replace 解码即 U+FFFD 实锤。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING",
                        "PYTHONLEGACYWINDOWSSTDIO")}
    env["PYTHONIOENCODING"] = "cp936"
    env["PYTHONUTF8"] = "0"
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script_name)] + list(args),
        capture_output=True, env=env, cwd=cwd or tempfile.mkdtemp(),
        timeout=120)


# ════════════════════════════ T1 (M-4) ════════════════════════════

class ForceUtf8HardfaultTests(unittest.TestCase):
    """--no-probe --json 路径: diagnosis 字段中文在 cp936 子进程下修前
    乱码 (U+FFFD 实锤), 修后 main 入口 force_utf8_streams 收编 → 干净。"""

    def test_diagnosis_survives_cp936_pipeline(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        hf = os.path.join(ws, "capture.txt")
        with open(hf, "w", encoding="utf-8") as f:
            # [HF] 模板契约: 8 位大写十六进制无 0x 前缀 (_HF_SITE_RE)
            f.write("[初始化] boot ok\n[HF] PC=08001234 LR=08005678\n")
        r = _run_cp936("hardfault.py",
                       ["--no-probe", "--json", "--fault-text", hf], cwd=ws)
        self.assertEqual(r.returncode, 0,
                         r.stdout.decode("utf-8", "replace")
                         + r.stderr.decode("utf-8", "replace"))
        text = r.stdout.decode("utf-8", "replace")
        self.assertNotIn("\ufffd", text, "cp936 子进程下 diagnosis 乱码实锤")
        result = json.loads(text)
        self.assertEqual(result["status"], "parsed_text_only")
        self.assertIn("故障点已定位", result["diagnosis"])


class ForceUtf8HandoffGuardTests(unittest.TestCase):
    """L3 警告路径: stdout JSON 携中文 note (主流程改动无 tests 伴随),
    cp936 子进程下修前乱码, 修后干净且 verdict 语义不变。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)

        def git(*a):
            subprocess.run(["git"] + GIT_ID + ["-C", self.repo] + list(a),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, check=True)
        git("init", "-q")
        vdir = os.path.join(self.repo, "scripts")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "verify.py"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("def run():\n    return 0\n")
        git("add", "-A")
        git("commit", "-qm", "base")
        git("branch", "-M", "master")
        git("checkout", "-qb", "handoff/t")
        with open(os.path.join(vdir, "verify.py"), "a",
                  encoding="utf-8", newline="\n") as f:
            f.write("# 触发 L3: 主流程改动且无 tests 伴随\n")
        git("add", "-A")
        git("commit", "-qm", "tweak verify no tests")

    def test_l3_warning_note_survives_cp936_pipeline(self):
        r = _run_cp936("handoff_guard.py",
                       ["--repo", self.repo, "--branch", "handoff/t",
                        "--base", "master", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        text = r.stdout.decode("utf-8", "replace")
        self.assertNotIn("\ufffd", text, "cp936 子进程下 warning note 乱码实锤")
        v = json.loads(text)
        self.assertEqual(v["verdict"], "clean")
        self.assertTrue(v["warnings"], "夹具必须真实触发 L3 中文 note")


class ForceUtf8ReleaseAuditTests(unittest.TestCase):
    """无 releases 目录路径: stdout JSON 携中文 error, cp936 子进程下
    修前乱码, 修后干净且 verdict 语义不变。"""

    def test_chinese_error_survives_cp936_pipeline(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        r = _run_cp936("release_audit.py",
                       ["--project", ws, "--tag", "v0", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        text = r.stdout.decode("utf-8", "replace")
        self.assertNotIn("\ufffd", text, "cp936 子进程下 error 乱码实锤")
        result = json.loads(text)
        self.assertIn("releases", result.get("error", ""))


# ════════════════════════════ T2 (M-5) ════════════════════════════

class JunitXmlSanitizeTests(unittest.TestCase):
    """XML 1.0 非法控制字符 (#x00-#x08 #x0B #x0C #x0E-#x1F) 净化:
    修前 message 直入 ET 属性 → 非法 XML 且信封 ok=True 假绿;
    修后 U+FFFD 替换, 输出恒可解析, 合法字符逐字节不动。"""

    def test_control_char_message_still_parseable(self):
        cases = [{"name": "T\x01bad", "classname": "verify",
                  "kind": "failure", "failure_type": "fail",
                  "message": "bad\x01ctl\x02tail"}]
        xml = junit_xml.render_xml(cases, None)
        root = ET.fromstring(xml)   # 修前: ParseError not well-formed
        self.assertNotIn("\x01", xml)
        self.assertIn("\ufffd", xml, "非法控制字符应替换为 U+FFFD")
        self.assertEqual(root.find("testcase").get("name"), "T\ufffdbad")

    def test_envelope_ok_implies_parseable_file(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        out = os.path.join(ws, "junit.xml")
        result = {"steps": {"verify": {"results": [
            {"id": "FR-DIRTY", "status": "fail", "detail": "脏\x07detail"}]}}}
        rs = junit_xml.write_junit_report(result, out)
        self.assertTrue(rs["ok"], rs)
        root = ET.parse(out).getroot()   # 修前: ParseError → ok=True 假绿实锤
        self.assertEqual(root.get("failures"), "1")

    def test_legal_chars_byte_identical(self):
        # 反向钉 (金比对): \t \n 中文 <&> 引号合法, 修前修后逐字节同。
        cases = [{"name": "FR-MSG-01", "classname": "expectations",
                  "kind": "failure", "failure_type": "fail",
                  "message": "行一\t制表\n行二 换行 中文 <&> 引号\"x\" 保留"}]
        self.assertEqual(
            junit_xml.render_xml(cases, None),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<testsuite name="embedded-toolkit verify" tests="1" failures="1"'
            ' errors="0" skipped="0"><testcase name="FR-MSG-01"'
            ' classname="expectations"><failure type="fail" message="行一&#09;'
            '制表&#10;行二 换行 中文 &lt;&amp;&gt; 引号&quot;x&quot; 保留"'
            ' /></testcase></testsuite>')


# ════════════════════════════ T3 (M-7) ════════════════════════════

class EvidenceExportTypeGuardTests(unittest.TestCase):
    """类型守卫: 改坏记录 (results 为真值字符串等) 修前抛未捕获
    AttributeError (CI if:always() 假红), 修后 fail-soft 留痕不崩;
    正常记录渲染逐字节不变 (金比对反向钉)。"""

    def test_release_summary_bad_results_type_no_attributeerror(self):
        md = evidence_export.render_release_summary(
            {"tag": "v1", "results": "abc"})   # 修前: AttributeError
        self.assertIsInstance(md, str)
        self.assertIn("results", md, "坏输入要留痕")
        self.assertIn("str", md)

    def test_verify_summary_bad_types_no_crash(self):
        md = evidence_export.render_verify_summary({
            "status": "ok",
            "steps": {"verify": {"results": "abc"}},   # 修前: AttributeError
            "records": "xyz",
            "captured_output": 123,
        })
        self.assertIsInstance(md, str)
        for label in ("results", "records", "captured_output"):
            self.assertIn(label, md, f"坏字段 {label} 要留痕")

    def test_main_end_to_end_no_traceback(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, ignore_errors=True)
        bad = os.path.join(ws, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"tag": "v1", "results": "abc"}, f)
        out = os.path.join(ws, "summary.md")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "evidence_export.py"),
             "--release-record", bad, "--out", out],
            capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertNotIn(b"Traceback", r.stderr, "CI if:always() 步骤不崩红")
        with open(out, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("results", body, "坏输入记录进摘要留痕")

    def test_normal_records_byte_identical(self):
        # 反向钉 (金比对): 正常记录修前修后逐字节同 (两渲染面)。
        verify_result = {
            "status": "ok", "evidence": "simulation_validated",
            "elapsed_sec": 1.2,
            "steps": {"verify": {"results": [
                {"id": "FR-SYS-01", "status": "pass"},
                {"id": "FR-ADC-01", "status": "fail",
                 "detail": "mv=319 < min 3000"}]}},
            "records": [{"id": "FR-ADC-01", "mv": "3192"}],
            "captured_output": "boot on <path>",
        }
        self.assertEqual(
            evidence_export.render_verify_summary(verify_result),
            "## embedded-toolkit verify 报告\n\n- **判定**: ✅ OK\n"
            "- **证据等级**: `simulation_validated`（仿真/静态证据不进发布门禁）\n"
            "- **实测耗时**: 1.2s\n\n| 期望 | 判定 | 说明 |\n|---|---|---|\n"
            "| FR-SYS-01 | ✅ PASS |  |\n| FR-ADC-01 | ❌ FAIL | mv=319 < min 3000 |\n"
            "\n- **record 提取**: `mv=3192`\n\n"
            "<details><summary>采集输出（前 500 字符）</summary>\n\n```text\n"
            "boot on <path>\n```\n\n</details>\n")
        release_record = {
            "tag": "v1.1.0", "git_head": "0123456789abcdef",
            "branch": "master", "evidence": "production_approved",
            "production_approved_at": "2026-09-12T12:00:00+08:00",
            "xfail_waived": ["FR-B"],
            "fidelity_boundaries": ["真机 capture 输出匹配判定"],
            "limitations": ["单板单次采样"],
            "results": [{"id": "FR-A", "status": "pass"},
                        {"id": "FR-B", "status": "xfail"}],
            "signature": "",
        }
        self.assertEqual(
            evidence_export.render_release_summary(release_record),
            "## 发布 v1.1.0\n\n- **git_head**: `0123456789ab` @ `master`\n"
            "- **证据等级**: `production_approved`\n"
            "- **批准投产**: 2026-09-12T12:00:00+08:00\n"
            "- **xfail 豁免**: FR-B\n\n**Fidelity 边界**:\n"
            "- 真机 capture 输出匹配判定\n\n**已知局限**:\n- 单板单次采样\n\n"
            "| 期望 | 判定 |\n|---|---|\n| FR-A | ✅ PASS |\n"
            "| FR-B | ⏭ XFAIL (欠条) |\n\n"
            "_signature: 留空（签名机制登记未实现）_\n")


# ════════════════════════════ T4 (M-8) ════════════════════════════

_SVD_HEAD = ("<?xml version='1.0'?>\n<device>\n  <peripherals>\n"
             "    <peripheral>\n      <name>USART1</name>\n"
             "      <baseAddress>0x40013800</baseAddress>\n      <registers>\n"
             "        <register>\n          <name>SR</name>\n"
             "          <addressOffset>0x00</addressOffset>\n"
             "          <fields><field><name>TXE</name>"
             "<bitRange>[7:7]</bitRange></field></fields>\n"
             "        </register>\n"
             "        <register><name>DR</name>"
             "<addressOffset>0x04</addressOffset></register>\n"
             "      </registers>\n    </peripheral>\n")


def _write_svd(derived_attr):
    ws = tempfile.mkdtemp()
    tail = (f"    <peripheral{derived_attr}>\n      <name>USART2</name>\n"
            "      <baseAddress>0x40004400</baseAddress>\n"
            "    </peripheral>\n  </peripherals>\n</device>\n")
    path = os.path.join(ws, "mini.svd")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_SVD_HEAD + tail)
    return path


class SvdDerivedFromStreamingTests(unittest.TestCase):
    """--periph 流式路径补 derivedFrom: 修前 USART2 空表与 --all 劈叉
    零告警, 修后与 extract_all 同源解析; 无 derivedFrom 路径不变;
    基外设缺席响亮告警。"""

    def test_single_resolves_derived_from(self):
        path = _write_svd(' derivedFrom="USART1"')
        self.addCleanup(shutil.rmtree, os.path.dirname(path),
                        ignore_errors=True)
        name, data = svd_to_json.extract_single(path, "USART2")
        self.assertEqual(name, "USART2")
        self.assertTrue(data["registers"], "修前空表实锤 (与 --all 劈叉)")
        root = ET.parse(path).getroot()
        all_data = svd_to_json.extract_all(root.find("peripherals"))
        self.assertEqual(data["registers"],
                         all_data["USART2"]["registers"])

    def test_unresolvable_derived_from_warns_loudly(self):
        path = _write_svd(' derivedFrom="USART9"')
        self.addCleanup(shutil.rmtree, os.path.dirname(path),
                        ignore_errors=True)
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            name, data = svd_to_json.extract_single(path, "USART2")
        self.assertIn("USART9", err.getvalue(),
                      "基外设缺席必须响亮告警, 不得静默空表")
        self.assertEqual(data["registers"], {})

    def test_no_derivedfrom_path_byte_identical(self):
        # 反向钉: 无 derivedFrom 路径修前修后同 (与 --all 互证)。
        path = _write_svd("")
        self.addCleanup(shutil.rmtree, os.path.dirname(path),
                        ignore_errors=True)
        name, data = svd_to_json.extract_single(path, "USART1")
        root = ET.parse(path).getroot()
        all_data = svd_to_json.extract_all(root.find("peripherals"))
        self.assertEqual(name, "USART1")
        self.assertEqual(data, all_data["USART1"])
        self.assertEqual(sorted(data["registers"]), ["DR", "SR"])


# ════════════════════════════ T5 (M-9) ════════════════════════════

def _ref_fixture(path, with_meta=True):
    ref = {"peripherals": {"GPIOA": {
        "base": "0x40010800", "registers": {"CR": {"offset": "0x00"}}}}}
    if with_meta:
        ref = {"_meta": {"version": "2.0.0", "chip": "T",
                         "peripheral_count": 1}, **ref}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
    return ref


_MERGE_DATA = {"USART1": {"base": "0x40013800", "bus": "APB2",
                          "desc": "usart",
                          "registers": {"SR": {"offset": "0x00"}}}}

# 旧路径 (截断式 open('w') + json.dump) 产出, newline 归一后逐字节金样。
# 旧 open('w') 在 Windows 附带 \n→CRLF 翻译 (与盘上 ref.json 的 LF 形态
# 相悖的偶然产物); 原子写强制 LF — 金口径 = 归一后逐字节同, 原子形态另钉。
_T5_MERGE_GOLDEN_LF = (
    '{\n  "_meta": {\n    "version": "2.0.0",\n    "chip": "T",\n'
    '    "peripheral_count": 2\n  },\n  "peripherals": {\n'
    '    "GPIOA": {\n      "base": "0x40010800",\n      "registers": {\n'
    '        "CR": {\n          "offset": "0x00"\n        }\n      }\n'
    '    },\n    "USART1": {\n      "base": "0x40013800",\n'
    '      "bus": "APB2",\n      "desc": "usart",\n'
    '      "registers": {\n        "SR": {\n          "offset": "0x00"\n'
    '        }\n      },\n      "available_on_c8": true\n    }\n  }\n}')


class SvdMergeAtomicWriteTests(unittest.TestCase):
    """merge_into_ref 原子写 (tempdir 副本验证, data/** 零写):
    dump 中途失败原文件逐字节完好 (修前截断损坏); 正常输出与旧形态
    newline 归一后逐字节同; _meta 缺键显式报错不裸 KeyError。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.ref_path = os.path.join(self.ws, "ref.json")

    def test_failed_dump_leaves_ref_intact(self):
        _ref_fixture(self.ref_path)
        snapshot = open(self.ref_path, "rb").read()
        bad = {"USART9": {"base": "0x0", "bus": "APB1",
                          "registers": {"R": {"offset": {1, 2}}}}}  # set 不可序列化
        with self.assertRaises(TypeError):
            svd_to_json.merge_into_ref(bad, self.ref_path)
        with open(self.ref_path, "rb") as f:
            current = f.read()
        self.assertEqual(current, snapshot,
                         "dump 中途失败不得损坏原 ref (修前截断实锤)")

    def test_normal_merge_bytes_match_old_form(self):
        # 反向钉 (金比对): 正常 merge 与旧形态 newline 归一后逐字节同。
        _ref_fixture(self.ref_path)
        added, total = svd_to_json.merge_into_ref(_MERGE_DATA, self.ref_path)
        self.assertEqual((added, total), (1, 2))   # 库态签名不变
        with open(self.ref_path, "rb") as f:
            raw = f.read()
        self.assertEqual(raw.replace(b"\r\n", b"\n").decode("utf-8"),
                         _T5_MERGE_GOLDEN_LF)

    def test_atomic_form_lf_only_no_tmp_leftover(self):
        # 原子形态: 成功路径 LF-only (修前 Windows CRLF 偶然翻译, 红) +
        # 无 .tmp 残留。断言 CRLF 面在 POSIX 修前本就 LF (不红), 跨平台
        # 红由 test_failed_dump_leaves_ref_intact 承担。
        _ref_fixture(self.ref_path)
        svd_to_json.merge_into_ref(_MERGE_DATA, self.ref_path)
        with open(self.ref_path, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r\n", raw, "原子写强制 LF (wb_common F-022 口径)")
        json.loads(raw.decode("utf-8"))
        self.assertEqual([n for n in os.listdir(self.ws) if ".tmp" in n], [],
                         "成功路径不得残留 .tmp")

    def test_meta_missing_explicit_error_not_bare_keyerror(self):
        _ref_fixture(self.ref_path, with_meta=False)
        with self.assertRaises(ValueError,
                               msg="_meta 缺键应显式 ValueError 而非裸 KeyError"):
            svd_to_json.merge_into_ref(_MERGE_DATA, self.ref_path)
        # 报错路径同样不得损坏原文件
        with open(self.ref_path, "rb") as f:
            self.assertIn(b"GPIOA", f.read())

# ════════════════════════════ T6 (F-194 P-2) ════════════════════════════

GCC_TIMEOUT = 30

# 最小 stub: 无 #include <stdint.h> (F-078 smoke stub 预置 stdint 恰好
# 掩盖自足缺口 — 本钉剥掉预置, 自足性缺口直接编译红)。
_MINI_STUB = r"""#pragma once
#define __DSB() ((void)0)
typedef struct { volatile unsigned int CR, CFGR, CIR, APB2RSTR, APB1RSTR,
    AHBENR, APB2ENR, APB1ENR, BDCR, CSR; } RCC_TypeDef;
typedef struct { volatile unsigned int CRL, CRH, IDR, ODR, BSRR, BRR, LCKR;
} GPIO_TypeDef;
typedef struct { volatile unsigned int SR, DR, BRR, CR1, CR2, CR3, GTPR;
} USART_TypeDef;
typedef struct { volatile unsigned int CR1, CR2, SR, DR, CRCPR, RXCRCR,
    TXCRCR, I2SCFGR; } SPI_TypeDef;
#define RCC     ((RCC_TypeDef *)  0x40021000UL)
#define GPIOA   ((GPIO_TypeDef *) 0x40010800UL)
#define GPIOB   ((GPIO_TypeDef *) 0x40010C00UL)
#define USART1  ((USART_TypeDef *) 0x40013800UL)
#define USART2  ((USART_TypeDef *) 0x40004400UL)
#define SPI1    ((SPI_TypeDef *)   0x40013000UL)
#define SPI2    ((SPI_TypeDef *)   0x40003800UL)
#define RCC_APB2ENR_IOPAEN   (1UL << 2)
#define RCC_APB2ENR_IOPBEN   (1UL << 3)
#define RCC_APB2ENR_SPI1EN   (1UL << 12)
#define RCC_APB2ENR_USART1EN (1UL << 14)
#define RCC_APB1ENR_SPI2EN   (1UL << 14)
#define RCC_APB1ENR_USART2EN (1UL << 17)
#define USART_CR1_TE (1UL << 3)
#define USART_CR1_RE (1UL << 2)
#define USART_CR1_UE (1UL << 13)
"""


def _find_arm_gcc():
    exe = None
    try:
        import wb_common
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


@unittest.skipUnless(_MINI_GCC, "arm-none-eabi-gcc 不在场 (machine.json)")
class GenStdintSelfEmitTests(unittest.TestCase):
    """gen_usart/gen_spi 帮手 uint8_t 自足 (F-194 P-2 同族补面):
    无 stdint 预置的最小 stub 下过 gcc -fsyntax-only (修前裸 uint 编译红);
    include 发射先于首个引用; 其它型输出金夹具逐字节不随动。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.stub = os.path.join(cls.tmp, "mini_stub.h")
        with open(cls.stub, "w", encoding="ascii") as f:
            f.write(_MINI_STUB)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _syntax_check(self, name, code):
        # 机械变换与 F-078 smoke 同口径: 剥行首 static 后包进函数
        # (GNU C 嵌套函数; #include 在函数体内即原地展开, typedef 函数
        # 作用域合法)。
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

    def test_usart_spi_compile_without_preset_stdint(self):
        snippets = [
            ("usart1", lambda: gen_periph.gen_usart("USART1", 115200,
                                                   "PA9", "PA10")),
            ("usart2", lambda: gen_periph.gen_usart("USART2", 9600,
                                                   "PA2", "PA3")),
            ("spi1", lambda: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5",
                                                "PA6", "PA7", 16)),
            ("spi2", lambda: gen_periph.gen_spi("SPI2", 3, "PB12", "PB13",
                                                "PB14", "PB15", 256)),
        ]
        for name, gen in snippets:
            with self.subTest(case=name):
                self._syntax_check(name, gen())

    def test_include_precedes_first_uint_use_exactly_once(self):
        # 平台无关红面 (无 gcc 也咬): 修前 include 缺席 → 红。
        for name, gen in (
                ("usart", lambda: gen_periph.gen_usart("USART1", 115200,
                                                       "PA9", "PA10")),
                ("spi", lambda: gen_periph.gen_spi("SPI1", 0, "PA4", "PA5",
                                                   "PA6", "PA7", 16))):
            with self.subTest(case=name):
                out = gen()
                self.assertEqual(out.count("#include <stdint.h>"), 1,
                                 "恰好自发射一次 (若已含则不重复)")
                self.assertLess(out.index("#include <stdint.h>"),
                                out.index("uint8_t"),
                                "include 必须先于首个 uint 引用")

    def test_other_generators_byte_identical(self):
        # 反向钉 (金比对): 其它型输出与修前金夹具逐字节同 (其它型不随动)。
        fixture = os.path.join(TK_ROOT, "tests", "fixtures",
                               "gen_periph_golden_f195.json")
        with open(fixture, encoding="utf-8") as f:
            golden = json.load(f)
        current = {
            "t6_gpio_pp50": gen_periph.gen_gpio("PC13", "out-pp-50mhz"),
            "t6_pwm_tim2_ch1": gen_periph.gen_pwm("TIM2", 1, "PA0", 1000, 50),
            "t6_adc_ch1": gen_periph.gen_adc("ADC1", 1, "PA1"),
            "t6_timerint_tim2": gen_periph.gen_timer_int("TIM2", 1, 72),
            "t6_i2c1_std": gen_periph.gen_i2c("I2C1", 100000, "PB6", "PB7"),
            "t6_systick_1k": gen_periph.gen_systick(1000),
        }
        for key, value in current.items():
            with self.subTest(case=key):
                self.assertEqual(value, golden[key])


if __name__ == "__main__":
    unittest.main()
