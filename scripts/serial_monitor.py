"""串口实时文本监控"""

import argparse
import re
import signal
import sys
import time
from datetime import datetime

from serial_runtime import (
    connect_serial,          # F-156 (P2-1): 公共骨架 ②
    output_jsonl as output_json,  # F-156: JSON Lines 紧凑态收编 (字节不变)
    resolve_serial_config,   # F-156 (P2-1): 公共骨架 ①
    update_state_entry,
)

IDLE_FLUSH_SEC = 0.2


def error_exit(action, code, message, use_json):
    result = {"status": "error", "action": action, "error": {"code": code, "message": message}}
    if use_json:
        output_json(result)
    else:
        print(f"错误: {message}", file=sys.stderr)
    sys.exit(1)


def emit_line(text, cfg, args, include_re, exclude_re):
    if include_re:
        try:
            if not include_re.search(text):
                return False
        except Exception as e:
            # F-133/a: 过滤器异常 fail-closed — 旧 except pass 会把坏过滤器
            # 变成"全放行", 监控输出被污染
            print(f"[warn] include 过滤器异常, 该行跳过 (fail-closed): {e}",
                  file=sys.stderr)
            return False

    if exclude_re:
        try:
            if exclude_re.search(text):
                return False
        except Exception as e:
            print(f"[warn] exclude 过滤器异常, 该行跳过 (fail-closed): {e}",
                  file=sys.stderr)
            return False

    now = datetime.now().isoformat(timespec="milliseconds")
    if args.json:
        output_json({"timestamp": now, "port": cfg["port"], "baudrate": cfg["baudrate"], "text": text})
    else:
        prefix = f"[{now}] " if args.timestamp else ""
        print(f"{prefix}{text}")
    return True


def main():
    parser = argparse.ArgumentParser(description="串口实时文本监控")
    parser.add_argument("--port", help="串口号 (如 COM3)")
    parser.add_argument("--baudrate", type=int, help="波特率")
    parser.add_argument("--bytesize", type=int, help="数据位")
    parser.add_argument("--parity", help="校验位 (none/even/odd)")
    parser.add_argument("--stopbits", type=int, help="停止位")
    parser.add_argument("--encoding", help="编码")
    parser.add_argument("--timestamp", action="store_true", help="显示时间戳")
    parser.add_argument("--filter", help="正则过滤（仅显示匹配行）")
    parser.add_argument("--exclude", help="正则排除（隐藏匹配行）")
    parser.add_argument("--timeout", type=float, default=0, help="超时秒数，0=无限")
    parser.add_argument("--direct", action="store_true", help="直连真实串口，跳过 mux")
    parser.add_argument("--json", action="store_true", help="JSON Lines 输出")
    args = parser.parse_args()

    start_time = time.time()

    # 获取配置 + 写回 (F-156: 公共骨架 ①, 本地 85% 同文块删除)
    cfg = resolve_serial_config(
        args,
        fail=lambda code, message: error_exit("monitor", code, message, args.json))

    include_re = None
    exclude_re = None
    if args.filter:
        try:
            include_re = re.compile(args.filter)
        except re.error:
            error_exit("monitor", "bad_regex", f"无效正则: {args.filter}", args.json)
    if args.exclude:
        try:
            exclude_re = re.compile(args.exclude)
        except re.error:
            error_exit("monitor", "bad_regex", f"无效正则: {args.exclude}", args.json)

    # 开串口 + mux 警告 (F-156: 公共骨架 ②)
    ser = connect_serial(
        cfg, args,
        mux_warn="[mux] 已通过多路复用连接，请避免在 minicom 中同时写入以免串口数据冲突",
        fail=lambda code, message: error_exit("monitor", code, message, args.json))
    ser.timeout = 0.1

    line_count = 0
    running = True

    def on_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    encoding = cfg.get("encoding", "utf-8")
    text_buffer = ""
    last_data_at = 0.0
    skip_leading_lf = False

    try:
        while running:
            if args.timeout > 0 and (time.time() - start_time) >= args.timeout:
                break

            read_size = max(1, getattr(ser, "in_waiting", 0) or 1)
            raw = ser.read(read_size)
            if not raw:
                if text_buffer and last_data_at and (time.time() - last_data_at) >= IDLE_FLUSH_SEC:
                    if emit_line(text_buffer, cfg, args, include_re, exclude_re):
                        line_count += 1
                    text_buffer = ""
                continue

            try:
                chunk = raw.decode(encoding, errors="replace")
            except Exception:
                chunk = raw.hex()
            if skip_leading_lf and chunk.startswith("\n"):
                chunk = chunk[1:]
            skip_leading_lf = chunk.endswith("\r")
            text_buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
            last_data_at = time.time()

            parts = text_buffer.split("\n")
            if text_buffer.endswith("\n"):
                complete_lines = parts[:-1]
                text_buffer = ""
            else:
                complete_lines = parts[:-1]
                text_buffer = parts[-1]

            for text in complete_lines:
                if emit_line(text, cfg, args, include_re, exclude_re):
                    line_count += 1

    except Exception as e:
        error_exit("monitor", "read_error", str(e), args.json)
    finally:
        if text_buffer:
            if emit_line(text_buffer, cfg, args, include_re, exclude_re):
                line_count += 1
        ser.close()

    duration = round(time.time() - start_time, 1)
    summary = f"监控结束，共 {line_count} 行，耗时 {duration}s\n"
    sys.stderr.buffer.write(summary.encode("utf-8"))
    sys.stderr.buffer.flush()

    # 更新状态
    update_state_entry("last_observe", {
        "type": "serial_monitor",
        "port": cfg["port"],
        "baudrate": cfg["baudrate"],
        "lines": line_count,
        "duration_sec": duration,
    })


if __name__ == "__main__":
    main()
