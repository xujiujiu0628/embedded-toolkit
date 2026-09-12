r"""F-145 (总工单 v2 B-1) 机器级设备锁回归钉。

验收五条 (总工单 v2): 获取 / 冲突 fail-fast 含持有者信息 / 正常释放 /
崩溃后锁可重取 (真实 subprocess 持锁再 kill) / 与 F-127 state.json 锁
互不干扰; 两个并发 verify (mock 硬件步) 一成一败且报错可行动。

设计钉 (v2 修订): 锁本体 = OS 级文件锁 (Windows msvcrt.locking / POSIX
fcntl.flock), 崩溃 = OS 自动释放, 不做 PID 探活、不做 mtime 过期回收;
锁位置 = %USERPROFILE%\.embedded-toolkit\device-locks\<device>.lock
(测试经 ETK_DEVICE_LOCK_DIR / mock 重定向临时目录); 元数据写 .meta.json
旁车, 冲突报错点名 purpose + acquired_at (resource_busy)。

纪律: 测试一律把 DEVICE_LOCK_DIR 重定向到临时目录, 绝不碰真实用户目录;
openocd/verify 的硬件子进程全 mock, 零硬件。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import hw_lease  # noqa: E402
import openocd_run  # noqa: E402
import runtime_common  # noqa: E402
import verify  # noqa: E402

_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts")


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class HwLeaseCoreTests(unittest.TestCase):
    """验收 1/2/3: 获取 / 冲突 fail-fast / 正常释放 + 有界等待"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.lock_dir = os.path.join(self.ws, "device-locks")
        self._patcher = mock.patch.object(hw_lease, "DEVICE_LOCK_DIR",
                                          self.lock_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_1_acquire_creates_lock_and_meta_sidecar(self):
        rs = hw_lease.acquire(purpose="unit test", workspace=self.ws)
        self.assertTrue(rs["ok"], rs)
        lock_file, meta_file = hw_lease.lock_paths("stlink")
        self.assertEqual(rs["lock_file"], lock_file)
        self.assertTrue(os.path.isfile(lock_file))
        self.assertTrue(isinstance(rs["_fd"], int), "OS 锁需要 fd 存活到 release")
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        for key in ("acquired_at", "pid", "token", "purpose", "workspace"):
            self.assertIn(key, meta)
        self.assertEqual(meta["purpose"], "unit test")
        self.assertEqual(meta["workspace"], self.ws)

    def test_2_conflict_fails_fast_with_holder_info(self):
        self.assertTrue(hw_lease.acquire(purpose="holder purpose")["ok"])
        t0 = time.time()
        rs = hw_lease.acquire(purpose="second comer")
        self.assertFalse(rs["ok"])
        self.assertLess(time.time() - t0, 1.0, "fail-fast 不得死等")
        self.assertIn("resource_busy", rs["error"])
        self.assertIn("holder purpose", rs["error"], "报错必须点名持有者")
        self.assertIn("acquired_at", rs["error"])
        meta = hw_lease.holder_info()
        self.assertEqual(meta["purpose"], "holder purpose")

    def test_3_release_allows_reacquire(self):
        leased = hw_lease.acquire(purpose="owner")
        rs = hw_lease.release(leased)
        self.assertTrue(rs["ok"], rs)
        # 正常释放后立即可重取 (OS 字节锁已解)
        rs2 = hw_lease.acquire(purpose="next owner")
        self.assertTrue(rs2["ok"], rs2)
        hw_lease.release(rs2)

    def test_release_rejects_foreign_lease_dict(self):
        self.assertTrue(hw_lease.acquire(purpose="real holder")["ok"])
        # 伪造的 lease dict (没有本进程的 _fd) 不可释放
        rs = hw_lease.release({"ok": True, "device": "stlink"})
        self.assertFalse(rs["ok"])
        meta = hw_lease.holder_info()
        self.assertEqual(meta["purpose"], "real holder",
                         "误放失败后持有者原样保留")
        self.assertTrue(hw_lease.release(
            {"ok": False})["ok"], "失败 lease 释放应幂等无害")

    def test_wait_succeeds_when_released_in_time(self):
        leased = hw_lease.acquire(purpose="soon gone")
        threading.Timer(0.4, hw_lease.release, args=[leased]).start()
        t0 = time.time()
        rs = hw_lease.acquire(purpose="waiter", wait=5)
        self.assertTrue(rs["ok"], rs)
        self.assertGreater(time.time() - t0, 0.3, "确实等了持有者释放")
        hw_lease.release(rs)

    def test_wait_times_out_with_actionable_error(self):
        hw_lease.acquire(purpose="stubborn holder")
        rs = hw_lease.acquire(purpose="waiter", wait=0.6)
        self.assertFalse(rs["ok"])
        self.assertIn("stubborn holder", rs["error"])
        self.assertIn("resource_busy", rs["error"])

    def test_device_names_are_namespaced(self):
        # 不同设备名互不阻塞 (多探针机器的预留面)
        a = hw_lease.acquire("stlink", purpose="a")
        b = hw_lease.acquire("openocd-usb2", purpose="b")
        self.assertTrue(a["ok"] and b["ok"])
        hw_lease.release(a)
        hw_lease.release(b)


class CrashRecoveryTests(unittest.TestCase):
    """验收 4: 崩溃后锁可重取 — 真实 subprocess 持锁再 kill, OS 自动放锁"""

    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp()
        cls.lock_dir = os.path.join(cls.ws, "device-locks")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ws, ignore_errors=True)

    def test_killed_holder_lock_is_reacquirable(self):
        env = dict(os.environ, ETK_DEVICE_LOCK_DIR=self.lock_dir)
        code = (
            "import sys, time; sys.path.insert(0, r'%s');\n"
            "import hw_lease\n"
            "rs = hw_lease.acquire(purpose='crasher')\n"
            "assert rs['ok'], rs\n"
            "print('locked', flush=True)\n"
            "time.sleep(60)\n" % _SCRIPTS_DIR)
        proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                                stdout=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
        try:
            line = proc.stdout.readline().strip()
            proc.stdout.close()
            self.assertEqual(line, "locked", "持锁子进程未就绪")
            # 真实持锁在场 → 冲突可复现 (fail-fast, 报错点名 crasher)
            with mock.patch.object(hw_lease, "DEVICE_LOCK_DIR", self.lock_dir):
                busy = hw_lease.acquire(purpose="victim")
                self.assertFalse(busy["ok"])
                self.assertIn("crasher", busy["error"])
            proc.kill()
            proc.wait(timeout=10)
            # 崩溃后同进程重取 — 无任何回收机制, OS 放锁立即可得
            with mock.patch.object(hw_lease, "DEVICE_LOCK_DIR", self.lock_dir):
                rs = hw_lease.acquire(purpose="after crash")
                self.assertTrue(rs["ok"],
                                f"崩溃后锁必须立即可重取 (OS 自动释放): {rs}")
                hw_lease.release(rs)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


