r"""serial_mux 生命周期回归钉 (F-097, WB-A / 审计 P1-3)。

缺陷: start_mux 的 wait_for_tcp_server 失败分支直接 return, 不 terminate
已启动的 p1 (serve 进程) → 孤儿进程独占真实串口且无台账; _serial_read_loop
异常静默 set stop_event → serve 死因零留痕 (父进程早已返回成功)。

修复后契约:
  1. 服务起不来 → p1 被 terminate (无孤儿)
  2. 读循环死亡 → stderr 留痕 + %TEMP%/serial_mux/serve_<port>.failed 现场
  3. 异常路径统一回收 _mux_procs

测试不依赖真串口/socat: p1 用**解释器自身的长睡进程**做占位 (不起 TCP、
也不 open serial), 故零外部命令依赖。

F-182 (WB-20260921-03 / GAP-ENV-3): 旧版在用例开头按
`shutil.which("sleep")` 守卫, PATH 无 coreutils 时整例**静默 skip** ——
"全绿"口径随 PATH 在 skipped 7↔6 间漂移而不自知。占位进程既已由解释器
自身承担 (与外部 `sleep` 无关), 该守卫已无存在理由, **删除**;
skip 数自此与 PATH 无关 (收单口径: 全量 skipped 恒 6)。

F-183 (WB-20260921-04 / T3, GAP-F-9): 本文件的打桩曾用
`mock.patch.object(serial_mux.subprocess, "Popen", …)` 与
`mock.patch.object(serial_mux.shutil, "which", …)` —— 而 `serial_mux.subprocess`
/ `serial_mux.shutil` **就是全局模块对象**, 等于改全局 `subprocess.Popen` /
`shutil.which`: 打桩窗口内一切第三方 spawn / which 都被 fake 吞走
(GAP-ENV-1 同族; F-182 §三已实证占位进程会递归调回 fake → RecursionError →
被 start_mux 的 `except Exception` 吞成 start_failed)。现按 F-182 T1 样板
收窄为**模块引用替换** (`_patch_serial_mux_subprocess` /
`_patch_serial_mux_shutil_which`, stub 属性显式列全、fail-closed), 并补
`StubIsolationTests` 隔离自证钉 (窗口内真 spawn 第三方进程 + 捕获序列隔离)。
打桩收窄后全局 `subprocess.Popen` 不再被替换, 故 F-182 那个 import 期抢抓
真实句柄的 `_REAL_POPEN` **已移除** (由自证钉兜底 —— 若有人把桩改回全局,
自证钉立即红)。既有 mux 生命周期断言语义**零变**。
"""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_mux  # noqa: E402

# F-182: 占位进程用解释器自身长睡 —— 零外部命令依赖 (旧版依赖外部 `sleep`)
_PLACEHOLDER_CODE = "import time; time.sleep(60)"

# F-184 (GAP-F-10): import 期捕获**真实** `os._exit` —— 只作隔离自证钉的
# **身份判等期望值**。⚠ 严禁真调 `os._exit` 做探针 (会把测试进程当场杀掉);
# 本文件的自证钉全程只用引用判等, 零 exit 调用。
_REAL_OS_EXIT = os._exit


