#!/bin/bash
# 阻断级：检测业务代码中的 HAL_Delay() → exit 2
files=$(git diff --cached --name-only 2>/dev/null | grep -E '\.(c|h)$')
[ -z "$files" ] && files=$(git diff --name-only 2>/dev/null | grep -E '\.(c|h)$')
if [ -n "$files" ]; then
  added=$(git diff -U0 -- $files 2>/dev/null | grep '^\+[^+]' | grep -v '^\+//' | grep -v '^\+/\*')
  if echo "$added" | grep -q 'HAL_Delay'; then
    echo ""
    echo "=============================================="
    echo " 铁律违反：HAL_Delay() 阻塞调用"
    echo " 请改用 HAL_GetTick() + 非阻塞状态机。"
    echo "=============================================="
    exit 2
  fi
fi
exit 0