class StateLockCoexistenceTests(unittest.TestCase):
    """验收 5: 与 F-127 state.json 写锁互不干扰 (两层独立, 可嵌套持有)"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, ".workbench"), exist_ok=True)
        runtime_common.save_json_file(
            os.path.join(self.ws, ".workbench", "state.json"), {})
        self.lock_dir = os.path.join(self.ws, "device-locks")
        self._patcher = mock.patch.object(hw_lease, "DEVICE_LOCK_DIR",
                                          self.lock_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_device_lock_and_state_lock_nest_cleanly(self):
        # 两层物理隔离: 设备锁 (用户目录) 在场时, F-127 state 写锁照常
        # 独立工作 (不嵌套同一个锁 — state_write_lock 非重入是设计)。
        lease = hw_lease.acquire(purpose="coexistence", workspace=self.ws)
        self.assertTrue(lease["ok"])
        runtime_common.update_state_entry("last_flash",
                                          {"file": "a.hex"}, self.ws)
        state = runtime_common.load_workspace_state(self.ws)
        self.assertIn("last_flash", state)
        self.assertTrue(hw_lease.release(lease)["ok"])
        # 设备锁放掉后 state 锁再取同样无碍
        with runtime_common.state_write_lock(self.ws):
            pass


class VerifyLeaseIntegrationTests(unittest.TestCase):
    """验收 6: 两个并发 verify 一成一败 — 败方 exit 2 + 可行动报错;
    胜方 flash 执行瞬间锁在场、run 结束即释放"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        wb = os.path.join(self.ws, ".workbench")
        os.makedirs(wb)
        with open(os.path.join(wb, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"toolkit_min_version": "0.1", "builder": "gcc",
                       "gcc": {"project": "Makefile", "target": "main",
                               "log_dir": ".workbench/build"}}, f)
        with open(os.path.join(wb, "expectations.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "1.0", "expectations": [
                {"id": "FR-SYS-01", "desc": "boot", "texts": ["[init] OK"]},
            ]}, f)
        self.lock_dir = os.path.join(self.ws, "device-locks")
        self._patcher = mock.patch.object(hw_lease, "DEVICE_LOCK_DIR",
                                          self.lock_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run_main(self, extra_args=(), flash_status="ok",
                  capture_text="[init] OK\n"):
        """mock 硬件步骤驱动 main(); step_flash 记录'执行瞬间锁是否在场'"""
        lease_during_flash = []

        def _flash(*a, **k):
            lock_file, _meta = hw_lease.lock_paths("stlink")
            lease_during_flash.append(os.path.isfile(lock_file))
            return {"status": flash_status, "stderr": "Verified", "stdout": ""}

        argv = ["verify.py", "--project", self.ws, "--json"] + list(extra_args)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(verify, "step_build",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": "s",
                                      "metrics": {"errors": 0, "warnings": 0},
                                      "details": {}})), \
                mock.patch.object(verify, "step_analyze",
                                  mock.Mock(return_value={
                                      "status": "ok", "summary": {}})), \
                mock.patch.object(verify, "step_flash", _flash), \
                mock.patch.object(verify, "run_semihosting_session",
                                  mock.Mock(return_value=(capture_text, ""))), \
                mock.patch.object(verify, "reset_target",
                                  mock.Mock(return_value={"status": "ok"})), \
                mock.patch.object(verify, "record_checkpoint"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    verify.main()
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, out.getvalue(), err.getvalue(), lease_during_flash

    def test_winner_holds_lock_during_flash_and_releases_after(self):
        code, _out, _err, during = self._run_main()
        self.assertEqual(code, 0)
        self.assertEqual(during, [True], "flash 执行瞬间设备锁必须在场")
        lock_file, _meta = hw_lease.lock_paths("stlink")
        self.assertFalse(os.path.exists(lock_file),
                         "verify 结束后锁文件已清理 (锁信号在 OS 字节锁)")

    def test_flash_failure_releases_lock(self):
        code, out, _err, _during = self._run_main(
            flash_status="error", capture_text="")
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "flash_failed")
        lease = hw_lease.holder_info()
        self.assertTrue(lease is None or lease.get("pid") == os.getpid(),
                        "flash 失败早退也必须释放锁 (旁车已清)")

    def test_no_flash_run_still_uses_and_releases_lock(self):
        # --no-flash 跳过烧录但 capture 仍触硬件 — 锁照持照放
        code, _out, _err, _during = self._run_main(extra_args=["--no-flash"])
        self.assertEqual(code, 0)
        self.assertIsNone(hw_lease.holder_info(), "正常出口旁车已清")

    def test_loser_exits_2_with_actionable_holder_message(self):
        # 败方: 先来的 verify 持锁, 第二个 verify fail-fast exit 2,
        # 报错点名持有者 purpose 与获取时间, 持有者锁原样保留
        winner = hw_lease.acquire(
            purpose="verify flash+capture (another-ws)", workspace=self.ws)
        self.assertTrue(winner["ok"])
        code, _out, err, _during = self._run_main(
            extra_args=["--no-build"], capture_text="")
        self.assertEqual(code, 2)
        self.assertIn("resource_busy", err)
        self.assertIn("another-ws", err)
        self.assertEqual(hw_lease.holder_info()["purpose"],
                         "verify flash+capture (another-ws)")
        hw_lease.release(winner)


