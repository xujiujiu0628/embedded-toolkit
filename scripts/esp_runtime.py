"""ESP32 运行时后端 (F-174 esp32s3 pilot) — idf.py 构建 / esptool 烧录 / UART 采集.

设计: docs/specs/2026-09-16-esp32s3-pilot-design.md
纪律:
- 机器路径只允许存在于 machine.json (esp_idf_path / esp_tools_dir);
- 子进程成败只信 returncode (F-090 同源教训, OpenOCD 日志走 stderr 的同款坑);
- idf.py / esptool 依赖 export.ps1 注入的环境, 统一经 run_idf 单点封装
  (PowerShell 会话内 source 后顺序执行, 逐命令 $LASTEXITCODE 门闩传播退出码)。
"""
import glob
import hashlib
import os
import re
import subprocess
import time

from runtime_common import (load_workspace_state, update_state_entry,  # noqa: E402  (F-190/H-1: last_build 经共享层持锁读改写; F-200 A2 嵌套键消费)
                            workspace_root)
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
      2.5) F-177: 开口即释放 DTR/RTS (CH340 类桥电路断言双线=按住复位
         收 0 行; 释放附带一次 POWERON 复位=确定起点; 不支持设控制线
         的设备吞掉)
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
            # F-177: pyserial 开串口默认断言 DTR/RTS——CH340/CP210x 自动
            # 下载电路把该组合等价于拉低 EN, 芯片被按在复位里静默 0 行
            # (初代 esp32 真机首跑钓出; S3 试点板为 FTDI 桥 0403:6001,
            # 其对断言双线不拉 EN——旧代码在该板一向有行, 09-19 回归
            # 2× PASS 实证释放亦兼容)。开口后立即释放; CH340 板上
            # "断言→释放"本身就是一次 POWERON 复位, 反而给出确定起点。
            # 不支持设控制线的设备吞掉。
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            while time.time() - t0 < timeout_s:
                raw = ser.readline()
                if raw:
                    lines.append(raw.decode("utf-8", errors="replace")
                                 .rstrip("\r\n"))
    except serial.SerialException as e:
        # F-192 (WB-20260926-03 T4, 收 N-5): 已收行入账 — F-003"回收部分
        # 输出"纪律补齐 uart 异常路径 (此前只做了超时路径), 信封形态对齐
        # verify._finish_capture_timeout 的部分输出账 (lines 计数 +
        # partial_output 截断 2000); status 仍 fail-closed, esp_panic
        # 随部分输出保留 (定性交 AI judge, 采集故障不翻转判定)。
        text = "\n".join(lines)
        n_kept = len([ln for ln in lines if ln.strip()])
        return {
            "status": "error", "method": "uart", "port": port,
            "timeout_sec": timeout_s,
            "lines": n_kept,
            "esp_panic": detect_esp_panic(text),
            "error": f"串口 {port} 采集失败 (已收 {n_kept} 行一并入账): {e}",
            "partial_output": text[:2000],
        }
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
    """state.json last_build — 经 runtime_common.update_state_entry (F-190/H-1)。

    写入形态与 gcc_build 现场 (gcc_build.py:265-281) 逐键对齐: **嵌套
    artifacts + 平铺键双形态**——嵌套键供 release.build_record 消费
    (release.py:167, H-1 病灶: 旧版只写平铺键致 ESP 发布链在 hex 哈希门
    100% 硬拒), 平铺键供 verify --no-build 回读 (verify.py:805, 回归钉护)。
    hex_file 键复用 = .bin 路径 (F-174 既有约定); 哈希仍由 release 现场
    计算 (hex=bin、elf 各自 sha256), state 只落路径不落哈希 (同 gcc)。
    F-174a 随此闭合: update_state_entry 持锁读改写 (F-127) + 损坏隔离
    (.corrupt, F-019) + 原子替换 (F-020), 旧实现的无锁 RMW/损坏清空不再。"""
    artifacts = {"hex_file": bin_rel, "bin_file": bin_rel,
                 "elf_file": elf_rel}
    update_state_entry("last_build",
                       {"provider": "idf", "artifacts": dict(artifacts),
                        **artifacts},
                       ws)


