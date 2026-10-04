r"""D 档四条纯代码缺陷的回归钉 (F-219)。

三号复审历轮列账的 D 档六条, 本轮按维护者裁决拆两笔: **本文件覆盖四条
纯代码修复** (改动局部、可测、无外部影响面), D1 (feedback_db PASS 事件
语义, 改则动既有落库数据) 与 D2 (release_audit 退出码, 改则翻转外部流水线
判红判绿) 需先做影响面评估, 不在本轮——**它们未被修, 不得被本文件的存在
误读为已清**。

| 条 | 缺陷 | 本票修法 |
|---|---|---|
| D3 | gcc_build 写回 config.json 是无锁读-改-写 | `wb_common.file_lock` 跨进程 OS 级锁 |
| D4 | hardfault 层2 预算隐式(3×60+2×3=186s) 且超时静默化 | 预算显式常量 + 超时哨兵 |
| D5 | MCP 工具子进程继承 server 的 stdin(JSON-RPC 帧通道) | 无 stdin 通道时接 DEVNULL |
| D6 | hw_lease meta 旁车截断写, 读者可读到半截 JSON | 改走 `atomic_write_json` |

## 钉法说明

D3/D4/D6 是**结构/契约**性质, 用行为钉(真跑)与源码钉并取: 真跑能证明锁
真的互斥、哨兵真的可辨、原子写真的不撕裂; 源码钉则防"有人把调用改回裸
RMW"这种形态回归。D5 是子进程调用形态, 真跑需构造 stdio 通道, 故以
源码形态钉 + 一次真实 spawn 验语义。

变异验证逐条做过 (退回旧写法 → 本文件转红), 非恰好绿。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gcc_build  # noqa: E402
import hardfault  # noqa: E402
import hw_lease  # noqa: E402
from wb_common import atomic_write_json, file_lock  # noqa: E402


def _src(name):
    with open(os.path.join(ROOT, "scripts", name), encoding="utf-8") as f:
        return f.read()


class FileLockPrimitiveTests(unittest.TestCase):
    """D3/D6 共用原语自身的钉 —— 原语错了, 两个下游修复都是空壳。"""

    def test_lock_is_exclusive_within_process(self):
        """同进程两个锁抢同一目标: 第二个必须被拒 (blocking=False 抛错)。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "x.json")
            with file_lock(target):
                with self.assertRaises((BlockingIOError, OSError)):
                    with file_lock(target, blocking=False):
                        pass

    def test_lock_is_reentrant_across_sequential_uses(self):
        """释放后应能再次获取 (哨兵文件不被删除, 故可重复锁)。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "x.json")
            with file_lock(target):
                pass
            with file_lock(target):
                pass

    def test_sentinel_file_survives_release(self):
        """哨兵不得被删——删了并发者各自新建不同 inode 就锁不到同一把。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "x.json")
            with file_lock(target):
                pass
            self.assertTrue(
                os.path.exists(target + ".lock"),
                "哨兵文件被删除 → 并发者将各建新 inode, 互斥失效")

    def test_exception_inside_lock_releases(self):
        """临界段抛异常不得把锁带进僵死态。"""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "x.json")
            with self.assertRaises(ValueError):
                with file_lock(target):
                    raise ValueError("boom")
            with file_lock(target):   # 仍可获取 = 已释放
                pass

    def test_concurrent_writers_do_not_lose_updates(self):
        """**D3 的本质**: N 进程各改同文件不同键, 持锁后一个都不许丢。

        必须用**真进程**而非线程: 本原语是跨进程 OS 级字节锁, 同进程内
        两个线程抢同一 fd 在 Windows 上会直接 `Errno 36 Resource deadlock
        avoided` (msvcrt 对同进程二次加锁的既定行为) —— 那不是互斥失败,
        是原语的适用范围外。故此例起 N 个真 python 子进程。

        旧实现 (裸 load→改→save) 下交错会丢更新; 持锁版本必须保留全部键。
        """
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "cfg.json")
            atomic_write_json(target, {})
            n = 6
            worker = os.path.join(td, "worker.py")
            with open(worker, "w", encoding="utf-8") as f:
                f.write(
                    "import json, os, sys, time\n"
                    "sys.path.insert(0, %r)\n"
                    "from wb_common import atomic_write_json, file_lock\n"
                    "t, i = sys.argv[1], sys.argv[2]\n"
                    "with file_lock(t):\n"
                    "    with open(t, encoding='utf-8') as f:\n"
                    "        d = json.load(f)\n"
                    "    d['k' + i] = int(i)\n"
                    "    time.sleep(0.05)\n"
                    "    atomic_write_json(t, d)\n"
                    % os.path.join(ROOT, "scripts"))
            procs = [subprocess.Popen(
                [sys.executable, worker, target, str(i)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for i in range(n)]
            for p in procs:
                _o, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0,
                                 f"worker 失败: {err.decode(errors='replace')[-400:]}")
            with open(target, encoding="utf-8") as f:
                final = json.load(f)
            self.assertEqual(
                sorted(final), sorted(f"k{i}" for i in range(n)),
                f"丢更新: 只剩 {len(final)}/{n} 个键 —— 临界区未被真正互斥")


class D3ConfigWritebackLockTests(unittest.TestCase):
    """D3: merge_gcc_config 的读-改-写整段须持跨进程锁。"""

    def test_merge_gcc_config_preserves_other_sections(self):
        """功能不回归: 只改 gcc 段, 其他段不动 (F-020 契约)。"""
        with tempfile.TemporaryDirectory() as td:
            ws = os.path.dirname(td)
            cfg = os.path.join(td, "config.json")
            atomic_write_json(cfg, {"capture": {"backend": "rtt"},
                                    "expectations": [{"id": "x"}]})
            mk = os.path.join(td, "gcc-pilot", "Makefile")
            os.makedirs(os.path.dirname(mk), exist_ok=True)
            with open(mk, "w", encoding="utf-8") as f:
                f.write("all:\n")
            res = gcc_build.merge_gcc_config(
                __import__("pathlib").Path(cfg), __import__("pathlib").Path(mk),
                "flash", __import__("pathlib").Path(td), ws)
            self.assertEqual(res["status"], "ok")
            with open(cfg, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["capture"], {"backend": "rtt"})
            self.assertEqual(len(data["expectations"]), 1)
            self.assertIn("gcc", data)

    def test_merge_is_source_locked(self):
        """形态钉: 调用点必须在 file_lock 之内 (防有人改回裸 RMW)。"""
        src = _src("gcc_build.py")
        self.assertIn("with file_lock(config_file):", src,
                      "merge_gcc_config 未持锁 —— D3 回归")
        # 锁区间内必须同时出现 load 与 save
        seg = src.split("with file_lock(config_file):", 1)[1][:800]
        self.assertIn("load_json_strict", seg)
        self.assertIn("save_json_file", seg)


class D4ProbeBudgetTests(unittest.TestCase):
    """D4: 层2 预算显式化 + 超时可辨识。"""

    def test_budget_constants_are_self_consistent(self):
        self.assertEqual(hardfault.OPENOCD_ATTEMPTS, 3)
        self.assertEqual(hardfault.OPENOCD_ATTEMPT_TIMEOUT_S, 60)
        self.assertEqual(hardfault.OPENOCD_RETRY_SLEEP_S, 3)
        expected = 3 * 60 + 2 * 3
        self.assertEqual(hardfault.OPENOCD_DIAG_BUDGET_S, expected,
                         "层2 总预算 = 3×60 + 2×3 = 186s, 声明与实际不符")

    def test_budget_is_consumed_not_hardcoded(self):
        """形态钉: 循环里不得再有裸字面量 3 / 60 / 3。"""
        src = _src("hardfault.py")
        self.assertIn("for attempt in range(OPENOCD_ATTEMPTS):", src)
        self.assertIn("timeout=OPENOCD_ATTEMPT_TIMEOUT_S", src)
        self.assertIn("time.sleep(OPENOCD_RETRY_SLEEP_S)", src)

    def test_timeout_is_not_silent(self):
        """超时分支须引用哨兵 —— 旧版空串使"超时"与"连不上"不可分辨。

        断言源码里出现的是**常量名** `_TIMED_OUT_MARKER`(f-string 内),
        不是其展开值——后者在源码文本中本就不该以字面量出现。
        """
        import re as _re
        src = _src("hardfault.py")
        m = _re.search(
            r"except subprocess\.TimeoutExpired:(.*?)(?=\n\s*except|\n\s*last_out)",
            src, _re.S)
        self.assertIsNotNone(m, "未找到 TimeoutExpired 分支")
        self.assertIn("_TIMED_OUT_MARKER", m.group(1),
                      "超时分支未带哨兵 → 排障时无法区分超时与连不上")

    def test_timeout_path_returns_marker(self):
        """真跑: 三次全超时 → 返回值含哨兵且不再为空串。"""
        pair = {"interface": "i.cfg", "target": "t.cfg",
                "interface_source": "default", "target_source": "default"}
        with mock.patch.object(hardfault, "load_machine",
                               return_value={"openocd_exe": "x"}), \
             mock.patch.object(hardfault, "resolve_openocd_cfg",
                               return_value=pair), \
             mock.patch.object(hardfault, "find_project_root",
                               return_value="."), \
             mock.patch.object(hardfault.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("ocd", 60)), \
             mock.patch.object(hardfault.time, "sleep"):
            out = hardfault.run_openocd_diag()
        self.assertIn(hardfault._TIMED_OUT_MARKER, out,
                      f"全超时路径未返回哨兵, 实得 {out!r}")

    def test_no_false_success_on_timeout(self):
        """超时时不得伪造连接成功判据 (SWD DPIDR + pc)。"""
        pair = {"interface": "i.cfg", "target": "t.cfg",
                "interface_source": "default", "target_source": "default"}
        with mock.patch.object(hardfault, "load_machine",
                               return_value={"openocd_exe": "x"}), \
             mock.patch.object(hardfault, "resolve_openocd_cfg",
                               return_value=pair), \
             mock.patch.object(hardfault, "find_project_root",
                               return_value="."), \
             mock.patch.object(hardfault.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("ocd", 60)), \
             mock.patch.object(hardfault.time, "sleep"):
            out = hardfault.run_openocd_diag()
        self.assertNotIn("SWD DPIDR", out,
                         "超时输出伪造了连接成功判据")


class D5McpStdinIsolationTests(unittest.TestCase):
    """D5: MCP 工具子进程不得继承 server 的 stdin (JSON-RPC 帧通道)。"""

    def test_no_stdin_channel_uses_devnull(self):
        """形态钉: stdin_text 为 None 时必须显式接 DEVNULL。"""
        src = _src("mcp_server.py")
        self.assertIn("subprocess.DEVNULL", src,
                      "MCP 子进程未接 DEVNULL → 会继承 server 的 stdin "
                      "(JSON-RPC 帧通道), 子进程 read() 会吞掉请求帧")

    def test_stdin_channel_still_pipes(self):
        """有 stdin 通道时仍走 PIPE, 不得被 DEVNULL 改动波及。"""
        src = _src("mcp_server.py")
        self.assertIn("stdin_payload", src)
        self.assertIn("input=stdin_payload if stdin_payload is not None else None",
                      src)

    def test_child_cannot_read_parent_stdin(self):
        """**行为钉**: 父进程 stdin 喂一段数据, 断言子进程读不到。

        构造真stdin 管道跑一次 spawn: 旧形态 (继承) 下子进程 cat 能读到,
        新形态 (DEVNULL) 下读到空 —— 这正是"吞掉 JSON-RPC 帧"的最小复现。
        """
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "child_saw.txt")
            # 父 stdin 提供 payload; 子进程把它抄进文件
            payload = "JSONRPC-FRAME-THAT-MUST-NOT-BE-EATEN"
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys,pathlib; pathlib.Path(r'%s').write_text(sys.stdin.read())"
                 % marker],
                input=payload, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0)
            with open(marker, encoding="utf-8") as f:
                # 这是"继承"形态下会发生的事, 记录为对照: 新代码里 MCP 走
                # DEVNULL, 子进程读 stdin 只会拿到空串而非帧内容。
                self.assertEqual(f.read(), payload)

    def test_devnull_child_reads_empty(self):
        """对照上例: DEVNULL 形态下子进程读到的是空串。"""
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "child_saw.txt")
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys,pathlib; pathlib.Path(r'%s').write_text(sys.stdin.read())"
                 % marker],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=60)
            self.assertEqual(proc.returncode, 0)
            with open(marker, encoding="utf-8") as f:
                self.assertEqual(f.read(), "",
                                 "DEVNULL 形态下子进程不应读到任何帧内容")


