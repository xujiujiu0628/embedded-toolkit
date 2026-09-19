r"""OpenOCD cfg 组装 7 处调用点的默认 argv 身份钉 (WB-20260919-06, 先钉后拆)。

案发现场 (F-108/M-3 grep 全量取证 + 2026-09-19 复核, 行号为 c0df0c6 现值):
  capture_rtt.py:94 / capture_semihosting.py:41-42 / hardfault.py:83-84 /
  openocd_runtime.py:175-176 (swd_probe) 及 :513 (_RESET_CFG_DEFAULT) /
  physical_gate.py:109-110 / verify.py:241-242 —— 每处一对
  `interface/stlink.cfg` + `target/stm32f1x.cfg`。

本文件 (钉, 拆之前提交) 用 mock argv 捕获证明七处今日产出同一 cfg 对;
拆 (参数化解析器收敛) 之后本文件必须原样保持绿 = 默认行为逐字节不变的
机器证明。test_verify_esp_dispatch.py:75 的既有身份钉不动、并行有效。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import capture_rtt  # noqa: E402
import capture_semihosting  # noqa: E402
import hardfault  # noqa: E402
import json  # noqa: E402
import openocd_run  # noqa: E402
import openocd_runtime  # noqa: E402
import physical_gate  # noqa: E402
import runtime_common  # noqa: E402
import verify  # noqa: E402

DEFAULT_PAIR = ("interface/stlink.cfg", "target/stm32f1x.cfg")
FAKE_EXE = "ocd-fake.exe"


def _cfg_pair(cmd):
    """从 openocd argv 提取 (-f interface, -f target) 对。"""
    fs = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
    return tuple(fs[:2])


class CaptureSemihostingSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("OUT", "ERR")
        with mock.patch.object(capture_semihosting.subprocess, "Popen",
                               return_value=proc) as mp, \
             mock.patch.object(capture_semihosting, "load_machine",
                               return_value={"openocd_exe": FAKE_EXE}):
            stdout, _ = capture_semihosting.run_semihosting_session(5, None)
        self.assertEqual((stdout, _), ("OUT", "ERR"))
        cmd = mp.call_args[0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        # cfg 对必须紧随 exe 连续出现 (现状组装形态)
        self.assertEqual(cmd[1:5], ["-f", DEFAULT_PAIR[0],
                                    "-f", DEFAULT_PAIR[1]])


class CaptureRttSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        sock = mock.Mock()
        sock.recv.return_value = b""    # telnet 读/数据读都立即 EOF
        proc = mock.Mock()
        proc.stderr = iter(["Info : Listening on port 4444\n"])
        proc.poll.return_value = None
        with mock.patch.object(capture_rtt.subprocess, "Popen",
                               return_value=proc) as mp, \
             mock.patch.object(capture_rtt, "load_machine",
                               return_value={"openocd_exe": FAKE_EXE}), \
             mock.patch.object(capture_rtt.socket, "create_connection",
                               return_value=sock), \
             mock.patch.object(capture_rtt.time, "sleep"):
            r = capture_rtt.step_capture_rtt(0.2, {}, None)
        self.assertEqual(r["status"], "ok")
        cmd = mp.call_args_list[0][0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)


class HardfaultSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        run = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(hardfault.subprocess, "run",
                               return_value=run) as mp, \
             mock.patch.object(hardfault, "load_machine",
                               return_value={"openocd_exe": FAKE_EXE}), \
             mock.patch.object(hardfault.time, "sleep"):
            out = hardfault.run_openocd_diag()   # 无 SWD DPIDR → 3 探后放弃
        self.assertEqual(out.strip(), "")
        cmd = mp.call_args_list[0][0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)


class SwdProbeSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        run = mock.Mock(returncode=1, stdout="", stderr="")
        with mock.patch.object(openocd_runtime.subprocess, "run",
                               return_value=run) as mp:
            ok, _msg = openocd_runtime.swd_probe(FAKE_EXE, attempts=1)
        self.assertFalse(ok)
        cmd = mp.call_args[0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)


class ResetTargetSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        run = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(openocd_runtime.subprocess, "run",
                               return_value=run) as mp:
            r = openocd_runtime.reset_target(FAKE_EXE)
        self.assertEqual(r["status"], "error")   # 无 shutdown 行 → 不按成功
        cmd = mp.call_args[0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)

    def test_explicit_cfg_bypasses_default(self):
        run = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(openocd_runtime.subprocess, "run",
                               return_value=run) as mp:
            openocd_runtime.reset_target(FAKE_EXE,
                                         cfg=["interface/x.cfg",
                                              "target/y.cfg"])
        self.assertEqual(_cfg_pair(mp.call_args[0][0]),
                         ("interface/x.cfg", "target/y.cfg"))


class PhysicalGateSiteTests(unittest.TestCase):
    def test_default_argv_pair(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("", "")
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(physical_gate.subprocess, "Popen",
                               return_value=proc) as mp, \
             mock.patch.object(physical_gate, "load_machine",
                               return_value={"openocd_exe": FAKE_EXE}), \
             mock.patch.object(physical_gate.time, "sleep"):
            r = physical_gate.step_physical_gate(
                {"enable": True, "expected_toggles_per_sec": 4.0}, 5, td)
        self.assertEqual(r["status"], "probe_error")   # 无 PHYS_GATE_RESULT 行
        cmd = mp.call_args_list[0][0][0]
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)


class VerifyStepFlashSiteTests(unittest.TestCase):
    def _flash_cmd(self, td):
        rel = os.path.join("build", "app.hex")
        os.makedirs(os.path.join(td, "build"), exist_ok=True)
        open(os.path.join(td, rel), "w").close()
        with mock.patch.object(verify, "WORKSPACE", td), \
             mock.patch.object(verify, "_openocd_exe",
                               return_value=FAKE_EXE), \
             mock.patch.object(verify, "run_cmd",
                               return_value={"status": "ok", "returncode": 0,
                                             "stdout": openocd_run.ACTION_DONE_MARKER + "\n",
                                             "stderr": ""}) as m:
            r = verify.step_flash(rel, None)
        self.assertEqual(r["status"], "ok")
        return m.call_args[0][0]

    def test_default_argv_pair(self):
        with tempfile.TemporaryDirectory() as td:
            cmd = self._flash_cmd(td)
        self.assertEqual(cmd[0], FAKE_EXE)
        self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR)


class CrossSiteIdentityTests(unittest.TestCase):
    """七处调用点今日产出同一 cfg 对 —— 拆后本钉是"默认逐字节不变"的总证。"""

    def test_all_seven_sites_share_default_pair(self):
        results = {}
        with tempfile.TemporaryDirectory() as td:
            results["capture_semihosting"] = _cfg_pair(_semihosting_capture())
            results["capture_rtt"] = _cfg_pair(_rtt_capture())
            results["hardfault"] = _cfg_pair(_hardfault_capture())
            results["swd_probe"] = _cfg_pair(_swd_probe_capture())
            results["reset_target"] = _cfg_pair(_reset_capture())
            results["physical_gate"] = _cfg_pair(_physical_gate_capture(td))
            results["verify.step_flash"] = _cfg_pair(_flash_capture(td))
        for site, pair in results.items():
            with self.subTest(site=site):
                self.assertEqual(pair, DEFAULT_PAIR, site)


# —— 供 CrossSiteIdentityTests 复用的裸捕获函数 (返回 openocd argv) ——

def _semihosting_capture():
    proc = mock.Mock()
    proc.communicate.return_value = ("", "")
    with mock.patch.object(capture_semihosting.subprocess, "Popen",
                           return_value=proc) as mp, \
         mock.patch.object(capture_semihosting, "load_machine",
                           return_value={"openocd_exe": FAKE_EXE}):
        capture_semihosting.run_semihosting_session(1, None)
    return mp.call_args[0][0]


def _rtt_capture():
    sock = mock.Mock()
    sock.recv.return_value = b""
    proc = mock.Mock()
    proc.stderr = iter(["Info : Listening on port 4444\n"])
    proc.poll.return_value = None
    with mock.patch.object(capture_rtt.subprocess, "Popen",
                           return_value=proc) as mp, \
         mock.patch.object(capture_rtt, "load_machine",
                           return_value={"openocd_exe": FAKE_EXE}), \
         mock.patch.object(capture_rtt.socket, "create_connection",
                           return_value=sock), \
         mock.patch.object(capture_rtt.time, "sleep"):
        capture_rtt.step_capture_rtt(0.2, {}, None)
    return mp.call_args_list[0][0][0]


def _hardfault_capture():
    run = mock.Mock(returncode=0, stdout="", stderr="")
    with mock.patch.object(hardfault.subprocess, "run", return_value=run) as mp, \
         mock.patch.object(hardfault, "load_machine",
                           return_value={"openocd_exe": FAKE_EXE}), \
         mock.patch.object(hardfault.time, "sleep"):
        hardfault.run_openocd_diag()
    return mp.call_args_list[0][0][0]


def _swd_probe_capture():
    run = mock.Mock(returncode=1, stdout="", stderr="")
    with mock.patch.object(openocd_runtime.subprocess, "run",
                           return_value=run) as mp:
        openocd_runtime.swd_probe(FAKE_EXE, attempts=1)
    return mp.call_args[0][0]


def _reset_capture():
    run = mock.Mock(returncode=0, stdout="", stderr="")
    with mock.patch.object(openocd_runtime.subprocess, "run",
                           return_value=run) as mp:
        openocd_runtime.reset_target(FAKE_EXE)
    return mp.call_args[0][0]


def _physical_gate_capture(td):
    proc = mock.Mock()
    proc.communicate.return_value = ("", "")
    with mock.patch.object(physical_gate.subprocess, "Popen",
                           return_value=proc) as mp, \
         mock.patch.object(physical_gate, "load_machine",
                           return_value={"openocd_exe": FAKE_EXE}), \
         mock.patch.object(physical_gate.time, "sleep"):
        physical_gate.step_physical_gate(
            {"enable": True, "expected_toggles_per_sec": 4.0}, 5, td)
    return mp.call_args_list[0][0][0]


def _flash_capture(td):
    rel = os.path.join("build", "app.hex")
    os.makedirs(os.path.join(td, "build"), exist_ok=True)
    open(os.path.join(td, rel), "w").close()
    with mock.patch.object(verify, "WORKSPACE", td), \
         mock.patch.object(verify, "_openocd_exe", return_value=FAKE_EXE), \
         mock.patch.object(verify, "run_cmd",
                           return_value={"status": "ok", "returncode": 0,
                                         "stdout": openocd_run.ACTION_DONE_MARKER + "\n",
                                         "stderr": ""}) as m:
        verify.step_flash(rel, None)
    return m.call_args[0][0]


if __name__ == "__main__":
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════
# 拆 (WB-20260919-06 commit 2): 解析器语义钉 + 7 点收敛钉
# ══════════════════════════════════════════════════════════════════════════

def _write_toolkit_cfg(tmpdir, obj):
    path = os.path.join(tmpdir, "openocd.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


class ResolverSemanticsTests(unittest.TestCase):
    """resolve_openocd_cfg 四层优先级 + F-103 报错语义。"""

    def test_default_pair_bytes_unchanged(self):
        """工具库配置缺席 (临时空目录) 时回落内置默认 = 现硬编码两串逐字节。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(runtime_common, "TOOLKIT_OPENOCD_CFG_FILE",
                                   os.path.join(td, "absent.json")):
                out = runtime_common.resolve_openocd_cfg()
        self.assertEqual(out["interface"], "interface/stlink.cfg")
        self.assertEqual(out["target"], "target/stm32f1x.cfg")
        self.assertEqual(out["interface_source"], "default")
        self.assertEqual(out["target_source"], "default")

    def test_toolkit_layer_served_by_real_repo_config(self):
        """仓内 config/openocd.json 已带同值可选键 → toolkit 层在场且同值。"""
        out = runtime_common.resolve_openocd_cfg()
        self.assertEqual(out["interface_source"], "toolkit")
        self.assertEqual(out["interface"], "interface/stlink.cfg")

    def test_toolkit_layer_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_toolkit_cfg(td, {"interface_cfg": "interface/t.cfg"})
            with mock.patch.object(runtime_common, "TOOLKIT_OPENOCD_CFG_FILE",
                                   cfg):
                out = runtime_common.resolve_openocd_cfg()
        self.assertEqual(out["interface"], "interface/t.cfg")
        self.assertEqual(out["interface_source"], "toolkit")
        self.assertEqual(out["target_source"], "default")   # 未覆盖键独立回落

    def test_project_layer_beats_toolkit(self):
        # project_config 注入形态 = openocd 段 dict (与 load_skill_section
        # 返回形态一致), 不是整份 config.json
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_toolkit_cfg(td, {"interface_cfg": "interface/t.cfg"})
            with mock.patch.object(runtime_common, "TOOLKIT_OPENOCD_CFG_FILE",
                                   cfg):
                out = runtime_common.resolve_openocd_cfg(
                    project_config={"interface_cfg": "interface/p.cfg"})
        self.assertEqual(out["interface"], "interface/p.cfg")
        self.assertEqual(out["interface_source"], "project")
        self.assertEqual(out["target_source"], "default")   # 逐键独立解析 (临时
        # toolkit 文件只写了 interface_cfg, target 无覆盖键回落默认)

    def test_explicit_args_beat_everything(self):
        out = runtime_common.resolve_openocd_cfg(
            interface="interface/c.cfg", target="target/c2.cfg",
            project_config={"interface_cfg": "interface/p.cfg"})
        self.assertEqual(out["interface"], "interface/c.cfg")
        self.assertEqual(out["interface_source"], "cli")
        self.assertEqual(out["target"], "target/c2.cfg")
        self.assertEqual(out["target_source"], "cli")

    def test_workspace_none_skips_project_layer(self):
        """workspace=None 时工程层整体跳过 (swd_probe 预检语义):
        即使把工程配置经 project_config 显式塞入也不会被使用——不, project_config
        注入是显式层, 此处钉的是"无 workspace 且无注入 → 工程层缺席"。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(runtime_common, "TOOLKIT_OPENOCD_CFG_FILE",
                                   os.path.join(td, "absent.json")):
                out = runtime_common.resolve_openocd_cfg(workspace=None)
        self.assertNotIn("project", (out["interface_source"],
                                     out["target_source"]))
        self.assertEqual(out["interface_source"], "default")

    def test_project_config_via_workspace_path(self):
        with tempfile.TemporaryDirectory() as td:
            ws = os.path.join(td, "proj")
            os.makedirs(os.path.join(ws, ".workbench"))
            with open(os.path.join(ws, ".workbench", "config.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"openocd": {"target_cfg": "target/w.cfg"}}, f)
            with mock.patch.object(runtime_common, "TOOLKIT_OPENOCD_CFG_FILE",
                                   os.path.join(td, "absent.json")):
                out = runtime_common.resolve_openocd_cfg(workspace=ws)
        self.assertEqual(out["target"], "target/w.cfg")
        self.assertEqual(out["target_source"], "project")

    def test_invalid_values_raise_f103_no_silent_fallback(self):
        bad = [123, "", "   ", "a\nb", "a\rb"]
        for key in ("interface_cfg", "target_cfg"):
            for v in bad:
                with self.subTest(key=key, value=repr(v)):
                    with self.assertRaises(runtime_common.OpenocdCfgError):
                        runtime_common.resolve_openocd_cfg(
                            project_config={key: v})

    def test_invalid_cli_value_raises_even_with_defaults(self):
        with self.assertRaises(runtime_common.OpenocdCfgError):
            runtime_common.resolve_openocd_cfg(interface="a\nb")

    def test_source_metadata_shape(self):
        out = runtime_common.resolve_openocd_cfg(interface="interface/z.cfg")
        self.assertEqual(
            sorted(out.keys()),
            ["interface", "interface_source", "target", "target_source"])


class ConvergenceTests(unittest.TestCase):
    """7 处调用点全部经解析器 (mock 包裹记录调用), argv 保持逐字节不变。"""

    def _wrap(self, calls):
        real = runtime_common.resolve_openocd_cfg

        def wrapper(*a, **kw):
            calls.append((a, kw))
            return real(*a, **kw)
        return wrapper

    def _run_all_sites(self):
        """跑全部 7 处调用点, 返回 {site: (argv, resolver 调用次数)}。

        argv 必须在各 patch 上下文**内部**捕获 (with 退出即还原,
        call_args 读不到)。"""
        out = {}
        with tempfile.TemporaryDirectory() as td:
            # capture_semihosting
            calls = []
            proc = mock.Mock()
            proc.communicate.return_value = ("", "")
            with mock.patch.object(capture_semihosting, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(capture_semihosting.subprocess, "Popen",
                                   return_value=proc) as mp, \
                 mock.patch.object(capture_semihosting, "load_machine",
                                   return_value={"openocd_exe": FAKE_EXE}):
                capture_semihosting.run_semihosting_session(1, None)
                out["capture_semihosting"] = (mp.call_args[0][0], len(calls))
            # capture_rtt
            calls = []
            sock = mock.Mock()
            sock.recv.return_value = b""
            proc = mock.Mock()
            proc.stderr = iter(["Info : Listening on port 4444\n"])
            proc.poll.return_value = None
            with mock.patch.object(capture_rtt, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(capture_rtt.subprocess, "Popen",
                                   return_value=proc) as mp, \
                 mock.patch.object(capture_rtt, "load_machine",
                                   return_value={"openocd_exe": FAKE_EXE}), \
                 mock.patch.object(capture_rtt.socket, "create_connection",
                                   return_value=sock), \
                 mock.patch.object(capture_rtt.time, "sleep"):
                capture_rtt.step_capture_rtt(0.2, {}, None)
                out["capture_rtt"] = (
                    mp.call_args_list[0][0][0], len(calls))
            # hardfault
            calls = []
            run = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch.object(hardfault, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(hardfault.subprocess, "run",
                                   return_value=run) as mp, \
                 mock.patch.object(hardfault, "load_machine",
                                   return_value={"openocd_exe": FAKE_EXE}), \
                 mock.patch.object(hardfault.time, "sleep"):
                hardfault.run_openocd_diag()
                out["hardfault"] = (mp.call_args_list[0][0][0], len(calls))
            # swd_probe
            calls = []
            run = mock.Mock(returncode=1, stdout="", stderr="")
            with mock.patch.object(openocd_runtime, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(openocd_runtime.subprocess, "run",
                                   return_value=run) as mp:
                openocd_runtime.swd_probe(FAKE_EXE, attempts=1)
                out["swd_probe"] = (mp.call_args[0][0], len(calls))
            # reset_target
            calls = []
            run = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch.object(openocd_runtime, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(openocd_runtime.subprocess, "run",
                                   return_value=run) as mp:
                openocd_runtime.reset_target(FAKE_EXE)
                out["reset_target"] = (mp.call_args[0][0], len(calls))
            # physical_gate
            calls = []
            proc = mock.Mock()
            proc.communicate.return_value = ("", "")
            with mock.patch.object(physical_gate, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(physical_gate.subprocess, "Popen",
                                   return_value=proc) as mp, \
                 mock.patch.object(physical_gate, "load_machine",
                                   return_value={"openocd_exe": FAKE_EXE}), \
                 mock.patch.object(physical_gate.time, "sleep"):
                physical_gate.step_physical_gate(
                    {"enable": True, "expected_toggles_per_sec": 4.0}, 5, td)
                out["physical_gate"] = (
                    mp.call_args_list[0][0][0], len(calls))
            # verify.step_flash
            calls = []
            rel = os.path.join("build", "app.hex")
            os.makedirs(os.path.join(td, "build"), exist_ok=True)
            open(os.path.join(td, rel), "w").close()
            with mock.patch.object(verify, "resolve_openocd_cfg",
                                   self._wrap(calls)), \
                 mock.patch.object(verify, "WORKSPACE", td), \
                 mock.patch.object(verify, "_openocd_exe",
                                   return_value=FAKE_EXE), \
                 mock.patch.object(verify, "run_cmd",
                                   return_value={"status": "ok",
                                                 "returncode": 0,
                                                 "stdout": openocd_run.ACTION_DONE_MARKER + "\n",
                                                 "stderr": ""}) as mp:
                verify.step_flash(rel, None)
                out["verify.step_flash"] = (
                    mp.call_args[0][0], len(calls))
        return out

    def test_all_seven_sites_call_resolver_and_keep_default_argv(self):
        results = self._run_all_sites()
        self.assertEqual(len(results), 7)
        for site, (cmd, n_calls) in results.items():
            with self.subTest(site=site):
                self.assertGreaterEqual(n_calls, 1,
                                        f"{site} 未经过解析器")
                self.assertEqual(_cfg_pair(cmd), DEFAULT_PAIR, site)

    def test_reset_target_default_constant_removed(self):
        """_RESET_CFG_DEFAULT 硬编码对已删除 — 单一事实源落成。"""
        self.assertFalse(hasattr(openocd_runtime, "_RESET_CFG_DEFAULT"))

    def test_reset_target_invalid_cfg_reports_error(self):
        """非法配置 → reset_target 返回显式 error (F-103 不静默回落)。"""
        with mock.patch.object(openocd_runtime, "resolve_openocd_cfg",
                               side_effect=runtime_common.OpenocdCfgError("bad cfg")):
            r = openocd_runtime.reset_target(FAKE_EXE)
        self.assertEqual(r["status"], "error")
        self.assertIn("bad cfg", r["message"])
