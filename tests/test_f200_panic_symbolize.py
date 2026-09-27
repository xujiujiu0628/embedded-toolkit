r"""ESP panic 符号化面钉 (F-200, WB-20260927-08 — 验收口径草案 A1~A6 兑现)。

spec §4.3 "panic 只做文本级标记, 符号化解析后置另票" 的后置票。红线: 只加
信息不改判据 — panic fail-closed 与 AI judge 定性零动, 既有三枚钉
(test_esp_runtime.py:243/265 + test_verify_esp_dispatch.py:86) 零扰动即
此条的机检形态 (全量回归覆盖, 本文件不重复)。

本钉六面 (口径 §3 逐条):

  A1 解析   parse_backtrace: Backtrace: 行 → (pc, sp) 帧对, 帧分隔容忍
            空格与旧版 |<-CORRUPTED; abort() 无 backtrace → 空列表不报错;
            ELF file SHA… 行一并提取 (拍板③); 多 Backtrace 行按序拼接。
  A2 elf    嵌套键 last_build.artifacts.elf_file 消费 (与 release.py:212
            同口径, 嵌套-only); 缺 state/缺键/空串/档不存在 → fail-soft
            {"available": false, "reason": "<tag>: <点名>"}, 原文保留,
            绝不抛穿。
  A3 工具   esp_tools_dir 下 glob tools/xtensa-esp-elf/*/…/addr2line.exe;
            多版本目录取版本段字典序最大 (确定性规则); glob 空/目录缺 →
            fail-soft 点名。白名单 executable 直调, 无 shell=True。
  A4 符号化 一次批量调 addr2line -f -i -a -p -e <elf> <pc…>; 块序 zip
            (实测 2.43.1 地址回显小写归一, 禁回显匹配); 单帧 ?? →
            {"pc","unresolved": true} 不断链; 无 DWARF (func at ??:?)
            → 保留函数名 file/line 为 null; (inlined by) 链拆多帧同 pc
            回显; (discriminator N) 后缀剥离; 块数不齐 → 余帧补 unresolved。
  A5 上账   ledger/result 增 esp_panic_symbolized (frames + elf_path/tool
            两字段 + elf_sha256* 三字段); available → stdout 解码框
            (帧号/函数/文件:行/未解计数), fail-soft → stderr 一行注记;
            SHA 前缀比对漂移 → 框内"[参考级]"警告, status/judge/expect
            判据链零动。
  A6 卫生   新代码零全局打桩: addr2line 路径纯函数注入参数; 库面测试用
            假 addr2line (.bat 壳 → python fixture 吐预置映射) 走真
            subprocess; 真 ROM elf 探针 (skipUnless 装配) 钉真工具实格式。
            唯一例外: verify 接线面沿 test_verify_esp_dispatch.py 先例
            patch 仓内共享层 seam (esp_runtime.step_capture_uart /
            symbolize_esp_panic — 棘轮 P 面不计), 符号化链本体零 patch。

fail-soft 理由码 (tag: detail 形态, detail 点名具体缺失):
  no_frames / elf_missing_key / elf_not_found / no_tools_dir /
  addr2line_not_found / tool_error
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import esp_runtime  # noqa: E402
import verify  # noqa: E402
from wb_common import load_machine  # noqa: E402

_SYMBOLIZE_API = ("parse_backtrace", "locate_addr2line", "symbolize_frames",
                  "symbolize_esp_panic", "format_symbol_box")

# ── 捕获文本三形态 (口径 §4 fixture; 文本按 IDF 公开格式构造, 真机终判归 B) ──
TEXT_CLASSIC = (
    "rst:0x1 (POWERON_RESET)\n"
    "Guru Meditation Error: Core 0 panic'ed (StoreProhibited). "
    "Exception was unhandled.\n"
    "Backtrace: 0x40092f3c:0x3ffb2ea0 0x40092f99:0x3ffb2ec0 "
    "0x40092f99:0x3ffb2ee0\n"
)
TEXT_S3 = (
    "abort() was called at PC 0x403765d3 on core 0\n"
    "Backtrace: 0x403765d3:0x3fce9b30 0x40376b95:0x3fce9b50 |<-CORRUPTED\n"
    "ELF file SHA256: 3c9d3e1f2b4a5c6d7e8f9012a3b4c5d6"
    "e7f8091a2b3c4d5e6f708192a3b4c5d6\n"
)
SHA_S3 = TEXT_S3.rsplit("ELF file SHA256: ", 1)[1].split("\n", 1)[0]

_FAKE_SCRIPT = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["F200_LOG"], "a", encoding="utf-8") as f:
    f.write("CALL " + " ".join(args) + "\n")
try:
    i = args.index("-e")
    pcs = args[i + 2:]
except ValueError:
    pcs = []
mapping = json.loads(os.environ.get("F200_MAP", "{}"))
for pc in pcs:
    body = mapping.get(pc)
    if body is not None:
        sys.stdout.write("%s: %s\r\n" % (pc, body))
'''

_FAKE_SCRIPT_RC1 = "import sys\nsys.exit(1)\n"


class SymbolizeLandedMixin:
    """未实现态 = 全红 (先红实录); T1 实现 commit 转绿。"""

    def setUp(self):
        missing = [n for n in _SYMBOLIZE_API if not hasattr(esp_runtime, n)]
        if missing:
            self.fail("esp_runtime panic 符号化面未实现 (缺 "
                      + ", ".join(missing) + "; F-200 T1 实现 commit 转绿)")


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _mk_fake_addr2line(td, script_body=_FAKE_SCRIPT):
    """假 addr2line: .bat 壳 → python fixture 吐预置映射 (真 subprocess)。"""
    script = os.path.join(td, "f200_fake_addr2line.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(script_body)
    bat = os.path.join(td, "xtensa-esp-elf-addr2line.bat")
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write('@echo off\n"%s" "%s" %%*\n' % (sys.executable, script))
    return bat


def _setenv(mapping, log_path=None):
    """os.environ 注入 (零 patch 路线), addCleanup 恢复。"""
    saved = {k: os.environ.get(k) for k in mapping}
    if log_path is not None:
        saved["F200_LOG"] = os.environ.get("F200_LOG")
        mapping = dict(mapping, F200_LOG=log_path)
    os.environ.update(mapping)

    def _restore():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return _restore


def _mk_ws(td, elf_rel="build/app.elf", write_elf=True, nested=True,
           flat=True, elf_bytes=b"f200-fake-elf-content"):
    """工作区 + .workbench/state.json (嵌套/平铺双形态可选) + elf 档。"""
    ws = os.path.join(td, "ws")
    os.makedirs(os.path.join(ws, ".workbench"), exist_ok=True)
    if write_elf:
        os.makedirs(os.path.join(ws, os.path.dirname(elf_rel)),
                    exist_ok=True)
        with open(os.path.join(ws, elf_rel.replace("/", os.sep)), "wb") as f:
            f.write(elf_bytes)
    entry = {}
    if nested:
        entry["artifacts"] = {"hex_file": "build/app.bin",
                              "bin_file": "build/app.bin",
                              "elf_file": elf_rel}
    if flat:
        entry.update({"hex_file": "build/app.bin", "elf_file": elf_rel})
    with open(os.path.join(ws, ".workbench", "state.json"), "w",
              encoding="utf-8") as f:
        json.dump({"last_build": entry}, f)
    return ws


def _s3_text_with_sha(ws, sha=None):
    """S3 形态文本, ELF SHA 行换成本地 elf 实算 sha (默认)。"""
    if sha is None:
        sha = _sha256_of(os.path.join(ws, "build", "app.elf"))
    return TEXT_S3.replace(SHA_S3, sha)


class ParseBacktraceTests(SymbolizeLandedMixin, unittest.TestCase):
    """A1: Backtrace: 行 → 帧对 + ELF SHA 提取。"""

    def test_classic_form_pairs_in_order(self):
        r = esp_runtime.parse_backtrace(TEXT_CLASSIC)
        self.assertEqual(
            r["frames"],
            [("0x40092f3c", "0x3ffb2ea0"), ("0x40092f99", "0x3ffb2ec0"),
             ("0x40092f99", "0x3ffb2ee0")])
        self.assertIsNone(r["elf_sha"])

    def test_old_form_no_space_and_pipe_separators(self):
        text = ("Backtrace:0x40000544:0x3ffae110 |- 0x4000c2a0:0x3ffae130 "
                "|<-CORRUPTED")
        r = esp_runtime.parse_backtrace(text)
        self.assertEqual(r["frames"],
                         [("0x40000544", "0x3ffae110"),
                          ("0x4000c2a0", "0x3ffae130")])

    def test_abort_without_backtrace_is_empty_not_error(self):
        r = esp_runtime.parse_backtrace("abort() was called at PC 0x403765d3")
        self.assertEqual(r["frames"], [])
        self.assertIsNone(r["elf_sha"])

    def test_elf_sha_line_extracted(self):
        r = esp_runtime.parse_backtrace(TEXT_S3)
        self.assertEqual(len(r["frames"]), 2)   # |<-CORRUPTED 尾巴不进帧
        self.assertEqual(r["elf_sha"], SHA_S3)

    def test_multi_backtrace_lines_concat_in_order(self):
        text = ("Backtrace: 0x40000001:0x3ff00001\n"
                "Backtrace: 0x40000002:0x3ff00002 0x40000003:0x3ff00003\n")
        r = esp_runtime.parse_backtrace(text)
        self.assertEqual(
            r["frames"],
            [("0x40000001", "0x3ff00001"), ("0x40000002", "0x3ff00002"),
             ("0x40000003", "0x3ff00003")])

    def test_plain_text_no_backtrace(self):
        r = esp_runtime.parse_backtrace("ESP-PILOT-OK tick=0 heap=123\n")
        self.assertEqual(r["frames"], [])
        self.assertIsNone(r["elf_sha"])


class LocateAddr2lineTests(SymbolizeLandedMixin, unittest.TestCase):
    """A3: glob 定位 + 版本段字典序最大 + fail-soft 点名。"""

    def _mk_tools(self, td, versions):
        tools = os.path.join(td, "tools-root")
        for ver in versions:
            bindir = os.path.join(tools, "tools", "xtensa-esp-elf", ver,
                                  "xtensa-esp-elf", "bin")
            os.makedirs(bindir, exist_ok=True)
            with open(os.path.join(bindir,
                                   "xtensa-esp-elf-addr2line.exe"), "wb") as f:
                f.write(b"marker")
        return tools

    def test_single_version_found(self):
        with tempfile.TemporaryDirectory() as td:
            tools = self._mk_tools(td, ["esp-14.2.0_20260121"])
            exe, why = esp_runtime.locate_addr2line(tools)
            self.assertIsNone(why)
            self.assertTrue(exe.endswith("xtensa-esp-elf-addr2line.exe"))
            self.assertIn("esp-14.2.0_20260121", exe)

    def test_multiple_versions_take_lexicographic_max_segment(self):
        with tempfile.TemporaryDirectory() as td:
            tools = self._mk_tools(td, ["esp-14.2.0_20241026",
                                        "esp-14.2.0_20260121"])
            exe, why = esp_runtime.locate_addr2line(tools)
            self.assertIsNone(why)
            self.assertIn("esp-14.2.0_20260121", exe)   # 字典序最大 (日期段)

    def test_glob_empty_named_reason(self):
        with tempfile.TemporaryDirectory() as td:
            tools = self._mk_tools(td, [])
            exe, why = esp_runtime.locate_addr2line(tools)
            self.assertIsNone(exe)
            self.assertTrue(why.startswith("addr2line_not_found"), why)

    def test_missing_tools_dir_named_reason(self):
        for bad in ("", r"Z:\definitely\not\here"):
            exe, why = esp_runtime.locate_addr2line(bad)
            self.assertIsNone(exe)
            self.assertTrue(why.startswith("no_tools_dir"), why)


class SymbolizeFramesTests(SymbolizeLandedMixin, unittest.TestCase):
    """A4: 一次批量调用 + 块序 zip + 逐帧映射与降级 (假工具真 subprocess)。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.bat = _mk_fake_addr2line(self._td.name)
        self.log = os.path.join(self._td.name, "f200_calls.log")

    def _map(self, mapping):
        self.addCleanup(_setenv({"F200_MAP": json.dumps(mapping)}, self.log))

    def _calls(self):
        with open(self.log, encoding="utf-8") as f:
            return f.read().splitlines()

    def test_golden_mapping_batch_call_and_order(self):
        self._map({"0x40092f3c": "app_main at main/main.c:42",
                   "0x40092f99": "panic_abort at components/esp_system/panic.c:118"})
        frames, why = esp_runtime.symbolize_frames(
            ["0x40092f3c", "0x40092f99"], r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x40092f3c", "function": "app_main",
             "file": "main/main.c", "line": 42},
            {"pc": "0x40092f99", "function": "panic_abort",
             "file": "components/esp_system/panic.c", "line": 118}])
        calls = [c for c in self._calls() if c.startswith("CALL ")]
        self.assertEqual(len(calls), 1)             # 一次批量, 逐帧不逐调
        argv = calls[0].split(" ")[1:]
        for flag in ("-f", "-i", "-a", "-p"):
            self.assertIn(flag, argv)
        e = argv.index("-e")
        self.assertEqual(argv[e + 1], r"W:\ws\build\app.elf")
        self.assertEqual(argv[e + 2:], ["0x40092f3c", "0x40092f99"])

    def test_inline_chain_splits_frames_same_pc_echo(self):
        self._map({"0x403765d3":
                   "inner_step at main/tasks.c:5 (inlined by) "
                   "outer_step at main/tasks.c:9"})
        frames, why = esp_runtime.symbolize_frames(
            ["0x403765d3"], r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x403765d3", "function": "inner_step",
             "file": "main/tasks.c", "line": 5},
            {"pc": "0x403765d3", "function": "outer_step",
             "file": "main/tasks.c", "line": 9}])

    def test_all_unresolved_downgrade_keeps_chain(self):
        self._map({"0x403765d3": "?? ??:0", "0x40376b95": "?? ??:0"})
        frames, why = esp_runtime.symbolize_frames(
            ["0x403765d3", "0x40376b95"], r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x403765d3", "unresolved": True},
            {"pc": "0x40376b95", "unresolved": True}])

    def test_no_dwarf_keeps_function_without_location(self):
        self._map({"0x40027d50": "lc_lmp_rx_ind_handler at ??:?"})
        frames, why = esp_runtime.symbolize_frames(
            ["0x40027d50"], r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x40027d50", "function": "lc_lmp_rx_ind_handler",
             "file": None, "line": None}])

    def test_discriminator_suffix_stripped(self):
        self._map({"0x40092f3c":
                   "app_main at main/main.c:42 (discriminator 4)"})
        frames, why = esp_runtime.symbolize_frames(
            ["0x40092f3c"], r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x40092f3c", "function": "app_main",
             "file": "main/main.c", "line": 42}])

    def test_tool_rc_nonzero_is_tool_error(self):
        bat = _mk_fake_addr2line(self._td.name, _FAKE_SCRIPT_RC1)
        frames, why = esp_runtime.symbolize_frames(
            ["0x40092f3c"], r"W:\ws\build\app.elf", bat)
        self.assertIsNone(frames)
        self.assertTrue(why.startswith("tool_error"), why)

    def test_block_count_mismatch_pads_unresolved(self):
        self._map({"0x40092f3c": "app_main at main/main.c:42"})  # 只回 1 块
        frames, why = esp_runtime.symbolize_frames(
            ["0x40092f3c", "0x40092f99", "0x40092f99"],
            r"W:\ws\build\app.elf", self.bat)
        self.assertIsNone(why)
        self.assertEqual(frames, [
            {"pc": "0x40092f3c", "function": "app_main",
             "file": "main/main.c", "line": 42},
            {"pc": "0x40092f99", "unresolved": True},
            {"pc": "0x40092f99", "unresolved": True}])

    def test_real_rom_elf_resolves_function_no_dwarf(self):
        """真工具真 elf 探针 (skipUnless 装配): 2.43.1 实格式回写钉。"""
        tools = (load_machine() or {}).get("esp_tools_dir", "")
        exe, why = esp_runtime.locate_addr2line(tools)
        rom = os.path.join(tools, "tools", "esp-rom-elfs", "20241011",
                           "esp32_rev0_rom.elf")
        nm = os.path.join(os.path.dirname(exe or ""), "xtensa-esp-elf-nm.exe")
        if not (exe and os.path.isfile(rom) and os.path.isfile(nm)):
            self.skipTest("esp 工具/ROM elf 未装配 (%s)" % (why or rom))
        with subprocess.Popen([nm, rom], stdout=subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace") as p:
            syms = [ln.split(" ", 2) for ln in (p.communicate()[0] or "")
                    .splitlines()]
        picks = [(int(a, 16), n) for a, t, n in syms
                 if t == "T" and int(a, 16) >= 0x40000000 and n.isidentifier()]
        self.assertTrue(picks)
        addr, name = sorted(picks)[len(picks) // 2]
        frames, why = esp_runtime.symbolize_frames(
            ["0x%08x" % addr, "0x50000000"], rom, exe)
        self.assertIsNone(why)
        self.assertEqual(frames[0]["pc"], "0x%08x" % addr)
        self.assertEqual(frames[0]["function"], name)   # 符号表在, DWARF 无
        self.assertIsNone(frames[0]["file"])
        self.assertIsNone(frames[0]["line"])
        self.assertNotIn("unresolved", frames[0])
        self.assertEqual(frames[1], {"pc": "0x50000000",
                                     "unresolved": True})


class SymbolizeEspPanicTests(SymbolizeLandedMixin, unittest.TestCase):
    """A2+A3+A5 编排: fail-soft 六类 + SHA 前缀比对 + 字段保留。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.bat = _mk_fake_addr2line(self._td.name)

    def test_full_success_gold(self):
        ws = _mk_ws(self._td.name)
        self.addCleanup(_setenv({
            "F200_MAP": json.dumps({
                "0x403765d3": "panic_abort at panic.c:118",
                "0x40376b95": "esp_restart_noos at panic.c:55"}),
            "F200_LOG": os.path.join(self._td.name, "calls.log")}))
        sym = esp_runtime.symbolize_esp_panic(
            _s3_text_with_sha(ws), ws, addr2line_exe=self.bat)
        self.assertTrue(sym["available"])
        self.assertEqual(sym["tool"], "xtensa-esp-elf-addr2line.bat")
        self.assertTrue(os.path.isabs(sym["elf_path"]))
        self.assertEqual(sym["elf_path"],
                         os.path.join(ws, "build", "app.elf"))
        self.assertEqual(sym["frames"], [
            {"pc": "0x403765d3", "function": "panic_abort",
             "file": "panic.c", "line": 118},
            {"pc": "0x40376b95", "function": "esp_restart_noos",
             "file": "panic.c", "line": 55}])
        self.assertEqual(sym["elf_sha256"],
                         _sha256_of(os.path.join(ws, "build", "app.elf")))
        self.assertEqual(sym["elf_sha256_captured"], SHA_S3)
        self.assertIs(sym["elf_sha_match"], True)

    def test_sha_mismatch_marks_reference_grade(self):
        ws = _mk_ws(self._td.name)
        self.addCleanup(_setenv({
            "F200_MAP": json.dumps(
                {"0x403765d3": "f at f.c:1", "0x40376b95": "g at g.c:2"}),
            "F200_LOG": os.path.join(self._td.name, "calls.log")}))
        sym = esp_runtime.symbolize_esp_panic(
            TEXT_S3, ws, addr2line_exe=self.bat)   # 捕获 sha ≠ 本地 elf
        self.assertTrue(sym["available"])
        self.assertIs(sym["elf_sha_match"], False)
        self.assertEqual(sym["elf_sha256_captured"], SHA_S3)
        self.assertEqual(len(sym["frames"]), 2)    # 漂移只降参考级, 不删帧

    def test_missing_state_json_failsoft(self):
        ws = os.path.join(self._td.name, "empty-ws")
        os.makedirs(ws, exist_ok=True)
        sym = esp_runtime.symbolize_esp_panic(
            TEXT_S3, ws, addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("elf_missing_key"),
                        sym["reason"])

    def test_empty_elf_file_value_failsoft(self):
        """_write_last_build 无 elf 产出时的真实形态: elf_file 空串。"""
        ws = _mk_ws(self._td.name, write_elf=False, elf_rel="")
        sym = esp_runtime.symbolize_esp_panic(
            TEXT_S3, ws, addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("elf_missing_key"),
                        sym["reason"])

    def test_flat_only_state_fails_nested_consumption(self):
        """口径 A2: 消费嵌套键 (release.py:212 同口径), 平铺键不兜底。"""
        ws = _mk_ws(self._td.name, nested=False)
        sym = esp_runtime.symbolize_esp_panic(
            TEXT_S3, ws, addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("elf_missing_key"),
                        sym["reason"])

    def test_elf_file_missing_on_disk_failsoft(self):
        ws = _mk_ws(self._td.name, write_elf=False)
        sym = esp_runtime.symbolize_esp_panic(
            TEXT_S3, ws, addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("elf_not_found"),
                        sym["reason"])
        self.assertIn("app.elf", sym["reason"])   # 点名缺失档

    def test_no_frames_failsoft_short_circuits_before_state(self):
        """abort()/assert 形态: 无帧即账 no_frames, 不触 state/工具。"""
        sym = esp_runtime.symbolize_esp_panic(
            "assert failed: x > 0, file main.c, line 7",
            r"Z:\no\state\here", addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("no_frames"), sym["reason"])

    def test_no_frames_keeps_captured_elf_sha(self):
        """abort 无 backtrace 但新 IDF 仍打 SHA 行 — 提取面独立于帧。"""
        text = ("abort() was called at PC 0x403765d3 on core 0\n"
                "ELF file SHA256: %s\n" % SHA_S3)
        sym = esp_runtime.symbolize_esp_panic(
            text, r"Z:\no\state\here", addr2line_exe=self.bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("no_frames"), sym["reason"])
        self.assertEqual(sym["elf_sha256_captured"], SHA_S3)

    def test_tools_dir_param_plumbs_into_locate(self):
        ws = _mk_ws(self._td.name)
        sym = esp_runtime.symbolize_esp_panic(
            _s3_text_with_sha(ws), ws, tools_dir=os.path.join(
                self._td.name, "no-such-tools"))
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("no_tools_dir"),
                        sym["reason"])

    def test_tool_error_keeps_elf_and_tool_fields(self):
        ws = _mk_ws(self._td.name)
        bat = _mk_fake_addr2line(self._td.name, _FAKE_SCRIPT_RC1)
        sym = esp_runtime.symbolize_esp_panic(
            _s3_text_with_sha(ws), ws, addr2line_exe=bat)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("tool_error"), sym["reason"])
        self.assertEqual(sym["tool"], "xtensa-esp-elf-addr2line.bat")
        self.assertEqual(sym["elf_path"], os.path.join(ws, "build", "app.elf"))

    def test_production_tools_dir_consumes_machine_json(self):
        """生产路径 (verify 零注入调用面): machine.json esp_tools_dir 消费
        + 真工具拒非 elf 档 (BFD "not recognized" rc≠0) → tool_error 账。
        装配缺省机器 skip (与 hooks 探针族同式)。"""
        tools = (load_machine() or {}).get("esp_tools_dir", "")
        if not tools or not os.path.isdir(tools):
            self.skipTest("machine.json esp_tools_dir 未装配")
        ws = _mk_ws(self._td.name, elf_bytes=b"not an elf at all")
        sym = esp_runtime.symbolize_esp_panic(_s3_text_with_sha(ws), ws)
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("tool_error"), sym["reason"])


class FormatBoxTests(SymbolizeLandedMixin, unittest.TestCase):
    """A5: stdout 人类可读解码框 + 降级/漂移形态。"""

    def test_box_gold_frames_and_count(self):
        sym = {"available": True, "tool": "xtensa-esp-elf-addr2line.exe",
               "elf_path": r"D:\ws\build\app.elf",
               "elf_sha256": "a" * 64, "elf_sha256_captured": "a" * 64,
               "elf_sha_match": True,
               "frames": [
                   {"pc": "0x40092f3c", "function": "app_main",
                    "file": "main/main.c", "line": 42},
                   {"pc": "0x40092f99", "unresolved": True}]}
        box = esp_runtime.format_symbol_box(sym)
        self.assertIn("xtensa-esp-elf-addr2line.exe", box)
        self.assertIn(r"D:\ws\build\app.elf", box)
        self.assertIn("#0 0x40092f3c  app_main  main/main.c:42", box)
        self.assertIn("#1 0x40092f99  [未解]", box)
        self.assertIn("解码 1/2 帧", box)
        self.assertNotIn("[参考级]", box)           # sha 一致无漂移警告

    def test_box_no_location_frame(self):
        sym = {"available": True, "tool": "t", "elf_path": "e",
               "frames": [{"pc": "0x40027d50",
                           "function": "lc_lmp_rx_ind_handler",
                           "file": None, "line": None}]}
        box = esp_runtime.format_symbol_box(sym)
        self.assertIn("#0 0x40027d50  lc_lmp_rx_ind_handler  位置未知", box)
        self.assertIn("解码 1/1 帧", box)

    def test_box_sha_drift_reference_warning(self):
        sym = {"available": True, "tool": "t", "elf_path": "e",
               "elf_sha256": "a" * 64, "elf_sha256_captured": "b" * 64,
               "elf_sha_match": False,
               "frames": [{"pc": "0x40000001", "unresolved": True}]}
        box = esp_runtime.format_symbol_box(sym)
        self.assertIn("[参考级]", box)
        self.assertIn("SHA", box)
        self.assertIn("仅供参考", box)

    def test_failsoft_single_note_line(self):
        note = esp_runtime.format_symbol_box(
            {"available": False, "reason": "elf_missing_key: state.json 缺"})
        self.assertIn("elf_missing_key", note)
        self.assertIn("原文 backtrace", note)
        self.assertNotIn("#0", note)               # 无框可打


class VerifyWiringTests(SymbolizeLandedMixin, unittest.TestCase):
    """A5 接线面: 上账 + 双流输出 + 判据零动 (沿 dispatch 钉 seam 先例)。"""

    def _args(self):
        return verify.argparse.Namespace(
            timeout=5, task_origin="manual",
            require_schedule_origin=False, json=True)

    def test_wiring_ledger_and_box_and_judgment_untouched(self):
        fixed = {"available": True, "tool": "fake-addr2line",
                 "elf_path": r"W:\ws\build\app.elf",
                 "frames": [{"pc": "0x40092f3c", "function": "app_main",
                             "file": "main/main.c", "line": 42}]}
        cfg = {"capture": {"backend": "uart", "port": "COM9"},
               "verify": {}}
        result = {"steps": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "ok", "method": "uart",
                                   "esp_panic": True,
                                   "_text": TEXT_CLASSIC}), \
             mock.patch.object(esp_runtime, "symbolize_esp_panic",
                               return_value=dict(fixed)), \
             mock.patch.object(verify, "append_audit_entry"):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), \
                 contextlib.redirect_stderr(err):
                verify._run_capture_step(
                    self._args(), cfg, result, None, False, "uart", {}, 0, "")
        self.assertEqual(result["esp_panic_symbolized"], fixed)
        self.assertTrue(result.get("esp_panic"))     # 判据链零动: 原标记在
        self.assertNotIn("status", result)           # 符号化不设 status
        self.assertIn("#0 0x40092f3c  app_main  main/main.c:42", out.getvalue())
        self.assertIn("解码 1/1 帧", out.getvalue())
        self.assertNotIn("符号化不可用", err.getvalue())

    def test_wiring_failsoft_real_chain_no_state(self):
        """真符号化链 (无 state.json → fail-soft): stderr 注记, 无框,
        台账 available=false — 零抛穿即 A2 的接线面机检。"""
        cfg = {"capture": {"backend": "uart", "port": "COM9"},
               "verify": {}}
        result = {"steps": {}}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(esp_runtime, "step_capture_uart",
                     return_value={"status": "ok", "method": "uart",
                                   "esp_panic": True,
                                   "_text": TEXT_CLASSIC}), \
             mock.patch.object(verify, "append_audit_entry"):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), \
                 contextlib.redirect_stderr(err):
                verify._run_capture_step(
                    self._args(), cfg, result, None, False, "uart", {}, 0, "")
        sym = result["esp_panic_symbolized"]
        self.assertEqual(sym["available"], False)
        self.assertTrue(sym["reason"].startswith("elf_missing_key"),
                        sym["reason"])
        self.assertNotIn("== ESP panic 符号化", out.getvalue())  # 无框
        self.assertIn("符号化不可用", err.getvalue())
        self.assertTrue(result.get("esp_panic"))


if __name__ == "__main__":
    unittest.main()
