"""ESP32 运行时后端 (F-174 esp32s3 pilot) — idf.py 构建 / esptool 烧录 / UART 采集.

设计: docs/specs/2026-09-16-esp32s3-pilot-design.md
纪律:
- 机器路径只允许存在于 machine.json (esp_idf_path / esp_tools_dir);
- 子进程成败只信 returncode (F-090 同源教训, OpenOCD 日志走 stderr 的同款坑);
- idf.py / esptool 依赖 export.ps1 注入的环境, 统一经 run_idf 单点封装
  (PowerShell 会话内 source 后顺序执行, 逐命令 $LASTEXITCODE 门闩传播退出码)。
"""
import glob
import json
import os
import re
import subprocess
import time

from wb_common import load_machine

_PANIC_MARKERS = ("Guru Meditation", "Backtrace:", "abort() was called",
                  "assert failed", "Heap corruption")


class EspConfigError(RuntimeError):
    """machine.json 缺 esp_idf_path 或目录不存在 — 友好报错不裸 traceback"""


def resolve_idf_path() -> str:
    m = load_machine()
    path = m.get("esp_idf_path", "")
    if not path or not os.path.isdir(path):
        raise EspConfigError(
            f"machine.json esp_idf_path 未配置或目录不存在: {path!r} — "
            "真机构建/烧录前请填入 ESP-IDF 根目录绝对路径")
    return path


def _idf_env() -> dict:
    """子进程 env: IDF_TOOLS_PATH 指到 machine.json 的 esp_tools_dir.

    export.ps1 找不到工具会去默认 %USERPROFILE%\\.espressif 兜底——装在哪
    就必须告诉它去哪找, 键缺省时不注入 (回落 IDF 官方默认)。"""
    env = os.environ.copy()
    # F-174 真机裁决: 调用方若是 Git Bash 系进程, MSYSTEM/MSYS*/MINGW* 会随
    # 环境继承进 PowerShell 子进程, IDF export 检测到即拒绝激活
    # ("MSys/Mingw is not supported")——清除这些标记, 保证原生态激活。
    for _k in [k for k in env if k.upper().startswith(("MSYSTEM", "MSYS", "MINGW"))]:
        env.pop(_k)
    tools = load_machine().get("esp_tools_dir", "")
    if tools:
        env["IDF_TOOLS_PATH"] = tools
    return env