# ── ESP panic 符号化面 (F-200, spec §4.3 "符号化解析后置另票" 兑现) ────────
# 红线: 只加信息不改判据 — 本节全部输出是增量信息账 (result 上的
# esp_panic_symbolized 字段与 stdout 解码框), status/judge/expect 判据链
# 零触碰; 每步 fail-soft (reason 点名), 绝不抛穿 verify 主流程。
# A6 卫生: addr2line 路径与 subprocess 均为注入参数, 零全局打桩。
# 工具事实 (实测): machine.json esp_tools_dir 下 xtensa 统一包
# xtensa-esp-elf-addr2line (binutils 2.43.1) elf 自识别 target, 经典
# ESP32 与 S3 通吃; 实输出三态 — 全解 "0xA: fn at f:L" / 无 DWARF
# "fn at ??:?" / 未解 "?? ??:0" (无 " at "), 地址回显小写归一 → 解析
# 按块序 zip, 禁回显匹配。
_BACKTRACE_PAIR_RE = re.compile(r"(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)")
_ELF_SHA_RE = re.compile(r"ELF file SHA\w*:\s*([0-9a-fA-F]{8,64})")
_ADDR2LINE_GLOB = os.path.join("tools", "xtensa-esp-elf", "*",
                               "xtensa-esp-elf", "bin",
                               "xtensa-esp-elf-addr2line.exe")
_ADDR_PREFIX_RE = re.compile(r"^0x[0-9a-fA-F]+:\s*")
_FRAME_SEG_RE = re.compile(r"^(.+?)\s+at\s+(.+):(\d+)$")
_FRAME_NO_DWARF_RE = re.compile(r"^(.+?)\s+at\s+\?\?:\?$")
_DISCRIMINATOR_RE = re.compile(r"\s*\(discriminator \d+\)\s*$")
_SYMBOLIZE_TIMEOUT = 60


def parse_backtrace(text: str) -> dict:
    """A1: 提取 Backtrace: 帧对 [(pc, sp)…] 与 ELF file SHA 行 (拍板③)。

    只扫含 "Backtrace:" 的行 (寄存器 dump 的 "REG: 0x…" 形态不误捕);
    帧分隔容忍空格与旧版 |<-CORRUPTED 尾巴; 多条 Backtrace 行按出现序
    拼接 (只加信息不去重); abort()/assert 无 backtrace → 空列表不报错。"""
    frames = []
    for ln in text.splitlines():
        if "Backtrace:" not in ln:
            continue
        frames.extend(_BACKTRACE_PAIR_RE.findall(ln))
    sha = _ELF_SHA_RE.search(text)
    return {"frames": frames, "elf_sha": sha.group(1) if sha else None}


def locate_addr2line(tools_dir: str | None) -> tuple[str | None, str | None]:
    """A3: esp_tools_dir 下定位 xtensa 统一包 addr2line。

    glob tools/xtensa-esp-elf/*/xtensa-esp-elf/bin/xtensa-esp-elf-addr2line.exe;
    多版本目录取版本段字典序最大 (确定性规则); 同版本前缀内日期段单调
    (F-201 措辞收窄: 跨主版本位数/跨命名方案 — 如 esp-9 vs esp-14、
    esp-2022r1 — 字典序≠语义序; 现网可达域内实证单版本无实害, 09 报告
    L-2 可达域论证; 扩集须先改语义比较);
    glob 空/目录缺 → (None, reason 点名)。只做存在性定位, 不校验可执行位
    (Windows 无此语义)。riscv/esp32ulp 工具链本票不入面 (在册无此类板)。"""
    if not tools_dir or not os.path.isdir(tools_dir):
        return None, ("no_tools_dir: esp_tools_dir 未配置或目录不存在 "
                      "(tools_dir=%r)" % (tools_dir,))
    hits = glob.glob(os.path.join(tools_dir, _ADDR2LINE_GLOB))
    if not hits:
        return None, ("addr2line_not_found: esp_tools_dir 下未找到 "
                      "xtensa-esp-elf-addr2line (glob tools/xtensa-esp-elf/"
                      "*/xtensa-esp-elf/bin/, tools_dir=%r)" % (tools_dir,))

    def _ver(hit: str) -> str:
        return os.path.relpath(hit, tools_dir).split(os.sep)[2]

    best = max(hits, key=lambda h: (_ver(h), h))
    return best, None


def _addr2line_frame(seg: str, pc: str) -> dict:
    """单段解码 → 帧字典 (A4 三态: 全解 / 无 DWARF / 未解)。"""
    seg = _DISCRIMINATOR_RE.sub("", seg.strip())
    m = _FRAME_SEG_RE.match(seg)
    if m:
        fn, path, line = m.group(1).strip(), m.group(2), int(m.group(3))
        if fn == "??" or path == "??":
            return {"pc": pc, "unresolved": True}
        return {"pc": pc, "function": fn, "file": path, "line": line}
    m = _FRAME_NO_DWARF_RE.match(seg)
    if m:
        # 符号表有函数名、无 DWARF 行列 (ROM/strip 档形态) — 保留函数名
        return {"pc": pc, "function": m.group(1).strip(),
                "file": None, "line": None}
    return {"pc": pc, "unresolved": True}   # "?? ??:0" 及一切不识别形态


