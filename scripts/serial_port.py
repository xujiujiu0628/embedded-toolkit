"""capture.port 的端口解析 (F-235)。

字面量 (COM15 / /dev/ttyUSB0) 原样返回, 交给调用方的既有校验;
`auto:<描述子串>` 则用 pyserial 枚举端口, 按 description/hwid 子串
大小写不敏感匹配。0 命中或 >1 命中都报错并列出现场 —— 不猜。
跨平台: 只用 pyserial, 不调 PowerShell / udev。
"""
from __future__ import annotations

try:
    from serial.tools import list_ports
except ImportError:      # 无 pyserial 的宿主: 本模块仍可 import (esp_runtime
    list_ports = None    # 被 verify 顶层引用, 核心闭环链零第三方依赖不受牵连),
                         # 字面量端口照用, 只有 auto: 分支报可读缺依赖错。
AUTO_PREFIX = "auto:"


def resolve_port(port_cfg) -> dict:
    """返回 {"port": <设备名>} 或 {"error": <可读原因>}。"""
    raw = (port_cfg or "").strip()
    if not raw:
        return {"error": "capture.port 未配置 (uart 后端需要串口号, "
                         "可写 COM3 或 auto:<描述子串>)"}
    if not raw.lower().startswith(AUTO_PREFIX):
        return {"port": raw}
    needle = raw[len(AUTO_PREFIX):].strip().lower()
    if not needle:
        return {"error": "capture.port 的 auto: 后缺少描述子串 "
                         "(如 auto:WCH-Link SERIAL)"}
    if list_ports is None:
        return {"error": "缺 pyserial: pip install pyserial "
                         "(capture.port 的 auto: 端口发现需要 pyserial)"}
    ports = list(list_ports.comports())
    hits = [p for p in ports
            if needle in f"{p.description or ''} {p.hwid or ''}".lower()]
    if not hits:
        avail = ", ".join(f"{p.device}({p.description})" for p in ports) or "<无端口>"
        return {"error": f"auto:{needle} 未匹配到端口; 当前端口: {avail}"}
    if len(hits) > 1:
        names = ", ".join(p.device for p in hits)
        return {"error": f"auto:{needle} 匹配到多个端口 ({names}); "
                         "请改用字面端口号"}
    return {"port": hits[0].device}
