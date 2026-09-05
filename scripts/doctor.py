r"""环境预检 --doctor (F-058) — verify.py 拆分件（防腐方案 §3.3 步骤 5a）.

打印工具链环境矩阵: toolkit/Python/machine.json 四键/gcc/openocd/make/SWD
连通性/契约 fixture 健康。诊断专用——报告不是门禁, 退出码恒 0; 占位路径
永不执行 (test_doctor 安全钉死)。

自 verify.py 整体搬迁（F-041 引入的原块逐字搬运），仅 import 收归本模块：
load_machine / toolkit_version 来自 wb_common。测试 patch 目标随迁——
load_machine 与 _fixture_main_sha 的 spy 改钉本模块（F-029 先例）；
subprocess.run 为共享模块对象, 原钉不动。
"""
import hashlib
import os
import subprocess
import sys

from openocd_runtime import swd_probe  # noqa: E402  (F-041: doctor 与 G0.5 同源)
from wb_common import (TOOLKIT_ROOT, load_machine,
                       toolkit_version)


# ---------------------------------------------------------------------------
# 环境预检 --doctor (F-041): 打印工具链环境矩阵, 诊断专用。
# 定位: release.py G0.5 "区分环境未备/固件真坏" 之前的自检; 报障随 issue 附
# --doctor --json, 消灭"环境不同"类往返。是报告不是门禁 —— 退出码恒 0,
# 占位路径永不执行 (test_doctor 安全钉死)。

_DOCTOR_KEYS = ("uv4_exe", "openocd_exe", "gcc_path", "make_exe")