def _addr2line_frames(out: str, pcs: list[str]) -> list[dict]:
    """addr2line 输出 → 帧列表。块序 zip 输入 pc (回显小写归一, 禁回显
    匹配); (inlined by) 链拆多帧同 pc 回显; 非 pretty 续行容忍; 块数不齐
    → 余帧补 unresolved 不断链。"""
    blocks: list[list[str]] = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("0x") and ":" in ln:
            blocks.append([ln])
        elif blocks:
            blocks[-1].append(ln)      # 旧 binutils 非 pretty 续行
    frames: list[dict] = []
    for i, block in enumerate(blocks):
        if i >= len(pcs):
            break                      # 输出块多于输入: 丢弃, 不杜撰帧
        for j, ln in enumerate(block):
            body = _ADDR_PREFIX_RE.sub("", ln, count=1) if j == 0 else ln
            for seg in body.split("(inlined by)"):
                if seg.strip():
                    frames.append(_addr2line_frame(seg, pcs[i]))
    if len(blocks) < len(pcs):
        frames.extend({"pc": pc, "unresolved": True}
                      for pc in pcs[len(blocks):])
    return frames


def symbolize_frames(pcs: list[str], elf_path: str, addr2line_exe: str,
                     *, _run=subprocess.run) -> tuple[list[dict] | None,
                                                      str | None]:
    """A4: 一次批量调 addr2line -f -i -a -p -e <elf> <pc…>。

    白名单 executable 直调 (无 shell=True, F-174 注入面纪律); 成败只信
    returncode (F-090)。返回 (frames, None) 或 (None, "tool_error: …");
    单帧 ?? 只降该帧, 不断链。"""
    if not pcs:
        return [], None
    cmd = [addr2line_exe, "-f", "-i", "-a", "-p", "-e", elf_path] + list(pcs)
    try:
        proc = _run(cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=_SYMBOLIZE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "tool_error: addr2line 超时 (%ds)" % _SYMBOLIZE_TIMEOUT
    except OSError as e:
        return None, "tool_error: addr2line 启动失败: %s" % e
    if proc.returncode != 0:
        return None, ("tool_error: addr2line rc=%s (stderr: %s)"
                      % (proc.returncode,
                         (proc.stderr or "")[-200:].strip()))
    return _addr2line_frames(proc.stdout or "", list(pcs)), None


def _sha256_file(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def symbolize_esp_panic(text: str, workspace: str | None = None, *,
                        addr2line_exe: str | None = None,
                        tools_dir: str | None = None,
                        _run=subprocess.run) -> dict:
    """A1~A5 编排: 捕获文本 → 符号化账, 全程 fail-soft 绝不抛穿。

    生产调用面 = verify uart panic 分支 (零注入): tools_dir 缺省读
    machine.json esp_tools_dir (只读消费); elf 走 state.json 嵌套键
    last_build.artifacts.elf_file (release.py:212 同口径, 平铺不兜底)。
    返回 {"available": true, tool, elf_path, frames[, elf_sha256,
    elf_sha256_captured, elf_sha_match]} 或 {"available": false,
    "reason": "<tag>: <点名>"} — 理由码 no_frames / elf_missing_key /
    elf_not_found / no_tools_dir / addr2line_not_found / tool_error /
    internal_error。SHA 前缀比对漂移只降"[参考级]" (拍板③), 不删帧。"""
    try:
        return _symbolize_impl(text, workspace, addr2line_exe=addr2line_exe,
                               tools_dir=tools_dir, _run=_run)
    except Exception as e:   # noqa: BLE001  (fail-soft 兜底: 信息面异常
        # 绝不许翻转判据, 也不许打断 verify 主流程)
        return {"available": False,
                "reason": "internal_error: 符号化编排异常: %r" % (e,)}


def _symbolize_impl(text: str, workspace: str | None = None, *,
                    addr2line_exe: str | None = None,
                    tools_dir: str | None = None,
                    _run=subprocess.run) -> dict:
    parsed = parse_backtrace(text)
    pcs = [pc for pc, _sp in parsed["frames"]]
    out: dict = {}
    if parsed["elf_sha"]:
        out["elf_sha256_captured"] = parsed["elf_sha"]   # 提取面独立于帧
    if not pcs:
        out["available"] = False
        out["reason"] = ("no_frames: 捕获文本无 Backtrace: 帧 "
                         "(abort()/assert 形态) — 原文已入账")
        return out
    entry = load_workspace_state(workspace).get("last_build")
    entry = entry if isinstance(entry, dict) else {}
    arts = entry.get("artifacts")
    arts = arts if isinstance(arts, dict) else {}
    rel = arts.get("elf_file")
    if not isinstance(rel, str) or not rel.strip():
        out["available"] = False
        out["reason"] = ("elf_missing_key: state.json 缺 "
                         "last_build.artifacts.elf_file (未构建/无 elf "
                         "产出/档缺失均此账; 嵌套键消费不含平铺兜底)")
        return out
    ws_root = os.path.normpath(str(workspace_root(workspace)))
    elf = os.path.normpath(os.path.join(ws_root, rel))
    out["elf_path"] = elf
    # F-206 (复审 L-4): os.path.join 对绝对路径 rel 直接采纳 — state.json
    # 被篡改/外来档可引 workspace 外任意 elf 进符号化。收容校验: 解析结果
    # 必须仍位于 workspace 下 (normcase 归一 Windows 大小写/分隔符差异);
    # 信息面只读、写入方恒写相对路径, 此为防波堤非修复行为面。
    if os.path.isabs(rel) or not os.path.normcase(elf).startswith(
            os.path.normcase(ws_root + os.sep)):
        out["available"] = False
        out["reason"] = ("elf_path_escape: state.json 记录的 elf_file 为"
                         "绝对路径或越出 workspace (禁跨目录取档): " + rel)
        return out
    if not os.path.isfile(elf):
        out["available"] = False
        out["reason"] = ("elf_not_found: state.json 记录的 elf 档不存在: "
                         + elf)
        return out
    if addr2line_exe:
        exe = addr2line_exe
    else:
        tools = tools_dir if tools_dir else (load_machine() or {}).get(
            "esp_tools_dir", "")
        exe, why = locate_addr2line(tools)
        if not exe:
            out["available"] = False
            out["reason"] = why
            return out
    out["tool"] = os.path.basename(exe)
    frames, why = symbolize_frames(pcs, elf, exe, _run=_run)
    if frames is None:
        out["available"] = False
        out["reason"] = why
        return out
    out["available"] = True
    out["frames"] = frames
    local_sha = _sha256_file(elf)
    if local_sha:
        out["elf_sha256"] = local_sha
        if parsed["elf_sha"] and len(parsed["elf_sha"]) >= 8:
            out["elf_sha_match"] = local_sha.startswith(
                parsed["elf_sha"].lower())
    return out


def format_symbol_box(sym: dict) -> str:
    """A5: 人类可读解码框 (available → 多行框 / fail-soft → 一行注记)。

    只读渲染不判案 — SHA 漂移打 "[参考级]" 警告行, 判据链不消费本输出。"""
    if not sym.get("available"):
        return ("ESP panic 符号化不可用 (%s) — 原文 backtrace 已随捕获文本"
                "入账, 定性交 AI judge" % sym.get("reason", "?"))
    lines = ["== ESP panic 符号化 (tool: %s) ==" % sym.get("tool", "?"),
             "  elf: %s" % sym.get("elf_path", "?")]
    frames = sym.get("frames") or []
    solved = 0
    for i, fr in enumerate(frames):
        if fr.get("unresolved"):
            lines.append("  #%d %s  [未解]" % (i, fr.get("pc", "?")))
            continue
        solved += 1
        if fr.get("file") is None:
            loc = "位置未知"
        else:
            loc = "%s:%s" % (fr["file"], fr.get("line", "?"))
        lines.append("  #%d %s  %s  %s" % (i, fr.get("pc", "?"),
                                           fr.get("function", "?"), loc))
    lines.append("  解码 %d/%d 帧 (未解 %d)"
                 % (solved, len(frames), len(frames) - solved))
    if sym.get("elf_sha_match") is False:
        lines.append("  [参考级] ELF SHA 漂移: 捕获 %s… ≠ 本地 %s… — "
                     "符号化结果可能跨版本, 仅供参考"
                     % (str(sym.get("elf_sha256_captured", ""))[:12],
                        str(sym.get("elf_sha256", ""))[:12]))
    return "\n".join(lines)