def _patch_serial_mux_subprocess(fake_popen):
    """把打桩面收窄到 `serial_mux` 模块内的 subprocess **引用** (F-183 T3)。

    只换 `serial_mux` 自己的属性: `serial_mux` 内对 subprocess 的调用被换掉,
    全局 `subprocess.Popen` 原样可跑。stub 显式带上 `serial_mux` 实际消费的
    全部 subprocess 属性 (现场核实 `scripts/serial_mux.py`):

      · `Popen`          —— :318 / :337 起 serve / mux 子进程
      · `DEVNULL`        —— :318-319 / :337-338 的 stdout/stderr 目标
      · `TimeoutExpired` —— :328 `except` 子句求值

    属性集是**收窄**的 → fail-closed: 若 `serial_mux` 将来消费别的 subprocess
    属性, 测试会直接 `AttributeError` 报出来, 而不是静默放行。
    """
    stub = types.SimpleNamespace(
        Popen=fake_popen,
        DEVNULL=subprocess.DEVNULL,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    return mock.patch.object(serial_mux, "subprocess", stub)


def _patch_serial_mux_shutil_which(fake_which):
    """同上: 只换 `serial_mux` 的 shutil 引用。

    `serial_mux` 仅消费 `shutil.which` (:242 `shutil.which("socat")`),
    故 stub 只给该一个属性 (同样 fail-closed)。
    """
    return mock.patch.object(serial_mux, "shutil",
                             types.SimpleNamespace(which=fake_which))


def _patch_serial_mux_os(fake_exit):
    """打桩入口: `serial_mux` 的 os 引用 (F-184 / GAP-F-10)。

    **阶段一 (钉, 本笔) 的体仍是旧写法**: `serial_mux.os` **就是全局 `os`
    模块对象**, 故 `mock.patch.object(serial_mux.os, "_exit", …)` 等于把
    **全局** `os._exit` 换掉 —— 打桩窗口内任何第三方 `os._exit` 都会被 fake
    吞走 (GAP-F-9 同族残余, 本单 GAP-F-10)。

    本笔只把打桩入口从用例内行内调用**收敛到这一个 helper** (行为等价), 使
    阶段二的收窄成为**一处 diff**; `StubIsolationTests` 的
    `test_module_os_stub_does_not_hijack_global_exit` 此刻**必红**。

    阶段二 (修) 把体换成**模块引用替换** —— `mock.patch.object(serial_mux,
    "os", SimpleNamespace(…))`, 属性显式列全、fail-closed。
    """
    return mock.patch.object(serial_mux.os, "_exit", fake_exit)


def _spawn_placeholder(**kw):
    # F-183 T3: 打桩已收窄到 serial_mux 的模块引用 —— 全局 subprocess.Popen
    # 不再被替换, 故无需 import 期抢抓真实句柄 (F-182 的 `_REAL_POPEN` 已移除;
    # 若桩被改回全局, StubIsolationTests 立即红)。
    return subprocess.Popen([sys.executable, "-c", _PLACEHOLDER_CODE], **kw)


def _reap(proc):
    """收尾: terminate → 超时兜底 kill, 不留孤儿 (F-182 §4.7)。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class MuxStartNoLeakTests(unittest.TestCase):
    """修复钉 1: 服务起不来时 p1 必须被回收"""

    def test_failed_start_terminates_p1(self):
        # 假 serve: 起一个长睡进程 → wait_for_tcp_server 被 monkeypatch 成
        # False (poll 恒 None → 超时 False), 模拟"进程起了但服务没起"的窗口。
        # F-182: 占位进程由解释器自身承担, 无外部 `sleep` 依赖, 无 skip 守卫。
        # F-183: 打桩面收窄到 serial_mux 的模块引用 (原为全局劫持)。
        calls = {}

        def fake_popen(cmd, **kw):
            p = _spawn_placeholder(**kw)
            self.addCleanup(_reap, p)
            calls["p1"] = p
            return p

        def fake_wait(port, proc, timeout=2.0):
            return False   # 模拟服务起不来

        with _patch_serial_mux_subprocess(fake_popen), \
             mock.patch.object(serial_mux, "wait_for_tcp_server", fake_wait), \
             _patch_serial_mux_shutil_which(lambda x: "/usr/bin/socat"):
            out = serial_mux.start_mux(port="COMX", baudrate=115200,
                                       workspace=None,
                                       vserial_link="/tmp/nonexistent_link")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"]["code"], "port_open_failed")
        # 核心断言: p1 必须已被 terminate (旧版漏报点)
        self.assertIn("p1", calls)
        self.assertIsNotNone(calls["p1"].poll(),
                             "p1 应在失败分支被 terminate (旧版泄漏)")


class ReadLoopDeathTraceTests(unittest.TestCase):
    """修复钉 2: 读循环死亡必须留痕 + 非零退出。
    F-159: 端口 29876/29877 硬编码 → 动态空闲口; 全局 tempdir 死亡标记
    setUp 先清 (跨运行残留会假绿/假红)。"""

    def setUp(self):
        self.tcp_port = serial_mux.find_free_port()
        self.marker = os.path.join(tempfile.gettempdir(), "serial_mux",
                                   f"serve_{self.tcp_port}.failed")
        if os.path.exists(self.marker):
            os.remove(self.marker)
        self.addCleanup(lambda: os.path.exists(self.marker)
                        and os.remove(self.marker))

    def _server(self):
        return serial_mux.SerialMuxServer(
            {"port": "X", "baudrate": 115200, "bytesize": 8,
             "parity": "none", "stopbits": 1}, tcp_port=self.tcp_port)

    def test_read_loop_death_writes_failure_marker(self):
        server = self._server()
        # 伪造 serial_port: read 抛异常 → 读循环死亡
        class _Boom:
            in_waiting = 0
            def read(self, n):
                raise RuntimeError("device disconnected")
        server.serial_port = _Boom()
        server.server_sock = mock.Mock()

        # serve 子进程内 run() 的主循环逻辑: 读循环死亡 → stop_event + os._exit(1)
        # 这里直接调 _serial_read_loop 并捕获 os._exit
        # F-184: 打桩入口收敛到唯一 helper `_patch_serial_mux_os` (阶段一/二同式);
        # 账目面改用**显式 mock 变量** —— 旧体的 helper 返回 Mock、收窄后返回
        # SimpleNamespace stub, `as` 绑定值会随之变形态, 故断言面不依赖返回值。
        exit_mock = mock.Mock(side_effect=SystemExit(1),
                              name="serial_mux.os._exit")
        with _patch_serial_mux_os(exit_mock):
            with self.assertRaises(SystemExit):
                server._serial_read_loop()
        self.assertEqual(exit_mock.call_args[0][0], 1,
                         "读循环死亡必须非零退出 (旧版静默 break)")
        self.assertTrue(os.path.exists(self.marker),
                        f"死亡现场未落盘: {self.marker}")
        content = open(self.marker, encoding="utf-8").read()
        self.assertIn("device disconnected", content)

    def test_normal_stop_does_not_exit_1(self):
        """stop_event 置位 (正常关闭) 不触发死亡路径"""
        server = self._server()
        class _Quiet:
            in_waiting = 0
            def read(self, n):
                time.sleep(0.05)
                return b""
        server.serial_port = _Quiet()
        server.server_sock = mock.Mock()
        server.stop_event.set()   # 先置位 → 循环应直接退出, 不走死亡分支
        server._serial_read_loop()   # 不应 os._exit
        self.assertFalse(os.path.exists(self.marker))


class StubIsolationTests(unittest.TestCase):
    """F-183 T3 (GAP-F-9) 打桩卫生自证钉 —— 照 F-182 T1 样板。

    收窄后的桩必须只作用在 `serial_mux` 的模块引用上, **不得**劫持全局
    `subprocess.Popen` / `shutil.which`; 否则打桩窗口内任何第三方 spawn /
    which 都被 fake 吞走 (F-182 §三实证: 占位进程递归调回 fake →
    RecursionError → 被 start_mux 的 `except Exception` 吞成 start_failed)。

    本类不依赖外部环境事实 (safe-delete shim 是否在场等), 而是**在打桩窗口内
    主动真跑一次第三方调用**, 用可观测证据判定是否被劫持:

      · A1/A2/A3 断言第三方进程**真实执行** —— 探针走**调用时**的全局
        `subprocess.Popen` 查表 (不用 import 期句柄: 用句柄会把劫持藏起来,
        本单阶段一实测该写法假绿); 桩只会抛 AssertionError、不可能产出
        rc/stdout, 故 A1 无异常 + A2 rc==0 + A3 stdout=="PROBE" 三者同时
        成立 = 全局查表未被替换;
      · B 断言桩的**捕获序列不含**该第三方 argv (劫持的直接证据)。

    F-184 (GAP-F-10) 同法加固 `serial_mux.os`: 但 `os._exit` **不可真调**
    (会当场杀掉测试进程), 故该钉改用**身份断言法** —— 见
    `test_module_os_stub_does_not_hijack_global_exit`。
    """

    def test_module_subprocess_stub_does_not_hijack_global_popen(self):
        captured = []

        def fake_popen(cmd, **kw):
            captured.append(list(cmd))
            raise AssertionError("serial_mux.subprocess 桩被非目标调用命中")

        probe_argv = [sys.executable, "-c",
                      "import sys; sys.stdout.write('PROBE')"]
        proc = None
        stdout = b""
        err = None
        try:
            with _patch_serial_mux_subprocess(fake_popen):
                proc = subprocess.Popen(probe_argv, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
                stdout, _stderr = proc.communicate(timeout=30)
        except Exception as e:      # 桩被命中 / 真 spawn 失败 皆为证据
            err = e

        with self.subTest(check="A1 第三方真 spawn"):
            self.assertIsNone(err, f"打桩窗口内第三方 spawn 失败/被桩吞: {err!r}")
        with self.subTest(check="A2 rc==0"):
            self.assertIsNotNone(proc, "第三方进程未创建")
            self.assertEqual(proc.returncode, 0)
        with self.subTest(check="A3 stdout 真实"):
            self.assertEqual(stdout, b"PROBE",
                             "第三方进程未真实执行 (stdout 不符)")
        with self.subTest(check="B 捕获序列隔离"):
            self.assertNotIn(probe_argv, captured,
                             f"桩捕获了非目标调用 (全局劫持证据): {captured}")

    def test_module_shutil_stub_does_not_hijack_global_which(self):
        def fake_which(name):
            raise AssertionError("serial_mux.shutil.which 桩被非目标调用命中")

        got = None
        err = None
        try:
            with _patch_serial_mux_shutil_which(fake_which):
                got = shutil.which(sys.executable)
        except Exception as e:
            err = e

        with self.subTest(check="A 第三方 which 真执行"):
            self.assertIsNone(err, f"全局 shutil.which 被桩吞走: {err!r}")
        with self.subTest(check="B 命中真实路径"):
            self.assertEqual(
                os.path.normcase(got or ""), os.path.normcase(sys.executable),
                f"第三方 shutil.which 结果不符: {got!r}")


    def test_module_os_stub_does_not_hijack_global_exit(self):
        """F-184 (GAP-F-10) 隔离自证钉 —— **身份断言法, 零真实 `os._exit` 调用**。

        ⚠ 安全红线: 本钉**不得**真调 `os._exit` 做探针（会把测试进程当场杀掉),
        故不照搬 subprocess 钉那种"窗口内真跑一次第三方调用 + 看 fake 账目"的
        写法, 改用**身份判等**:

          · A1 全局面: 窗口内 `os._exit`（**调用时**全局查表）必须仍是 import 期
            捕获的真实函数 `_REAL_OS_EXIT`;
          · A2 第三方视角: 第三方代码自己 `import os` 后调用时解析, 拿到的也必须
            是真实函数（走**独立的模块解析路径** `importlib.import_module("os")`,
            独立于本测试模块的 `os` 绑定 —— 排除"只改本模块绑定"式的假绿);
          · B1 桩的落点: 桩只挂在 `serial_mux.os` 上, 全局 `os` 里**查不到**它
            （收窄的直接证据);
          · B2 零副作用: 本钉全程 `fake.call_count == 0`（既证明未真调 exit, 也
            证明上述探针没有误入桩)。

        判据极性: 修前（桩改全局）A1/A2/B1 **必红**, 收窄后全绿。
        """
        def fake_exit(code):    # 若真被调用, 立刻以异常暴露而非静默通过
            raise AssertionError("serial_mux.os._exit 桩被调用 (本钉不应触发)")

        def _third_party_resolve_exit():
            # 第三方代码的典型形态: 自己 import 拿模块对象, 调用时再解析属性。
            # **只取引用做判等, 不调用它** —— 真调会杀掉本进程。
            return importlib.import_module("os")._exit

        fake = mock.Mock(side_effect=fake_exit, name="serial_mux.os._exit")
        with _patch_serial_mux_os(fake):
            with self.subTest(check="A1 全局 os._exit 身份未变"):
                self.assertIs(os._exit, _REAL_OS_EXIT,
                              "打桩窗口内全局 os._exit 被替换 (劫持)")
            with self.subTest(check="A2 第三方调用时查表得真实函数"):
                self.assertIs(_third_party_resolve_exit(), _REAL_OS_EXIT,
                              "第三方视角解析被劫持")
            with self.subTest(check="B1 桩只在 serial_mux 引用上"):
                self.assertIs(serial_mux.os._exit, fake)
                self.assertIsNot(os._exit, fake,
                                 "全局 os 里查得到桩 (未收窄)")
            with self.subTest(check="B2 零副作用"):
                self.assertEqual(fake.call_count, 0,
                                 "本钉不应有任何真实 exit 调用")


if __name__ == "__main__":
    unittest.main()
