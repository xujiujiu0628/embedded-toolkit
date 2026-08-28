# legacy/keil — AI↔Keil 自动化桥（退役留门区）

2026-08-28 Keil 从 AI 工作台退役定案：**D:\KEIL5 软件保留**（非 AI 项目仍手工使用），
但 AI 自动化链路 100% GCC 默认。本目录是当时拆桥又留门的产物——
不主动维护、不进任何默认路径，但**随时可以原样唤起**。

## 本区文件

| 文件 | 作用 |
|---|---|
| keil_build.py | 驱动 UV4.exe 做 build/rebuild/clean/flash（flash 走 Keil 自带 downloader，非 OpenOCD），JSON 契约与 gcc_build 同构 |
| keil_analyze.py | 解析 ARMCC/L6xxx 编译日志，匹配 `data/keil-error-db.json` 输出结构化诊断 |
| keil_project.py | .uvprojx/.uvmpw 扫描与 Target 枚举（退役前已是零调用孤儿，一并入库） |

三者共用 `scripts/wb_runtime.py`（中性化共享运行时）与 `scripts/config/../config/keil.json`、
`machine.json:uv4_exe`——这些**主干资产不因退役而移动**。

## 唤起方法

工程 `.workbench/config.json` 显式声明：

```json
{
  "builder": "keil",
  "keil": { "project": "xxx.uvprojx", "target": "<TargetName>", "log_dir": ".workbench/build" }
}
```

之后 `verify.py` 全链（build→analyze→flash→capture→verify）照跑，无需其他改动。
缺省不写 `builder` 时走 gcc——默认值已于 2026-08-28 翻转（见 verify.py:841）。

## 已知限制

- `--rebuild` 旗标仅 gcc 后端支持（keil 路径会显式报错，不会静默）
- 归档工程 `stm32f103-blink`（archive zip 内）的 `.vscode/tasks.json` "编译 (Keil)"
  按钮指向旧路径 `scripts/keil_build.py` 且硬编码 `--uv4`——解包即用会挂，属预期，
  归档区不维护；真要复活改一行路径即可
- 本区脚本的修改政策：只修致命 bug，不做功能演进
