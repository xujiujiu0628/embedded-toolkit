# scripts/legacy

2026-09-05 (F-067b) 起, 本目录保留为空。

## 历史

- 2026-08-28 Keil 从 AI 工作台退役定案: 脚本沉到 `scripts/legacy/keil/`
- 2026-09-05 Keil 退役区完整拆 archive (`<d-claude-root>/archive/
  embedded-toolkit-keil-legacy-20260905/`), `scripts/legacy/keil/`
  随之空出

## 现状

- 目录保留: 不删, 留给未来其他工具退役时用
- 目录豁免: coverage_lint 默认不再豁免 `legacy/` 子树
  (Keil 退役区拆 archive 后已无受跟踪文件; 未来再有工具置入时,
  请同步加回 `DIR_EXEMPT = {"legacy"}` 避免误报)

## 唤起 Keil 退役区

> 下文 `<d-claude-root>` 是维护者工作区根的占位符（本机路径不公开, F-089）；
> 使用时替换为你本机的 toolkit 工作区根目录。

如需 Keil 构建链 (builder="keil" 工程), 从 archive 物理副本拷回:

```bash
cp <d-claude-root>/archive/embedded-toolkit-keil-legacy-20260905/scripts_legacy_keil/keil_*.py \
   <d-claude-root>/embedded-toolkit/scripts/legacy/keil/
cp <d-claude-root>/archive/embedded-toolkit-keil-legacy-20260905/keil-error-db.json \
   <d-claude-root>/embedded-toolkit/data/
cp <d-claude-root>/archive/embedded-toolkit-keil-legacy-20260905/keil.json \
   <d-claude-root>/embedded-toolkit/config/
```

或通过环境变量指 archive 路径 (verify.py 启动检测, 不在则清晰报错):
```bash
EMBEDDED_TOOLKIT_KEIL_ARCHIVE=<d-claude-root>/archive/embedded-toolkit-keil-legacy-20260905 \
  python scripts/verify.py --project <工程>
```

详细唤起说明见 archive README: `<d-claude-root>/archive/embedded-toolkit-keil-legacy-20260905/README.md`