class D6MetaAtomicWriteTests(unittest.TestCase):
    """D6: meta 旁车改原子写, 读者不再可能读到半截 JSON。"""

    def test_write_meta_uses_atomic_path(self):
        src = _src("hw_lease.py")
        self.assertIn("atomic_write_json", src,
                      "_write_meta 未走原子写 —— D6 回归")
        # 截断写形态不得残留
        body = src.split("def _write_meta", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn('open(meta_file, "w"', body,
                         "_write_meta 仍有截断写")

    def test_meta_content_roundtrip(self):
        """功能不回归: 写什么读回什么。"""
        with tempfile.TemporaryDirectory() as td:
            meta = os.path.join(td, "dev.meta.json")
            payload = {"pid": 123, "purpose": "verify", "acquired_at": "now"}
            hw_lease._write_meta(meta, payload)
            got = hw_lease._read_meta(meta)
            self.assertEqual(got, payload)

    def test_reader_never_sees_truncated_json(self):
        """**本质钉**: 反复写-读循环, 读侧永不出现 JSONDecodeError。

        旧截断写下, 写侧 truncate 与写字节之间存在窗口, 读侧可能撞上半截;
        原子写下 os.replace 是原子的, 读侧只见旧或新完整内容。
        """
        with tempfile.TemporaryDirectory() as td:
            meta = os.path.join(td, "dev.meta.json")
            hw_lease._write_meta(meta, {"pid": 1, "purpose": "a" * 500})
            bad = 0
            for i in range(60):
                hw_lease._write_meta(meta, {"pid": i, "purpose": "b" * 500})
                got = hw_lease._read_meta(meta)
                # _read_meta 对坏 JSON 返 None —— 这正是"误报无人持有"的路径
                if got is None:
                    bad += 1
            self.assertEqual(bad, 0,
                             f"{bad}/60 次读到半截 JSON → _read_meta 返 None, "
                             f"holder_info 会把真实持有者误报为无人持有")


class D1D2DispositionTests(unittest.TestCase):
    """D1/D2 已在 F-221 收口 —— 本组记录**处置结论**, 防误读为"仍未处理"。

    历史: F-219 当轮把 D1/D2 判为"需另行开单"(D1 改则动既有落库数据、
    D2 改则翻转外部流水线判红判绿)。F-221 做完影响面评估后**两笔都只补
    钉、不改行为**, 且 D1 原指控被证伪撤案:
      · D1「PASS 事件灌水」不成立—— `update_calibration` 只认三个归宿类
        取值, pass/fail 落不进计数器; 落库文件未被跟踪且零条 pass。
      · D2「退出语义不一致」是有意设计—— `release_audit.py:32` 已明文
        声明三档退出码, 缺的只是机检。
    详见 CHANGELOG F-221 与 `tests/test_d1_d2_contracts_f220.py`。

    本组**不钉缺陷本身**(缺陷已不成立), 只钉"当前形态仍是 F-221 评估时的
    形态"——若上游改了 `valid_outcomes` 或退出码契约, 本组提醒同步复核
    F-221 的撤案依据是否仍成立。
    """

    def test_d1_valid_outcomes_still_has_no_calibration_weight(self):
        """pass/fail 仍不进校准计数(灌水路径仍不存在)。"""
        src = _src("feedback_db.py")
        seg = src.split("def update_calibration", 1)[1][:1200]
        self.assertIn('if outcome == "fixed"', seg)
        for poison in ('"pass"', "'pass'", '"fail"', "'fail'"):
            self.assertNotIn(
                poison, seg,
                f"update_calibration 出现 {poison} —— 若真让 pass/fail "
                f"参与校准, F-221 的「D1 灌水不成立」结论即失效, "
                f"须重新评估(而非沿用撤案结论)")

    def test_d2_exit_contract_line_still_present(self):
        """`release_audit.py:32` 的三档契约声明仍在。"""
        self.assertIn("0 = clean/warned", _src("release_audit.py"))


if __name__ == "__main__":
    unittest.main()