def _first_version_line(cmd: list) -> tuple:
    """运行版本命令, 返回 (ok, 首个非空行或错误串)。stdout/stderr 合并取行
    (OpenOCD 版本行打印在 stderr)。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, str(e)
    lines = [ln.strip() for ln in ((r.stdout or "") + (r.stderr or "")).splitlines()
             if ln.strip()]
    return (r.returncode == 0 or bool(lines)), (lines[0] if lines else "")


def _check_tool(machine: dict, key: str, bare: str, version_args: tuple) -> dict:
    """单工具检查。空/占位 → skipped (永不执行占位路径, 安全钉在 test_doctor);
    键为目录 (gcc_path 型) → 目录下找可执行 (Windows 优先 .exe), 找不到 → warn;
    键为文件 → 直接用; 版本命令失败 → warn (诊断报告不判门禁红)。"""
    val = (machine.get(key) or "").strip()
    if not val:
        return {"status": "skipped", "detail": f"{key} 为空"}
    if val.startswith("<"):
        return {"status": "skipped",
                "detail": f"{key} 为占位路径 (复制 machine.example.json 后填写)"}
    if os.path.isdir(val):
        exe = None
        for name in ((bare + ".exe") if os.name == "nt" else bare, bare):
            cand = os.path.join(val, name)
            if os.path.isfile(cand):
                exe = cand
                break
        if exe is None:
            return {"status": "warn",
                    "detail": f"{key} 目录下未找到 {bare}[.exe]: {val}"}
    elif os.path.isfile(val):
        exe = val
    else:
        return {"status": "warn", "detail": f"{key} 指向的路径不存在: {val}"}
    ok, line = _first_version_line([exe, *version_args])
    if not ok:
        return {"status": "warn", "detail": f"版本命令失败: {exe}", "error": line[:200]}
    return {"status": "ok", "detail": exe, "version": line[:120]}


# F-048: fixture 体检 (2026-09-02 方案四-5)
#   - 检查 tests/fixtures/contract/{config,expectations}.json 是否在
#   - 用 sha256 对比本地 vs 仓库默认分支版, 漂移 = warn
#   - 缺失 = fail (没有 fixture, 契约测试就缺锚点)
#   整段离线, 只读 git 仓 (git show <base>:tests/fixtures/contract/<file>)
# 自审 (2026-09-03) 修: 此前硬编码 main 分支, 但本仓默认是 master,
# CI runner fresh clone 上 main 不存在, 静默返空 dict → 误判 ok
def _detect_default_branch() -> str:
    """拿仓默认分支名. 优先 symbolic-ref origin/HEAD, fallback master, main.

    返回: 分支名字符串 (e.g. 'master', 'main', 'unknown')
    """
    try:
        r = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
            encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            # refs/remotes/origin/master → master
            return r.stdout.strip().rsplit("/", 1)[-1]
    except (OSError, subprocess.TimeoutExpired):
        pass
    # fallback: master 先, main 后 (本仓 master 是真默认, main 是老 GitHub 习惯)
    for cand in ("master", "main"):
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{cand}"],
                capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
                encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "unknown"


def _fixture_main_sha(fixture_dir: str) -> dict:
    """读 git 默认分支上的 fixture 文件 sha256, 失败回空 dict.

    用 `git show <base>:<path>` 而非 checkout —— 不污染工作树.
    默认分支通过 _detect_default_branch() 推断, 支持 master/main.
    """
    out = {}
    try:
        rel = os.path.relpath(fixture_dir, TOOLKIT_ROOT).replace(os.sep, "/")
    except ValueError:
        return out
    base = _detect_default_branch()
    if base == "unknown":
        return out   # 无法推断默认分支 → 静默返空, 漂移检测跳过
    for name in ("config.json", "expectations.json"):
        try:
            r = subprocess.run(
                ["git", "show", f"{base}:{rel}/{name}"],
                capture_output=True, cwd=TOOLKIT_ROOT, timeout=5,
                encoding="utf-8", errors="replace")
            if r.returncode == 0 and r.stdout:
                h = hashlib.sha256()
                h.update(r.stdout.encode("utf-8"))
                out[f"{name.replace('.json', '')}_sha256"] = h.hexdigest()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return out


def fixture_health(fixture_dir: str, *, skip_drift_check: bool = False) -> dict:
    """F-048 体检: fixture 在场性 + 漂移检测.

    Args:
        fixture_dir: 工程 fixture 目录 (含 config.json + expectations.json)
        skip_drift_check: True 时跳过 git main 对比 (测试场景: 占位时不应跑子进程)

    Returns:
        {status, config, expectations, drift}
        status ∈ {ok, warn, fail, skipped}
        - fail: 至少一个关键文件缺失
        - warn: 文件在但与 main 漂移
        - ok: 都在且无漂移
        - skipped: 非 git 仓 (无法做漂移检测, 视作"无漂移信号")
    """
    config_p = os.path.join(fixture_dir, "config.json")
    exp_p = os.path.join(fixture_dir, "expectations.json")
    config_s = "ok" if os.path.isfile(config_p) else "missing"
    exp_s = "ok" if os.path.isfile(exp_p) else "missing"

    # 漂移检测: 本地 sha256 vs main sha256
    drift = {"detected": False, "mismatches": []}
    if config_s == "ok" and exp_s == "ok" and not skip_drift_check:
        local = {}
        for name, key in (("config.json", "config_sha256"),
                          ("expectations.json", "expectations_sha256")):
            try:
                with open(os.path.join(fixture_dir, name), "rb") as f:
                    local[key] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                pass
        main_sha = _fixture_main_sha(fixture_dir)
        if main_sha:
            for k in ("config_sha256", "expectations_sha256"):
                if k in local and k in main_sha and local[k] != main_sha[k]:
                    drift["detected"] = True
                    drift["mismatches"].append(k)
    # 状态聚合
    if config_s == "missing" or exp_s == "missing":
        status = "fail"
    elif drift["detected"]:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "config": {"status": config_s, "path": config_p},
        "expectations": {"status": exp_s, "path": exp_p},
        "drift": drift,
    }


def doctor_report(probe: bool = True, *, skip_drift_check: bool = False) -> dict:
    """环境矩阵收集 (F-041)。machine.json 缺失时经 load_machine 回退链取占位值,
    各工具按占位/缺失跳过 —— 本函数永不执行占位路径。probe=True 且 openocd
    在场时做单次 SWD 探测 (attempts=1; 门禁 G0.5 用 3 次重试版)。"""
    machine = load_machine()
    machine_file = os.path.join(TOOLKIT_ROOT, "machine.json")
    example_file = os.path.join(TOOLKIT_ROOT, "machine.example.json")
    if os.path.isfile(machine_file):
        mode = "machine.json"
    elif os.path.isfile(example_file):
        mode = "fallback: machine.example.json (占位值, 真机步骤会明确报错)"
    else:
        mode = "missing"

    keys = {}
    for k in _DOCTOR_KEYS:
        v = (machine.get(k) or "").strip()
        keys[k] = {"value_set": bool(v),
                   "placeholder": v.startswith("<"),
                   "path_exists": os.path.exists(v) if v else None}

    tools = {"gcc": _check_tool(machine, "gcc_path", "arm-none-eabi-gcc", ("--version",)),
             "openocd": _check_tool(machine, "openocd_exe", "openocd", ("--version",)),
             "make": _check_tool(machine, "make_exe", "make", ("--version",))}

    oc = (machine.get("openocd_exe") or "").strip()
    if not oc or oc.startswith("<") or not os.path.isfile(oc):
        swd = {"status": "skipped",
               "detail": "openocd_exe 未配置/占位/不存在, 跳过 SWD 探测"}
    elif probe:
        ok, tail = swd_probe(oc, attempts=1)
        swd = {"status": "ok" if ok else "fail", "detail": tail}
    else:
        swd = {"status": "skipped", "detail": "未请求探测"}

    # F-048: fixture 体检 (2026-09-02 方案四-5) — 复用 TOOLKIT_ROOT 的 fixture 目录
    #   不传 workspace 是因为 fixture 跟工具库同仓, 体检只看 tests/fixtures/contract/
    #   skip_drift_check 让测试场景 (占位时不许跑子进程) 显式跳过 git 调用
    fixture = fixture_health(os.path.join(TOOLKIT_ROOT, "tests", "fixtures", "contract"),
                             skip_drift_check=skip_drift_check)
    statuses = [tools[n]["status"] for n in ("gcc", "openocd", "make")] \
        + [swd["status"], fixture["status"]]
    summary = {k: statuses.count(k) for k in ("ok", "warn", "fail", "skipped")}
    summary["fixture"] = fixture["status"]   # F-048: fixture 子项与 tools/swd 平级
    return {"tool": "doctor", "toolkit_version": toolkit_version(),
            "python": sys.version.split()[0],
            "machine": {"mode": mode, "keys": keys},
            "tools": tools, "swd": swd, "fixtures": fixture, "summary": summary}


def _print_doctor(rep: dict) -> None:
    print("== embedded-toolkit doctor ==")
    print(f"toolkit : {rep['toolkit_version']}   python: {rep['python']}")
    print(f"machine : {rep['machine']['mode']}")
    for k, v in rep["machine"]["keys"].items():
        flags = [lbl for lbl, on in (("空", not v["value_set"]),
                                     ("占位", v["placeholder"]),
                                     ("路径在场", v["path_exists"])) if on]
        print(f"  {k:<11}: {', '.join(flags) if flags else '-'}")
    for name in ("gcc", "openocd", "make"):
        t = rep["tools"][name]
        line = f"  {name:<9}: {t['status']}"
        if t.get("version"):
            line += f" — {t['version']}"
        elif t.get("detail"):
            line += f" — {t['detail']}"
        if t.get("error"):
            line += f" | {t['error']}"
        print(line)
    print(f"swd     : {rep['swd']['status']} — {rep['swd']['detail'][:120]}")
    # F-048: fixture 体检行 (与 tools/swd 平级)
    fx = rep.get("fixtures", {})
    if fx:
        drift_note = ""
        if fx.get("drift", {}).get("detected"):
            mm = ", ".join(fx["drift"].get("mismatches", []))
            drift_note = f" (drift: {mm})"
        miss = []
        if fx.get("config", {}).get("status") == "missing":
            miss.append("config")
        if fx.get("expectations", {}).get("status") == "missing":
            miss.append("expectations")
        miss_note = f" (missing: {', '.join(miss)})" if miss else ""
        print(f"fixtures: {fx.get('status', '?')}{drift_note}{miss_note}")
    s = rep["summary"]
    print(f"summary : ok={s['ok']} warn={s['warn']} fail={s['fail']} skipped={s['skipped']}"
          + (f" fixture={s['fixture']}" if "fixture" in s else ""))
    print("(doctor 为诊断报告, 不做门禁判定; 报障请附 --doctor --json 输出)")


