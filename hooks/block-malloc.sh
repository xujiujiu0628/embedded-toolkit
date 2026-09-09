#!/bin/bash
# 阻断级：检测 malloc/free/calloc/realloc → exit 2
files=$(git diff --cached --name-only 2>/dev/null | grep -E '\.(c|h)$')
[ -z "$files" ] && files=$(git diff --name-only 2>/dev/null | grep -E '\.(c|h)$')
if [ -n "$files" ]; then
  # F-096: --cached 优先 (pre-commit 时刻 worktree==index, 旧单路 diff 恒空 → 恒放行); --cached 命中即拦, 未命中再查工作树
  if { git diff --cached -U0 -- $files 2>/dev/null; git diff -U0 -- $files 2>/dev/null; } | grep -nE '\bmalloc\b|\bfree\b|\bcalloc\b|\brealloc\b'; then
    echo ""
    echo "=============================================="
    echo " 铁律违反：动态内存分配"
    echo "   (malloc / free / calloc / realloc)"
    echo " 本项目禁止动态分配。请改用静态缓冲区。"
    echo "=============================================="
    exit 2
  fi
fi
exit 0