def run_idf(ps_commands: list[str], timeout: int, workspace: str,
            *, _run=subprocess.run) -> dict:
    """在 export.ps1 环境里顺序执行 PowerShell 命令串.

    导出脚本失败不单独拦——下一条命令必炸且报错更具体。
    返回 {status, returncode, output} (output = stdout+stderr 合并) 或
    超时 {status:"error", message}。_run 注入点供 host 单测。"""
    idf = resolve_idf_path()
    export = os.path.join(idf, "export.ps1").replace("\\", "/")  # PS 单引号不吃反斜杠转义
    export = export.replace("'", "''")  # PS 单引号串内 ' 只能翻倍转义 (Task 2 审查裁决)
    parts = [f". '{export}'"]
    for c in ps_commands:
        parts.append(c)
        parts.append("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-Command", "; ".join(parts)]
    try:
        proc = _run(cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout, cwd=workspace,
                    env=_idf_env())
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"idf 子进程超时 ({timeout}s)"}
    return {"status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "output": (proc.stdout or "") + (proc.stderr or "")}


def detect_esp_panic(text: str) -> bool:
    """ESP panic 只做文本级标记 (spec §4.3): 符号化解析后置另票。"""
    return any(m in text for m in _PANIC_MARKERS)


def step_build_idf(config: dict, rebuild: bool = False,
                   workspace: str | None = None,
                   *, _run_idf=None) -> dict:
    """builder=idf (F-174): idf.py build, 契约对齐 gcc_build (spec §4.2)。

    metrics 从合并日志行计数 ("error:" 行 + ninja "FAILED:" 行);
    成败判据: run_idf rc==0 且 errors==0, 两者缺一即 error。
    _run_idf 注入点供单测 (默认走模块级 run_idf)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    cfg = (config or {}).get("idf", {}) or {}
    commands = (["idf.py fullclean"] if rebuild else []) + ["idf.py build"]
    run = run_idf_(commands, timeout=int(cfg.get("build_timeout", 900)),
                   workspace=ws)
    output = run.get("output", "")

    log_dir = os.path.join(ws, ".workbench", "build")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "idf_build.log")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(output)

    errors = sum(1 for ln in output.splitlines()
                 if "error:" in ln or "FAILED:" in ln)
    warnings = sum(1 for ln in output.splitlines() if "warning:" in ln)
    metrics = {"errors": errors, "warnings": warnings}
    details = {"log_file": os.path.relpath(log_file, ws).replace(os.sep, "/")}

    if run.get("status") != "ok" or errors > 0:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": (f"idf build failed "
                            f"(rc={run.get('returncode', '?')}, {errors} errors)"),
                "stderr": output[-500:]}

    bins = sorted(glob.glob(os.path.join(ws, "build", "*.bin")))
    elfs = sorted(glob.glob(os.path.join(ws, "build", "*.elf")))
    if not bins:
        return {"status": "error", "metrics": metrics, "details": details,
                "summary": "idf build ok 但 build/*.bin 缺失 (先 set-target?)",
                "stderr": output[-300:]}
    bin_rel = os.path.relpath(bins[0], ws).replace(os.sep, "/")
    elf_rel = (os.path.relpath(elfs[0], ws).replace(os.sep, "/")
               if elfs else "")
    details.update({"hex_file": bin_rel, "bin_file": bin_rel,
                    "elf_file": elf_rel})
    _write_last_build(ws, bin_rel, elf_rel)
    return {"status": "ok", "metrics": metrics, "details": details,
            "summary": f"idf build ok ({warnings} warnings)"}


# ── 合入前置校验票 (F-174 终审安全节) ──────────────────────────────────────
# port/chip 会拼进 PowerShell 命令串 (run_idf)——config 虽是可信源, 白名单
# 收紧后"可信"不再依赖操作者自觉。port 只收 Windows COMn 与 Linux tty/cu
# 形态; 一切含空格/引号/分号/管道/$() 的"端口"在这里就被拒, 不进 shell。
_ESP_PORT_RE = re.compile(
    r"^(?:(?i:COM)\d{1,3}|/dev/(?:ttyUSB\d+|ttyACM\d+|cu\.[A-Za-z0-9._-]+))$")
_ESP_CHIPS = {"esp32", "esp32s2", "esp32s3", "esp32c2", "esp32c3",
              "esp32c5", "esp32c6", "esp32h2", "esp32p4"}


def _esp_port_error(port: str) -> str:
    """合法返空串; 非法返可读拒因 (调用方各自包 status:error 返回)。"""
    if not _ESP_PORT_RE.match(port):
        return ("flash/capture.port 不在白名单 (只收 COMn、/dev/ttyUSB*、"
                "/dev/ttyACM*、/dev/cu.*; 禁空格与 shell 元字符): "
                + repr(port))
    return ""


def _normalize_chip(chip) -> str:
    """esp32-S3 / ESP32_S3 等书写变体归一到白名单键形态。"""
    return str(chip).strip().lower().replace("-", "").replace("_", "")


def step_flash_esptool(flash_cfg: dict, workspace: str | None = None,
                       *, _run_idf=None) -> dict:
    """flash.backend=esptool (F-174): 经 idf.py -p <port> flash 烧录.

    选 idf.py flash 而非手拼 esptool write_flash 地址表: flash_args 由构建
    系统生成 (bootloader/分区表/app 三镜像+offset), 手拼即漂移 (spec §4.2)。
    结束自带 --after hard_reset, capture 段仍显式再复位一次 (确定性起点)。"""
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    port = (flash_cfg.get("port") or "").strip()
    if not port:
        return {"status": "error", "backend": "esptool",
                "message": "flash.port 未配置 (esptool 后端需要串口号, 如 COM3)"}
    port_err = _esp_port_error(port)
    if port_err:
        return {"status": "error", "backend": "esptool", "message": port_err}
    run = run_idf_([f"idf.py -p {port} flash"],
                   timeout=int(flash_cfg.get("timeout", 300)), workspace=ws)
    out = run.get("output", "")
    if run.get("status") == "ok":
        return {"status": "ok", "backend": "esptool", "stdout": out[-1000:]}
    return {"status": "error", "backend": "esptool",
            "message": f"idf.py flash 失败 (port={port}, "
                       f"rc={run.get('returncode', '?')})",
            "stderr": out[-500:]}


def step_capture_uart(timeout_s: int, cap_cfg: dict,
                      workspace: str | None = None,
                      *, _run_idf=None) -> dict:
    """capture.backend=uart (F-174): esptool 复位进固件 → pyserial 定时采集.

    时序 (spec §7 风险"复位窗口丢日志"缓解):
      1) esptool --after hard_reset chip_id: 廉价只读命令触发确定性复位
         (--no-flash 续跑路径同样先复位, 不吃上一轮残态 — 2026-08-16 教训同款)
      2) settle_sec 静默等端口稳定 (USB-UART 桥重枚举, 默认 1.0s)
      3) readline 到 deadline: 端口异常即 error (COM3 被占/拔线给可读报错)
    panic 不拦截: 只打 esp_panic 文本标记, 定性交 AI judge (spec §4.3)。
    正文经私有键 "_text" 带回, 契约与 step_capture_rtt 一致。
    """
    run_idf_ = _run_idf or run_idf
    ws = workspace or os.getcwd()
    port = (cap_cfg.get("port") or "").strip()
    if not port:
        return {"status": "error", "method": "uart",
                "error": "capture.port 未配置 (uart 后端需要串口号, 如 COM3)"}
    port_err = _esp_port_error(port)
    if port_err:
        return {"status": "error", "method": "uart", "error": port_err}
    chip = _normalize_chip(cap_cfg.get("chip", "esp32s3"))
    if chip not in _ESP_CHIPS:
        return {"status": "error", "method": "uart",
                "error": f"capture.chip 不在白名单: {chip!r} "
                         f"(支持: {', '.join(sorted(_ESP_CHIPS))})"}
    try:
        import serial
    except ImportError:
        return {"status": "error", "method": "uart",
                "error": "缺 pyserial: pip install pyserial"}
    # 复位兼探活用 esptool 只读命令。控制者裁决: 用下划线形式 chip_id + hard_reset
    # —— IDF 5.4 自带 esptool v4.x 的 --after 只认下划线 (真机首跑报 "invalid
    # choice: 'hard-reset'"); pip 装的 v5 仍收下划线 (仅弃用警告), 故下划线是
    # 两版通吃的安全集。若 PATH 只有 esptool.py 入口报 "not recognized", 换
    # `esptool.py ...` (Task 7 现场定; 单测 mock run_idf 不受影响)。
    reset = run_idf_([f"esptool --chip {chip} -p {port} --after "
                      f"hard_reset chip_id"], timeout=30, workspace=ws)
    if reset.get("status") != "ok":
        return {"status": "error", "method": "uart",
                "error": ("复位失败 (端口被占/板子未上电?): "
                          + (reset.get("message")
                             or reset.get("output", "")[-300:]))}

    t0 = time.time()
    deadline = t0 + float(cap_cfg.get("settle_sec", 1.0))
    try:
        while time.time() < deadline:
            time.sleep(0.05)
    except Exception:
        pass
    t0 = time.time()
    lines = []
    try:
        with serial.Serial(port, int(cap_cfg.get("baudrate", 115200)),
                           timeout=0.5) as ser:
            while time.time() - t0 < timeout_s:
                raw = ser.readline()
                if raw:
                    lines.append(raw.decode("utf-8", errors="replace")
                                 .rstrip("\r\n"))
    except serial.SerialException as e:
        return {"status": "error", "method": "uart",
                "error": f"串口 {port} 采集失败: {e}"}
    text = "\n".join(lines)
    return {
        "status": "ok", "method": "uart", "port": port,
        "timeout_sec": timeout_s,
        "lines": len([ln for ln in lines if ln.strip()]),
        "esp_panic": detect_esp_panic(text),
        "duration_sec": round(time.time() - t0, 1),
        "_text": text,
    }


def _write_last_build(ws: str, bin_rel: str, elf_rel: str) -> None:
    """state.json last_build (verify --no-build 回读契约, 与 gcc_build 同构)。

    hex_file 键复用 = .bin 路径: step_flash 的存在性检查与 --no-build
    读取逻辑零改动即可走通 esptool 后端。"""
    state_path = os.path.join(ws, ".workbench", "state.json")
    state = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["last_build"] = {"provider": "idf", "hex_file": bin_rel,
                           "bin_file": bin_rel, "elf_file": elf_rel,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
