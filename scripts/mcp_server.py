r"""MCP server (F-130, 工单二 A-3) — 现有 CLI 工具的有界 MCP 包装。

借鉴 agentic-hil / hardci / jlink-mcp 的第一接口形态: agent 通过有界 MCP
工具使用本工具库, 不再靠 shell 拼装。两条铁律 (agentic-hil 安全设计,
第一版就守住):
  1. 工具 = 对现有脚本的子进程调用透传, 零业务逻辑复制——CLI 仍是唯一事实源;
  2. 入参白名单校验 (工程根必须存在 .workbench/config.json 等), **不给
     agent 任意 shell**——参数值逐个过类型/正则/边界, 拒绝一切以 "-" 开头
     的值 (flag 注入)。

MCP SDK 为可选依赖 (requirements-mcp.txt, 仅本文件需要): 缺失时给可行动
的报错后退出, 不影响库内其余工具。stdio transport, Claude Code 注册方式
见仓根 .mcp.json.example 与 README "MCP 接入"。

前置: 工单一 P0-2 (F-120) 已统一 JSON 模式失败退出码——本 server 按
returncode 判 ok, 非零 = 工具判定失败, 错误经 stderr 尾巴透传给 agent。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

TOOLKIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(TOOLKIT_ROOT, "scripts")

# 子进程默认超时 (秒) — run_verify 的采集窗受 --timeout 参数约束另算
_DEFAULT_TIMEOUT = 120


class McpToolError(ValueError):
    """工具调用前置失败 (工程非法/参数越界) — 与子进程失败分开建模。"""


# ── 工具注册表: 单一数据结构, 测试钉住"每个工具映射的脚本真实存在" ──────
# params 规格: {键: (json schema 类型, 校验器 callable, 映射旗标, 描述)}
# 校验器返回 None 表示合法, 返回字符串 = 拒绝理由。
_PIN_RE = re.compile(r"^P[A-E]\d{1,2}$")
_RE_JUST_WORD = re.compile(r"^[A-Z][A-Z0-9]*\d*$")


def _no_leading_dash(v: str) -> str | None:
    return "值不得以 '-' 开头 (flag 注入)" if v.startswith("-") else None


def _bounded_int(lo: int, hi: int):
    def _check(v: int) -> str | None:
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            return f"须为 {lo}~{hi} 的整数"
        return None
    return _check


def _regex(regex: re.Pattern, hint: str):
    def _check(v: str) -> str | None:
        if not isinstance(v, str) or not regex.fullmatch(v):
            return f"须匹配 {hint}"
        return None
    return _check


_TOOL_REGISTRY: dict = {
    "run_verify": {
        "script": "verify.py",
        "description": ("闭环验证 (build→flash→capture→判定), 返回四态判定 JSON "
                        "与顶层 evidence 证据等级。需 ST-Link + 板子。"),
        "requires_project": True,
        "fixed_flags": ["--json"],
        "default_timeout": 600,   # verify 自带 build/采集窗, 给足
        "params": {
            "timeout": ("integer", _bounded_int(5, 120), "--timeout",
                        "采集超时秒数 (5~120)"),
            "no_flash": ("boolean", None, "--no-flash",
                         "跳过烧录 (固件已在板上时)"),
            "require_tgl": ("boolean", None, "--require-tgl",
                            "断言 capture 中至少 1 条 TGL 事件"),
        },
    },
    "lint_expectations": {
        "script": "expectations_lint.py",
        "description": "静态校验期望清单 (E1~E9 规则), 秒级, 无需硬件。",
        "requires_project": True,
        "fixed_flags": ["--json"],
        "default_timeout": _DEFAULT_TIMEOUT,
        "params": {},
    },
    "gen_peripheral": {
        "script": "gen_periph.py",
        "description": ("寄存器级外设初始化代码生成 (GPIO/USART/PWM/ADC/"
                        "I2C/SPI/systick/timer-int/doc)。"),
        "requires_project": False,
        "fixed_flags": [],
        "default_timeout": _DEFAULT_TIMEOUT,
        "params": {
            "type": ("string", _regex(re.compile(
                r"gpio|usart|pwm|adc|systick|timer-int|i2c|spi|doc"),
                "gpio|usart|pwm|adc|systick|timer-int|i2c|spi|doc"), "--type",
                "外设类型 (必填)"),
            "pin": ("string", _regex(_PIN_RE, "PA0~PE15 形态"), "--pin",
                    "GPIO 引脚"),
            "timer": ("string", _regex(re.compile(r"^TIM[1-4]$"), "TIM1~TIM4"),
                      "--timer", "PWM 定时器"),
            "ch": ("integer", _bounded_int(0, 17), "--ch",
                   "通道: PWM 1-4 / ADC 0-17"),
            "freq": ("integer", _bounded_int(1, 1_000_000), "--freq",
                     "PWM 频率 Hz"),
            "duty": ("integer", _bounded_int(0, 100), "--duty", "占空比 %"),
            "usart": ("string", _regex(re.compile(r"^USART[1-3]$"), "USART1~3"),
                      "--usart", "USART 外设"),
            "baud": ("integer", _bounded_int(300, 921_600), "--baud", "波特率"),
            "i2c": ("string", _regex(re.compile(r"^I2C[12]$"), "I2C1/2"),
                    "--i2c", "I2C 外设"),
            "speed": ("integer", _bounded_int(10_000, 1_000_000), "--speed",
                      "I2C 速率 Hz"),
            "periph": ("string", _regex(_RE_JUST_WORD, "如 I2C1/ADC1"), "--periph",
                       "--type doc 的目标外设"),
        },
        "required_params": ("type",),
    },
    "rm_lookup": {
        "script": "rm_lookup.py",
        "description": "查询寄存器知识库 (外设/寄存器/位/配方/关系)。",
        "requires_project": False,
        "fixed_flags": ["--json"],
        "default_timeout": _DEFAULT_TIMEOUT,
        "params": {
            "query": ("string", _no_leading_dash, None, "搜索词"),
            "recipe": ("string", _no_leading_dash, "--recipe", "仅搜索配方"),
            "rel": ("string", _no_leading_dash, "--rel",
                    "查外设关系 (如 'USART1 DMA', 'I2C1 pins')"),
        },
    },
    "diagnose_hardfault": {
        "script": "hardfault.py",
        "description": ("从捕获文本解析 HardFault 现场 ([HF] PC=/LR= 行 → "
                        "fault_site + 符号解析)。仅解析, 不触探针/不抢 ST-Link。"),
        "requires_project": False,
        "fixed_flags": ["--json", "--no-probe", "--fault-text", "-"],
        "default_timeout": _DEFAULT_TIMEOUT,
        "stdin_param": "text",
        "params": {
            "text": ("string", None, None,
                     "含 [HF] PC=xxxxxxxx LR=xxxxxxxx 行的捕获文本 (必填)"),
        },
        "required_params": ("text",),
        "max_stdin_chars": 20_000,
    },
    "doctor": {
        "script": "verify.py",
        "description": "环境预检: toolkit/Python/machine.json/gcc/openocd/make 矩阵。",
        "requires_project": False,
        "fixed_flags": ["--doctor", "--json"],
        "default_timeout": _DEFAULT_TIMEOUT,
        "params": {},
    },
}


def _script_path(tool: dict) -> str:
    return os.path.join(SCRIPTS, tool["script"])


def resolve_project(project: str) -> str:
    """工程根白名单校验: 必须存在且持有 .workbench/config.json。

    MCP agent 传任意路径都过这道闸——不存在/非工程即拒绝, 不给文件系统
    探测面 (agentic-hil 安全设计)。"""
    if not isinstance(project, str) or not project.strip():
        raise McpToolError("project 必填: 工程根目录绝对路径")
    ws = os.path.abspath(project)
    if not os.path.isdir(ws):
        raise McpToolError(f"project 目录不存在: {ws}")
    if not os.path.isfile(os.path.join(ws, ".workbench", "config.json")):
        raise McpToolError(
            f"{ws} 不是本工具库的工程 (缺 .workbench/config.json) — "
            "请传固件工程根, 不要传工具库自身路径")
    return ws


def _validate_param(tool_name: str, p_name: str, p_spec: tuple, value) -> list:
    """单参数白名单校验, 返回该参数映射的 CLI 旗标片段 (空列表 = 无旗标)。

    未知参数在 _plan_tool_call 层拒绝 (不在 spec 里的键一律非法)。"""
    schema_type, checker, flag, _desc = p_spec
    reason = None
    if schema_type == "integer":
        reason = checker(value)   # _bounded_int 自带类型检查
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            reason = "须为 boolean"
    else:
        if not isinstance(value, str):
            reason = "须为字符串"
        elif checker is not None:
            reason = checker(value)
    if reason:
        raise McpToolError(f"{tool_name}.{p_name} 非法: {reason}")
    if not flag:
        # F-183 (WB-20260921-04, GAP-F-7 裁决): `flag is None` 且**非**该工具
        # stdin 通道的参数 —— 其 CLI 真相是**位置参数** (rm_lookup.py:
        # `parser.add_argument("query", nargs="?")`), 旧式 `return []` 让 MCP 层
        # 宣告进 inputSchema 的参数**永不送达** (argv 无该值、无报错)。
        # 裁决 = 走**位置参数路线**(不发明旗标): 值按位置片段投影, 必 str 化
        # (F-180 契约同式)。
        # 前提/边界: 注册表当前唯一命中 `rm_lookup.query`, 故"尾部追加"即正确
        # 位置; 出现第二个无旗标参数时须重设计位置语义 (登记 GAP-F-12)。
        # boolean 无旗标者当前不存在 —— 若将来出现, 此处会以 str 值入 argv,
        # 由形态守卫 (tests/test_mcp_registry_shape.py 的无旗标参数快照钉 +
        # 位置投影钉) 拦下。
        return [str(value)]
    if schema_type == "boolean":
        # F-178 (WB-20260920-04, H-1): boolean 参数映射的是 store_true 开关
        # 旗标 —— 只发旗标本身, 绝不把 Python bool 当值塞进 argv。
        # 旧式 `[flag, value]` 对 False 也成立 (False != "" 恒真), 两层皆坏:
        #   · subprocess.list2cmdline 对非 str 抛
        #     `TypeError: expected str, bytes or os.PathLike object, not bool`
        #     —— 进程未起且异常不被 run_planned_call 的信封捕获;
        #   · 即便子进程起得来, argparse 的 store_true 收到值会报
        #     `unrecognized arguments`。
        return [flag] if value else []
    # F-180 (WB-20260921-01, GAP-F-1): 非 boolean 参数的值一律 str 化后再入
    # argv —— 旧式 `[flag, value]` 把裸 Python int 塞进 argv, Windows 上
    # `subprocess.list2cmdline` 抛
    # `TypeError: expected str, bytes or os.PathLike object, not int`,
    # 进程未起且异常不被 run_planned_call 的信封捕获 (违反本文件"统一信封"
    # 设计)。影响面: run_verify.timeout + gen_peripheral 的
    # ch/freq/duty/baud/speed 共 6 个整型参数。已是 str 者经 str() 恒等,
    # 语义零变。校验仍在上方先行 (非法值抛 McpToolError, 顺序不倒)。
    return [flag, str(value)] if value != "" else []


def plan_tool_call(tool_name: str, arguments: dict | None) -> dict:
    """纯计划层: 工具名 + 入参 → (argv, stdin_text, cwd, timeout)。

    校验失败抛 McpToolError; 不做任何 IO (除工程根存在性检查)。
    测试钉分发契约的主入口。"""
    tool = _TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise McpToolError(
            f"未知工具: {tool_name!r}, 可用: {', '.join(sorted(_TOOL_REGISTRY))}")
    arguments = dict(arguments or {})
    argv = [sys.executable, _script_path(tool)] + list(tool["fixed_flags"])

    cwd = None
    if tool.get("requires_project"):
        cwd = resolve_project(arguments.pop("project", ""))
        argv.extend(["--project", cwd])

    unknown = set(arguments) - set(tool["params"])
    if unknown:
        raise McpToolError(
            f"{tool_name} 不接受参数: {', '.join(sorted(unknown))} — "
            f"白名单: {', '.join(sorted(tool['params'])) or '(无)'}")

    stdin_text = None
    positional_pieces = []
    stdin_param = tool.get("stdin_param")
    for p_name, p_spec in tool["params"].items():
        if p_name not in arguments:
            continue
        pieces = _validate_param(tool_name, p_name, p_spec, arguments[p_name])
        if p_name == stdin_param:
            stdin_text = arguments[p_name]
            if len(stdin_text) > tool.get("max_stdin_chars", 20_000):
                raise McpToolError(
                    f"{tool_name}.{p_name} 超长 ({len(stdin_text)} > "
                    f"{tool['max_stdin_chars']} 字符)")
            continue
        if p_spec[2] is None:
            # F-183 (GAP-F-7 裁决): 无旗标片段 = **位置片段** (`_validate_param`
            # 返 `[str(value)]`)。按**注册顺序**收集, 统一追加到 argv **尾部**
            # (旗标片段流之后) —— 位置参数与旗标混排时尾部才是 CLI 的位置语义
            # (`rm_lookup.py --json --recipe I2C GPIOA`), 且末位恒为该参数值。
            # 当前唯一命中 rm_lookup.query; 多值/选项扩展另设计 (GAP-F-12)。
            positional_pieces.extend(pieces)
            continue
        argv.extend(pieces)

    argv.extend(positional_pieces)

    missing = [r for r in tool.get("required_params", ()) if r not in arguments]
    if missing:
        raise McpToolError(f"{tool_name} 缺必填参数: {', '.join(missing)}")

    return {
        "argv": argv,
        "stdin_text": stdin_text,
        "cwd": cwd,
        "timeout": tool.get("default_timeout", _DEFAULT_TIMEOUT),
    }


def run_planned_call(plan: dict) -> dict:
    """子进程透传执行计划, 返回统一信封。

    ok = returncode==0 (F-120 后 JSON 模式失败必非零); result 为解析出的
    JSON (可解析时), stdout/stderr 截尾透传——agent 拿到的是工具自己的
    输出, 本层不加工语义。"""
    try:
        proc = subprocess.run(
            plan["argv"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=plan["timeout"], cwd=plan["cwd"],
            input=plan["stdin_text"])
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None,
                "error": f"工具子进程超时 ({plan['timeout']}s)"}
    except OSError as e:
        return {"ok": False, "exit_code": None, "error": str(e)}
    out = {"ok": proc.returncode == 0, "exit_code": proc.returncode}
    try:
        out["result"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out["result"] = None
        out["stdout"] = proc.stdout[-2000:]
    out["stderr"] = (proc.stderr or "")[-1000:]
    return out


def call_tool(tool_name: str, arguments: dict | None) -> dict:
    """MCP call_tool 的同步实现 (计划 + 透传)。"""
    return run_planned_call(plan_tool_call(tool_name, arguments))


def tool_input_schema(tool_name: str) -> dict:
    """由注册表生成 MCP inputSchema (properties 白名单 + required)。"""
    tool = _TOOL_REGISTRY[tool_name]
    props = {}
    if tool.get("requires_project"):
        # F-183 (WB-20260921-04, GAP-F-8): 尾逗号曾使 RHS 成 1-元 tuple →
        # inputSchema 的 `properties.project` 被 JSON 序列化为**数组**而非对象
        # (对 MCP 客户端即畸形 schema)。RHS 必须是 dict。
        props["project"] = {
            "type": "string",
            "description": "固件工程根目录 (须含 .workbench/config.json)"}
    for p_name, p_spec in tool["params"].items():
        schema_type, _checker, _flag, desc = p_spec
        props[p_name] = {"type": schema_type, "description": desc}
    return {
        "type": "object",
        "properties": props,
        "required": (["project"] if tool.get("requires_project") else [])
                    + list(tool.get("required_params", ())),
    }


# ── MCP SDK 胶水 (可选依赖, 缺失时给可行动的报错) ─────────────────────────

def try_import_sdk() -> tuple[bool, str]:
    """探测 MCP SDK。缺失时返回可行动的报错文案 (machine.json 回退警告
    同款诚实化风格)。"""
    try:
        import mcp  # noqa: F401
        return True, ""
    except ImportError:
        return False, (
            "MCP SDK 未安装 — 本 server 是唯一需要它的组件。\n"
            "  安装: pip install -r requirements-mcp.txt\n"
            "  (工具库其余功能零第三方依赖, 不受影响; CLI 用法见 README)")


def build_server():
    """构建 MCP server 实例 (list_tools/call_tool 全部走上方纯计划层)。"""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    app = Server("embedded-toolkit")

    @app.list_tools()
    async def _list_tools() -> list[Tool]:
        return [Tool(name=name, description=tool["description"],
                     inputSchema=tool_input_schema(name))
                for name, tool in sorted(_TOOL_REGISTRY.items())]

    @app.call_tool()
    async def _call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        try:
            out = call_tool(name, arguments)
        except McpToolError as e:
            out = {"ok": False, "exit_code": None, "error": str(e)}
        return [TextContent(type="text",
                            text=json.dumps(out, ensure_ascii=False))]

    return app


def main() -> int:
    ok, message = try_import_sdk()
    if not ok:
        print(message, file=sys.stderr)
        return 2
    import asyncio

    from mcp.server.stdio import stdio_server

    app = build_server()

    async def _serve():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream,
                          app.create_initialization_options())

    asyncio.run(_serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
