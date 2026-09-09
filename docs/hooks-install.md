# hooks/ 安装与使用说明

> 三条 C 代码铁律的机器检查（git hook 脚本）。设计给**固件工程侧**使用
> （app 所在仓），也可挂在本 toolkit 仓。详见主 README「项目结构」节。

## 三条铁律

| 脚本 | 级别 | 判据 | 退出码 |
|---|---|---|---|
| `block-malloc.sh` | 阻断 | staged/工作树 diff 出现 `malloc` / `free` / `calloc` / `realloc`（词边界） | 2（拒收） |
| `block-hal-delay-in-logic.sh` | 阻断 | 业务代码出现 `HAL_Delay`（逻辑层忙等） | 2（拒收） |
| `warn-volatile-missing.sh` | 提醒 | ISR 相关文件新增非 `volatile` 变量 | 0（仅打印提醒） |

## 安装（固件工程侧）

hooks 目录可以整体拷进工程，或直接引用本仓路径。

### 方式 A：拷贝为 git hook（最简单）

```bash
# 在你的固件工程根目录
mkdir -p .git/hooks
cp <toolkit 根>/hooks/block-malloc.sh .git/hooks/pre-commit
cp <toolkit 根>/hooks/block-hal-delay-in-logic.sh .git/hooks/pre-commit-block2   # 见下方"组合"
chmod +x .git/hooks/pre-commit
```

git 的 pre-commit 只认一个文件名；三条脚本要同时生效请用**方式 B**。

### 方式 B：core.hooksPath + 分发脚本（推荐）

```bash
# 1. 工程里建 hooks.d 目录，拷入三条脚本
mkdir -p .githooks
cp <toolkit 根>/hooks/*.sh .githooks/

# 2. 写一个分发器 .githooks/pre-commit
cat > .githooks/pre-commit <<'DISPATCH'
#!/bin/bash
rc=0
for h in "$(dirname "$0")"/block-*.sh "$(dirname "$0")"/warn-*.sh; do
  [ -f "$h" ] || continue
  bash "$h" || rc=$?
done
exit $rc
DISPATCH
chmod +x .githooks/pre-commit

# 3. 让 git 使用该目录
git config core.hooksPath .githooks
```

阻断级脚本 exit 2 会让分发器以非零结束 → commit 被拒；提醒级恒 exit 0 不拦截。

## 已知限制（F-096 登记，修复待拍板）

**staged 且工作树一致时，三条脚本当前不会检查 staged 内容**（判据用
`git diff -U0 -- <files>`，比对的是工作树 vs index，pre-commit 时刻该 diff
通常为空）。行为探针见 `tests/test_hooks_behavior.py` 的
`CanaryDetectionGapTests`。在缺陷修复前，建议把 hook 挂到
**pre-commit 之外的场景**（如 CI 上对整个 diff 跑）或修改判据加 `--cached`。

## 测试

```bash
python -m unittest tests.test_hooks_behavior -v
```