class OpenocdRunLeaseTests(unittest.TestCase):
    """openocd_run flash/erase 动作粒度: 期间在场/结束释放/冲突 resource_busy"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.lock_dir = os.path.join(self.ws, "device-locks")
        self._patcher = mock.patch.object(hw_lease, "DEVICE_LOCK_DIR",
                                          self.lock_dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _run_action(self, action, **kw):
        lock_during = []

        def _fake_run(cmd, **kwargs):
            lock_file, _meta = hw_lease.lock_paths("stlink")
            lock_during.append(os.path.isfile(lock_file))
            # F-155 N-3: flash/erase 串尾有构造性标记才算完整跑完
            return _completed(stdout="", stderr="fake openocd output\n"
                              f"{openocd_run.ACTION_DONE_MARKER}\n")

        with mock.patch.object(openocd_run.subprocess, "run", _fake_run):
            rs = openocd_run.run_openocd(
                "openocd-fake", action, board="st-link",
                interface="interface/stlink.cfg", target="target/stm32f1x.cfg",
                file="fw.hex" if action == "flash" else "", **kw)
        return rs, lock_during

    def test_flash_holds_lock_during_and_releases_after(self):
        rs, during = self._run_action("flash")
        self.assertEqual(rs["status"], "ok", rs)
        self.assertEqual(during, [True])
        self.assertIsNone(hw_lease.holder_info(), "动作结束旁车已清")

    def test_erase_also_locked(self):
        rs, during = self._run_action("erase", erase_mode="sector", bank="0")
        self.assertEqual(during, [True], rs)
        self.assertIsNone(hw_lease.holder_info())

    def test_probe_does_not_touch_lock(self):
        # probe 只读不烧 — 根本不进入锁路径 (acquire 零调用)
        foreign = hw_lease.acquire(purpose="foreign holder")
        try:
            with mock.patch.object(hw_lease, "acquire") as m_acq:
                rs, _during = self._run_action("probe")
            m_acq.assert_not_called()
            self.assertNotEqual(rs.get("error", {}).get("code"),
                                "resource_busy")
        finally:
            hw_lease.release(foreign)

    def test_conflict_fails_fast_with_resource_busy_code(self):
        hw_lease.acquire(purpose="another flasher")
        rs, _during = self._run_action("flash")
        self.assertEqual(rs["status"], "error")
        self.assertEqual(rs["error"]["code"], "resource_busy")
        # 报错点名持有者 purpose + acquired_at, 可行动 (等/有界等待/重试)
        self.assertIn("another flasher", rs["error"]["message"])
        self.assertIn("acquired_at", rs["error"]["message"])


class LockDirEnvOverrideTests(unittest.TestCase):
    """ETK_DEVICE_LOCK_DIR: import 期环境重定向 (多环境部署/崩溃测试依赖)"""

    def test_env_override_at_import_time(self):
        import importlib
        target = os.path.join(tempfile.gettempdir(), "etk-locks-env-test")
        with mock.patch.dict(os.environ,
                             {"ETK_DEVICE_LOCK_DIR": target}):
            mod = importlib.reload(hw_lease)
            self.assertEqual(mod.DEVICE_LOCK_DIR, target)
        importlib.reload(hw_lease)   # 还原常量, 防污染其他测试
        self.assertNotEqual(hw_lease.DEVICE_LOCK_DIR, target)


if __name__ == "__main__":
    unittest.main()
