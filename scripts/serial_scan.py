"""串口扫描：枚举系统串口并展示设备信息"""

import argparse
import json
import sys
from pathlib import Path

from serial_runtime import get_mux_info, output_json, scan_serial_ports

COMMON_DEVICES_PATH = Path(__file__).parent.parent / "data" / "common_devices.json"


def load_chip_map():
    """加载 VID/PID -> 芯片名称映射"""
    chip_map = {}
    try:
        data = json.loads(COMMON_DEVICES_PATH.read_text(encoding="utf-8"))
        for entry in data.get("usb_serial_chips", []):
            key = (entry["vid"].upper(), entry["pid"].upper())
            chip_map[key] = entry["name"]
    except Exception:
        pass
    return chip_map


def scan_ports(filter_keyword=None):
    """F-156 (P2-1): 复用 serial_runtime.scan_serial_ports — 本地 40 行
    逐字副本删除 (含 load_chip_map 重复逻辑; 本函数保留 load_chip_map 供
    test_zero_cov_finish 钉)。错误态旧版 ports=None, 共享版 [] — main 只判
    err, 行为不变。"""
    return scan_serial_ports(filter_keyword)


def main():
    parser = argparse.ArgumentParser(description="扫描系统串口")
    parser.add_argument("--filter", help="按关键词过滤")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    ports, err = scan_ports(args.filter)

    if err:
        result = {"status": "error", "action": "scan", "error": {"code": "import_error", "message": err}}
        if args.json:
            output_json(result)
        else:
            print(f"错误: {err}", file=sys.stderr)
        sys.exit(1)

    mux_info = get_mux_info()
    result = {
        "status": "ok",
        "action": "scan",
        "summary": f"发现 {len(ports)} 个串口",
        "details": {"ports": ports},
    }
    if mux_info:
        result["details"]["mux"] = {
            "running": True,
            "vserial": mux_info["vserial"],
            "tcp_port": mux_info["tcp_port"],
            "real_port": mux_info["real_port"],
        }
        result["summary"] += f" (Mux 运行中: {mux_info['vserial']})"

    if args.json:
        output_json(result)
    else:
        if not ports:
            print("未发现可用串口")
        else:
            print(f"发现 {len(ports)} 个串口:\n")
            for p in ports:
                chip = f" [{p['chip']}]" if p["chip"] else ""
                vid_pid = f" (VID:{p['vid']} PID:{p['pid']})" if p["vid"] else ""
                print(f"  {p['port']}: {p['description']}{chip}{vid_pid}")
        if mux_info:
            print(f"\nMux 运行中: {mux_info['real_port']} -> TCP:{mux_info['tcp_port']} -> PTY:{mux_info['vserial']}")


if __name__ == "__main__":
    main()
