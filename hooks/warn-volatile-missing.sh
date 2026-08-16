#!/bin/bash
# 警告级：ISR 共享变量缺 volatile 提醒 → exit 0
files=$(git diff --cached --name-only 2>/dev/null | grep -E '\.(c|h)$')
[ -z "$files" ] && files=$(git diff --name-only 2>/dev/null | grep -E '\.(c|h)$')
if [ -n "$files" ] && grep -ql 'ISR\|IRQHandler\|Callback\|interrupt' $files 2>/dev/null; then
  new_vars=$(git diff -U0 -- $files 2>/dev/null | grep '^\+' | grep -v '^+++' | grep -E '(static\s+)?(uint|int|float|char|bool)\w*\s+\w+\s*=' | grep -v 'volatile')
  if [ -n "$new_vars" ]; then
    echo " 提醒：新增变量可能与 ISR 共享，请确认是否需要 volatile。"
  fi
fi
exit 0
