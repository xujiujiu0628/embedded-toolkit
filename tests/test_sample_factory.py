r"""样例工厂巡检测试 (WB-20260919-04) — 自动遍历 examples/f103-*/。

对每个样例目录生成一个用例: `make all` 必须 rc=0 且产出 ELF+HEX;
目录含哨兵文件 `MOCK` 时追加一个 `make test` 子用例 (host gcc 编译
纯逻辑断言, 断言全过 exit 0)。

工具解析链 (与仓内 machine.json 单一来源纪律一致):
  make       = machine.json make_exe (在盘校验) > PATH 上的 make/mingw32-make
  arm-gcc    = machine.json gcc_path > PATH (不在场时整组 skip — 同
               test_gen_syntax_smoke 的 CI 守卫: CI ubuntu 不装工具链)
  host gcc   = PATH 上的 gcc/cc/clang > msys64 常见安装位 (mock 子用例
               解析不到时 skipTest, 不算失败)
make 的同目录会 prepend 进子进程 PATH — Makefile 配方沿用 sim-demo
母本的 unix 风格 (mkdir -p / rm -rf), 工具定位统一收口在测试侧。

用例数 == 样例目录数 (+含 MOCK 哨兵的目录数) — 简报 §3① 的数量契约。
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import wb_common  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")
MAKE_TIMEOUT = 120


def _machine_tool(key, exe_name):
    """machine.json 登记路径 (在盘校验) → None, 交由调用方走 PATH 兜底。"""
    try:
        value = (wb_common.load_machine().get(key) or "").strip()
    except Exception:
        return None
    if not value:
        return None
    cand = os.path.join(value, exe_name) if os.path.isdir(value) else value
    return cand if os.path.isfile(cand) else None


def _resolve_make():
    cand = _machine_tool("make_exe", "make.exe" if os.name == "nt" else "make")
    if cand:
        return cand
    return shutil.which("make") or shutil.which("mingw32-make")


def _resolve_arm_gcc():
    cand = _machine_tool("gcc_path",
                         "arm-none-eabi-gcc.exe" if os.name == "nt"
                         else "arm-none-eabi-gcc")
    if cand:
        return cand
    return shutil.which("arm-none-eabi-gcc")


def _resolve_host_gcc():
    for name in ("gcc", "cc", "clang"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":  # msys2 常见安装位 (本机 machine.json 无 host gcc 键)
        for base in (r"C:\msys64\mingw64\bin", r"C:\msys64\ucrt64\bin",
                     r"C:\msys64\clang64\bin", r"C:\msys64\usr\bin"):
            cand = os.path.join(base, "gcc.exe")
            if os.path.isfile(cand):
                return cand
    return None


def _sample_dirs():
    if not os.path.isdir(EXAMPLES):
        return {}
    return {d: os.path.join(EXAMPLES, d)
            for d in sorted(os.listdir(EXAMPLES))
            if d.startswith("f103-") and d != "f103-common"
            and os.path.isdir(os.path.join(EXAMPLES, d))}


class SampleFactoryTests(unittest.TestCase):
    """每样例一用例 (make all → rc=0 + ELF/HEX); MOCK 哨兵追加 make test。"""
    maxDiff = None

    def _run_make(self, sample_dir, *args, **kw):
        env = dict(os.environ)
        make_dir = os.path.dirname(MAKE)
        if make_dir:
            env["PATH"] = make_dir + os.pathsep + env.get("PATH", "")
        cmd = [MAKE, *args]
        if kw.get("host_gcc"):
            cmd.append(f"CC_HOST={kw['host_gcc']}")
        return subprocess.run(
            cmd, cwd=sample_dir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=MAKE_TIMEOUT, env=env)


MAKE = _resolve_make()
ARM_GCC = _resolve_arm_gcc()
HOST_GCC = _resolve_host_gcc()
_SAMPLES = _sample_dirs()
_SKIP_REASON = None
if MAKE is None:
    _SKIP_REASON = "make 不在场 (machine.json make_exe 与 PATH 均未命中)"
elif ARM_GCC is None:
    _SKIP_REASON = "arm-none-eabi-gcc 不在场 (CI 默认不装工具链)"


def _make_all_test(name, sample_dir):
    def test(self):
        r = self._run_make(sample_dir, "all")
        self.assertEqual(
            r.returncode, 0,
            f"{name}: make all 失败\n--- stdout ---\n{r.stdout[-2000:]}"
            f"\n--- stderr ---\n{r.stderr[-2000:]}")
        elf = os.path.join(sample_dir, "build", name + ".elf")
        hexfile = os.path.join(sample_dir, "build", name + ".hex")
        self.assertTrue(os.path.isfile(elf), f"{name}: ELF 未产出: {elf}")
        self.assertTrue(os.path.isfile(hexfile), f"{name}: HEX 未产出: {hexfile}")
    return test


def _make_mock_test(name, sample_dir):
    def test(self):
        if HOST_GCC is None:
            self.skipTest("host gcc 不在场 — mock 测试无法编译")
        r = self._run_make(sample_dir, "test", host_gcc=HOST_GCC)
        self.assertEqual(
            r.returncode, 0,
            f"{name}: make test 失败 (host mock 断言未过?)\n"
            f"--- stdout ---\n{r.stdout[-2000:]}"
            f"\n--- stderr ---\n{r.stderr[-2000:]}")
    return test


@unittest.skipIf(_SKIP_REASON is not None, "工具链不在场")
class _GeneratedSampleTests(SampleFactoryTests):
    pass


if _SKIP_REASON is None:
    for _name, _dir in _SAMPLES.items():
        setattr(_GeneratedSampleTests, "test_sample_" + _name.replace("-", "_"),
                _make_all_test(_name, _dir))
        if os.path.isfile(os.path.join(_dir, "MOCK")):
            setattr(_GeneratedSampleTests, "test_mock_" + _name.replace("-", "_"),
                    _make_mock_test(_name, _dir))

if __name__ == "__main__":
    unittest.main()
