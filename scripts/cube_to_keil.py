#!/usr/bin/env python3
"""
cube_to_keil.py — 从 CubeMX 生成的文件中提取/恢复应用代码

工作流：
  1. (可选) 修改前先跑: python cube_to_keil.py --backup
     → 把当前所有 Core 文件备份到 .cube_backup/
  2. CubeMX 打开 test.ioc → 修改配置 → Generate Code
  3. 跑: python cube_to_keil.py --restore
     → 从备份中提取应用代码 → 注入到 CubeMX 新生成的文件中
  4. Keil 编译验证

原理：
  CubeMX 生成的文件中，只有 USER CODE BEGIN/END 之间的区域是安全的。
  本脚本把你在这些区域之外写的代码保存下来，等 CubeMX 覆盖后恢复回去。
"""

import os
import re
import sys
import shutil
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORE_SRC = PROJECT_ROOT / "Core" / "Src"
CORE_INC = PROJECT_ROOT / "Core" / "Inc"
BACKUP_DIR = PROJECT_ROOT / ".cube_backup"

# ── 已知的 CubeMX 生成文件 ──
CUBEMX_FILES = [
    "main.c", "main.h",
    "gpio.c", "gpio.h",
    "i2c.c", "i2c.h",
    "usart.c", "usart.h",
    "tim.c", "tim.h",
    "spi.c", "spi.h",
    "adc.c", "adc.h",
    "dma.c", "dma.h",
    "stm32f1xx_it.c", "stm32f1xx_it.h",
    "stm32f1xx_hal_conf.h",
    "stm32f1xx_hal_msp.c",
]

# ── USER CODE 标记模式 ──
USER_CODE_RE = re.compile(
    r'(/\*\s*USER CODE BEGIN\s+(\w+)\s*\*/)'
    r'(.*?)'
    r'(/\*\s*USER CODE END\s+\2\s*\*/)',
    re.DOTALL
)


def find_cubemx_files():
    """扫描 Core/Inc 和 Core/Src 中存在的 CubeMX 文件"""
    found = []
    for fname in CUBEMX_FILES:
        for base in [CORE_SRC, CORE_INC]:
            path = base / fname
            if path.exists():
                found.append(path)
    return sorted(set(found))


def extract_user_code(filepath):
    """提取文件中所有 USER CODE 块 → {block_name: content}"""
    try:
        content = filepath.read_text(encoding='ascii')
    except UnicodeDecodeError:
        content = filepath.read_text(encoding='utf-8', errors='replace')

    blocks = {}
    for match in USER_CODE_RE.finditer(content):
        name = match.group(2)
        code = match.group(3)
        blocks[name] = code
    return blocks


def _extract_init_code(content):
    """
    从自定义 main.c 中提取 MX_*_Init() 之后、while(1) 之前的初始化代码。
    返回去掉缩进的内容。
    """
    # 找到最后一次 MX_*_Init 调用的位置
    mx_calls = list(re.finditer(r'^\s*MX_\w+_Init\s*\(\s*\)\s*;', content, re.MULTILINE))
    if not mx_calls:
        return ""

    last_mx_end = mx_calls[-1].end()

    # 找到 while(1) 的位置
    loop_match = re.search(r'^\s*while\s*\(\s*1\s*\)', content[last_mx_end:], re.MULTILINE)
    if not loop_match:
        return ""

    init_section_end = last_mx_end + loop_match.start()

    # 提取中间的代码
    init_code = content[last_mx_end:init_section_end].strip()
    # 去掉缩进以便注入
    return _dedent(init_code)


def _extract_loop_code(content):
    """从自定义 main.c 中提取 while(1) { ... } 内部的代码。"""
    loop_match = re.search(r'^\s*while\s*\(\s*1\s*\)\s*\{', content, re.MULTILINE)
    if not loop_match:
        return ""

    # 从 while(1) { 后面开始，找匹配的 }
    start = loop_match.end()
    depth = 1
    i = start
    while i < len(content) and depth > 0:
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1

    loop_body = content[start:i-1].strip()
    return _dedent(loop_body)


def _extract_header_code(content):
    """从自定义 main.c 中提取 #include 和 semihosting 设置代码。"""
    # 找到 int main( 或 void main(  之前的非标准 includes/fputc/macro 代码
    main_match = re.search(r'^(int|void)\s+main\s*\(', content, re.MULTILINE)
    if not main_match:
        return ""

    preamble = content[:main_match.start()]

    # 提取 CubeMX 标准 includes 之外的内容
    extra = []
    for line in preamble.split('\n'):
        stripped = line.strip()
        # 跳过标准 CubeMX includes 和注释头
        if any(stripped.startswith(p) for p in [
            '#include "main.h"', '#include "i2c.h"', '#include "tim.h"',
            '#include "gpio.h"', '#include "usart.h"',
            '#include "spi.h"', '#include "dma.h"',
            '/* =', '*/', ' *', '/* USER CODE',
        ]):
            continue
        if stripped.startswith('#include') or 'semihost' in stripped.lower():
            extra.append(line)
        elif stripped.startswith('#define') and ('DHCSR' in stripped or 'fputc' in stripped):
            extra.append(line)
        elif 'extern void semihost' in stripped or 'int fputc' in stripped:
            extra.append(line)

    if extra:
        return '\n'.join(extra) + '\n'
    return ""


def _dedent(text):
    """去掉共同的缩进前缀。"""
    lines = text.split('\n')
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text

    min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
    if min_indent > 0:
        lines = [l[min_indent:] if l.strip() else l for l in lines]
    return '\n'.join(lines)


