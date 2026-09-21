#!/usr/bin/env python3
"""
cube_usercode.py — 从 CubeMX 生成的文件中提取/恢复应用代码
(F-131 工单 P2-2: 原 cube_to_keil.py 改名——本工具与 Keil 无关, 服务的是
 CubeMX 重生成时的 USER CODE 保全, 主链是 GCC; 引用方见 CHANGELOG F-131)

工作流：
  1. (可选) 修改前先跑: python cube_usercode.py --backup
     → 把当前所有 Core 文件备份到 .cube_backup/
  2. CubeMX 打开 test.ioc → 修改配置 → Generate Code
  3. 跑: python cube_usercode.py --restore
     → 从备份中提取应用代码 → 注入到 CubeMX 新生成的文件中
  4. GCC 编译验证 (verify.py / gcc_build.py)

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

# F-131: 工程根不再锚死"脚本在仓内"的 parents[1]——按 .workbench 标记从
# cwd 向上发现 (wb_common.find_project_root), 工具库/工程薄配置分离下依然可用。
# 懒解析 (import 期不 exit): extract_user_code/_dedent 等纯函数可被测试安全 import。
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from wb_common import find_project_root


def _project_root() -> Path:
    root = find_project_root(os.getcwd())
    if root is None:
        print("[!] 未找到工程根 (需含 .workbench/config.json) — 请在工程目录内运行本工具",
              file=sys.stderr)
        sys.exit(1)
    return Path(root)


PROJECT_ROOT = None  # 命令入口 (main/cmd_*) 首次调用时填充
CORE_SRC = CORE_INC = BACKUP_DIR = None


def _bind_roots() -> None:
    global PROJECT_ROOT, CORE_SRC, CORE_INC, BACKUP_DIR
    if PROJECT_ROOT is None:
        PROJECT_ROOT = _project_root()
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
    _bind_roots()
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


def _iter_code_chars(content, start=0):
    """逐个产出 content[start:] 中处于**代码态**的字符下标。

    跳过 C 字符串字面量、字符字面量、行注释与块注释（含反斜杠转义）。
    F-178 P1 (L-6, 09-19 审查): `_extract_loop_code` 旧版逐字符裸数花括号,
    被 `printf("}")`、`'{'`、含括号的注释欺骗 → while(1) 体被提前截断,
    用户代码静默丢尾。
    """
    i = start
    n = len(content)
    while i < n:
        c = content[i]
        if c == '/' and i + 1 < n and content[i + 1] == '/':
            j = content.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if c == '/' and i + 1 < n and content[i + 1] == '*':
            j = content.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '"' or c == "'":
            quote = c
            i += 1
            while i < n:
                if content[i] == '\\':
                    i += 2
                    continue
                if content[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        yield i
        i += 1


def _extract_loop_code(content):
    """从自定义 main.c 中提取 while(1) { ... } 内部的代码。"""
    loop_match = re.search(r'^\s*while\s*\(\s*1\s*\)\s*\{', content, re.MULTILINE)
    if not loop_match:
        return ""

    # 从 while(1) { 后面开始，找匹配的 }（只在代码态计花括号 — L-6）
    start = loop_match.end()
    depth = 1
    end = len(content) - 1   # 花括号未闭合时保持旧行为
    for i in _iter_code_chars(content, start):
        c = content[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    loop_body = content[start:end].strip()
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


def _commit_restore_plan(plan):
    """把 [(path, 新内容)] 统一落盘; 任一步失败回滚, 原文件保持不动。

    F-178 (WB-20260920-04, H-2) 两段式:
      ① 先给**每个**目标写同目录临时文件 —— 这一段落败时一个原文件都没动;
      ② 再逐个 os.replace 原子替换 (替换前留 .bak 作为回滚源) —— 这一段
         落败时用 .bak 把已替换者还原。
    返回 (rc, 已替换的 path 列表, 错误消息); rc=0 时列表按落盘顺序。
    """
    staged = []   # [(target, tmp)]
    try:
        for target, text in plan:
            tmp = target.with_name(target.name + ".restore.tmp")
            tmp.write_text(text, encoding='utf-8', errors='replace')
            staged.append((target, tmp))
    except OSError as e:
        for _target, tmp in staged:
            try:
                tmp.unlink()
            except OSError:
                pass
        return 1, [], f"[!] 恢复失败 (临时文件阶段), 原文件未改动: {e}"

    replaced = []   # [(target, bak)]
    for target, tmp in staged:
        bak = target.with_suffix(target.suffix + '.bak')
        try:
            shutil.copy2(target, bak)
            os.replace(tmp, target)
        except OSError as e:
            for t_done, b_done in replaced:
                try:
                    shutil.copy2(b_done, t_done)
                except OSError:
                    pass
            for _target, tmp2 in staged:
                try:
                    tmp2.unlink()
                except OSError:
                    pass
            return 1, [], (f"[!] 恢复失败 ({target.name} 落盘阶段), "
                           f"已回滚, 原文件保持不动: {e}")
        replaced.append((target, bak))
    return 0, [t for t, _b in replaced], ""


def cmd_backup():
    """备份当前 CubeMX 生成文件到 .cube_backup/

    F-178 (WB-20260920-04, M-10) 原子化: 先写临时目录, 全部复制成功后再
    整体交换。旧实现"先 rmtree 旧备份再复制"非原子 —— 复制中途失败
    (Windows 上工程文件被编辑器/Keil 占用是常态) 即旧备份已灭、新备份不全,
    而用户正处在"马上要跑 CubeMX"的最危险时点。
    """
    _bind_roots()
    files = find_cubemx_files()
    if not files:
        print("[!] 没有找到 CubeMX 生成的文件（Core/Src, Core/Inc）")
        return 1

    staging = BACKUP_DIR.with_name(BACKUP_DIR.name + ".staging")
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for f in files:
            rel = f.relative_to(PROJECT_ROOT)
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    except OSError as e:
        shutil.rmtree(staging, ignore_errors=True)
        print(f"[!] 备份失败, 旧备份保持不动: {e}", file=sys.stderr)
        return 1

    # 交换: 旧备份先让位到 .old (失败可原位挪回), 再让新备份上位。
    old = BACKUP_DIR.with_name(BACKUP_DIR.name + ".old")
    try:
        if old.exists():
            shutil.rmtree(old)
        if BACKUP_DIR.exists():
            os.replace(BACKUP_DIR, old)
        os.replace(staging, BACKUP_DIR)
    except OSError as e:
        if not BACKUP_DIR.exists() and old.exists():
            try:
                os.replace(old, BACKUP_DIR)
            except OSError:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        print(f"[!] 备份失败, 旧备份保持不动: {e}", file=sys.stderr)
        return 1
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)

    # 同时备份整个 Core 目录的完整快照
    for f in files:
        blocks = extract_user_code(f)
        if any(b.strip() for b in blocks.values()):
            # 有非空 USER CODE 内容
            pass

    print(f"[OK] 已备份 {len(files)} 个文件到 {BACKUP_DIR}")
    return 0


def cmd_restore():
    """从备份恢复应用代码到 CubeMX 新生成的文件中

    F-178 (WB-20260920-04, H-2) 两处修复:
      ① 注入改 lambda 拼接 —— 旧实现把旧文件源码原文拼进 re.sub 的
         replacement 模板, 反斜杠被模板二次解释: `printf("hi\\r\\n")` 的
         \\r\\n 变真实 CR/LF (C 字符串被拆断, 编译必炸)、`'\\0'` 变真实 NUL
         字节、正文含 \\d/\\s 直接抛 re.PatternError 使 restore 崩溃。
      ② 事务化 —— 全部文件先在内存组装, 再统一落盘; 任一文件失败回滚,
         原文件一个都不许动 (旧实现逐文件即时写, 前几个文件已写坏而末尾
         照报 "[OK] 恢复完成")。
    """
    _bind_roots()
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
    plan = []   # F-178 (H-2): 阶段一产物 [(Path, 新内容)] — 全量内存组装

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
            # 当前文件没有 USER CODE 标记 → 无法定位注入口。
            # F-178 P1 (L-6, 09-19 审查): 旧版对 main.c 走 `pass  # fall through
            # to conflict`, 注释说要落 conflict 却从不记录 —— 该文件既不进
            # restored 也不进 conflicts, 三个计数全部蒸发, 用户只看到
            # "[OK] 恢复完成" 以为没丢代码。现按实情报 conflict。
            if rel.name == "main.c" and "USER CODE BEGIN" in old_content:
                conflicts.append(
                    f"{rel} (旧版有 USER CODE 块, 新文件无标记 — 无法自动注入)")
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
        # F-178 (H-2): replacement 必须走**函数形式** —— 用户代码原文里的
        # 反斜杠是 C 转义字面量, 交给 re.sub 的模板解释会被吃掉或抛
        # PatternError。lambda 拼接让原文逐字节通行。
        new_content = current_content
        for name, code in old_blocks.items():
            if not code.strip():
                continue  # 空的，跳过

            # 找到当前文件中对应的 USER CODE 块
            pattern = rf'(/\*\s*USER CODE BEGIN\s+{name}\s*\*/)(.*?)(/\*\s*USER CODE END\s+{name}\s*\*/)'
            new_content = re.sub(
                pattern,
                lambda m, _code=code: m.group(1) + "\n" + _code + m.group(3),
                new_content, count=1, flags=re.DOTALL)

        if new_content != current_content:
            plan.append((current, new_content))
        else:
            skipped += 1

    # ── 阶段二: 统一落盘 (F-178/H-2: 任一失败回滚, 原文件保持不动) ──
    if plan:
        rc, done, err = _commit_restore_plan(plan)
        if rc != 0:
            print(err, file=sys.stderr)
            return rc
        restored = len(done)
        for target in done:
            print(f"  [RESTORED] {target.relative_to(PROJECT_ROOT)}")

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
    _bind_roots()
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
                    print("    → CubeMX 新增了内容")
                elif old_code and not new_code:
                    print("    → CubeMX 清空了此区块!")

    return 0


def main():
    parser = argparse.ArgumentParser(description="CubeMX USER CODE 迁移工具 (GCC 主链)")
    parser.add_argument('action', nargs='?', default='restore',
                        choices=['backup', 'restore', 'diff'],
                        help='backup: 备份当前代码 | restore: 恢复应用代码 | diff: 对比差异')
    args = parser.parse_args()

    _bind_roots()  # F-131: 先解析工程根 (发现失败体面 exit 1), 再切 cwd
    os.chdir(PROJECT_ROOT)

    if args.action == 'backup':
        return cmd_backup()
    elif args.action == 'restore':
        return cmd_restore()
    elif args.action == 'diff':
        return cmd_diff()


if __name__ == '__main__':
    sys.exit(main())
