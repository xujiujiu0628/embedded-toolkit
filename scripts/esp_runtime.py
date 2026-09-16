"""ESP32 运行时后端 (F-174 esp32s3 pilot) — idf.py 构建 / esptool 烧录 / UART 采集.

设计: docs/specs/2026-09-16-esp32s3-pilot-design.md
纪律:
- 机器路径只允许存在于 machine.json (esp_idf_path / esp_tools_dir);
- 子进程成败只信 returncode (F-090 同源教训, OpenOCD 日志走 stderr 的同款坑);
- idf.py / esptool 依赖 export.ps1 注入的环境, 统一经 run_idf 单点封装
  (PowerShell 会话内 source 后顺序执行, 逐命令 $LASTEXITCODE 门闩传播退出码)。
"""
import os
import subprocess

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