def cmd_backup():
    """备份当前 CubeMX 生成文件到 .cube_backup/"""
    files = find_cubemx_files()
    if not files:
        print("[!] 没有找到 CubeMX 生成的文件（Core/Src, Core/Inc）")
        return 1

    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    BACKUP_DIR.mkdir(parents=True)

    for f in files:
        rel = f.relative_to(PROJECT_ROOT)
        dest = BACKUP_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)

    # 同时备份整个 Core 目录的完整快照
    for f in files:
        blocks = extract_user_code(f)
        if any(b.strip() for b in blocks.values()):
            # 有非空 USER CODE 内容
            pass

    print(f"[OK] 已备份 {len(files)} 个文件到 {BACKUP_DIR}")
    return 0


def cmd_restore():
    """从备份恢复应用代码到 CubeMX 新生成的文件中"""
    if not BACKUP_DIR.exists():
        print("[!] 没有找到备份目录。请先运行 --backup")
        return 1

    files = find_cubemx_files()
    if not files:
        print("[!] 没有找到 CubeMX 生成的文件")
        return 1

    restored = 0
    skipped = 0
    conflicts = []

    for current in files:
        rel = current.relative_to(PROJECT_ROOT)
        backup = BACKUP_DIR / rel

        if not backup.exists():
            skipped += 1
            continue

        # 提取备份中的用户代码
        old_blocks = extract_user_code(backup)
        old_content = backup.read_text(encoding='utf-8', errors='replace')
        # 提取当前（CubeMX 新生成）文件的结构
        current_content = current.read_text(encoding='utf-8', errors='replace')

        # 检查当前文件是否有 USER CODE 标记
        current_blocks = {}
        for match in USER_CODE_RE.finditer(current_content):
            current_blocks[match.group(2)] = match

        if not current_blocks:
            # 当前文件没有 USER CODE 标记 → 尝试 main.c 智能迁移
            if rel.name == "main.c" and "USER CODE BEGIN" in old_content:
                # 旧 main.c 有 USER CODE 块但新 CubeMX 版没有 → 反向注入
                pass  # fall through to conflict
            else:
                conflicts.append(str(rel))
                continue

        # main.c 特殊处理: 旧文件完全自定义 → 提取关键区段注入新模板
        if rel.name == "main.c" and not old_blocks and current_blocks:
            # 旧 main.c 没有 USER CODE 标记（完全自定义）
            # 新 main.c（CubeMX 生成）有标准 USER CODE 结构
            # → 从旧文件中智能提取 init 代码和 loop 代码
            init_code = _extract_init_code(old_content)
            loop_code = _extract_loop_code(old_content)
            header_code = _extract_header_code(old_content)

            old_blocks = {}
            if header_code:
                old_blocks['Includes'] = header_code
            if init_code:
                old_blocks['2'] = "\n" + init_code + "\n  "
            if loop_code:
                old_blocks['3'] = "\n" + loop_code + "\n    "

            if not init_code and not loop_code:
                conflicts.append(str(rel) + " (无法自动提取 init/loop 代码)")
                continue

        # 注入用户代码：把旧文件里每个 USER CODE 块的内容填入新文件的对应位置
        new_content = current_content
        for name, code in old_blocks.items():
            if not code.strip():
                continue  # 空的，跳过

            # 找到当前文件中对应的 USER CODE 块
            pattern = rf'(/\*\s*USER CODE BEGIN\s+{name}\s*\*/)(.*?)(/\*\s*USER CODE END\s+{name}\s*\*/)'
            replacement = rf'\1\n{code}\3'
            new_content = re.sub(pattern, replacement, new_content, count=1, flags=re.DOTALL)

        if new_content != current_content:
            # 备份当前文件以防万一
            bak = current.with_suffix(current.suffix + '.bak')
            shutil.copy2(current, bak)

            # 写入
            current.write_text(new_content, encoding='utf-8', errors='replace')
            restored += 1
            print(f"  [RESTORED] {rel}")
        else:
            skipped += 1

    # 报告
    print(f"\n[OK] 恢复完成: {restored} 个文件已更新, {skipped} 个跳过")
    if conflicts:
        print(f"[!] {len(conflicts)} 个文件无 USER CODE 标记（需手动处理）:")
        for c in conflicts:
            print(f"    - {c}")
        print("  这些文件可能已被完全自定义。如需迁移，请手动对比 .cube_backup/ 中的旧版本。")

    return 0


def cmd_diff():
    """对比备份和当前文件的差异"""
    if not BACKUP_DIR.exists():
        print("[!] 没有找到备份目录")
        return 1

    for current in find_cubemx_files():
        rel = current.relative_to(PROJECT_ROOT)
        backup = BACKUP_DIR / rel
        if not backup.exists():
            print(f"  [NEW] {rel}")
            continue

        old_blocks = extract_user_code(backup)
        new_blocks = extract_user_code(current)

        for name in set(old_blocks) | set(new_blocks):
            old_code = old_blocks.get(name, "").strip()
            new_code = new_blocks.get(name, "").strip()
            if old_code != new_code:
                print(f"  [CHANGED] {rel} -> USER CODE {name}")
                if new_code and not old_code:
                    print(f"    → CubeMX 新增了内容")
                elif old_code and not new_code:
                    print(f"    → CubeMX 清空了此区块!")

    return 0


def main():
    parser = argparse.ArgumentParser(description="CubeMX → Keil 代码迁移工具")
    parser.add_argument('action', nargs='?', default='restore',
                        choices=['backup', 'restore', 'diff'],
                        help='backup: 备份当前代码 | restore: 恢复应用代码 | diff: 对比差异')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    if args.action == 'backup':
        return cmd_backup()
    elif args.action == 'restore':
        return cmd_restore()
    elif args.action == 'diff':
        return cmd_diff()


if __name__ == '__main__':
    sys.exit(main())
