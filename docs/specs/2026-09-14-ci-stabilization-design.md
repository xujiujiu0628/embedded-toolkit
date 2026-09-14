# CI 稳定化小单设计（F-164/F-165）

> 日期：2026-09-14 ｜ 分支：`ci-stabilize-20260914`（自 master `fc8fc7a` 起）｜ 状态：设计已获维护者批准
> 来源：F-162 首跑 0912 CI 暴露的两笔预置债（README 已知遗留 2026-09-13 登记行），
> 记忆账本：`embedded-toolkit-ticket-2026-09-13`。

## 目标

让 master 的 CI badge 复绿，并根治两笔已登记预置债：

1. **F-164**：`gcc_build.py` 构建预检 Windows 硬编码 → ubuntu runner 上 sim-demo job 必红（errors=-1 速败）。
2. **F-165**：两枚墙钟依赖计时钉（`test_state_write_lock` / `test_runtime_contract`）在 CI 慢速 runner 上抖动 → unittest 四象限 + coverage-gate 红。

## 已实证的根因（设计依据，实施者可直接采信但须复核行号）

- **F-164**：`scripts/gcc_build.py:209` 预检 `(Path(machine["gcc_path"]) / "arm-none-eabi-gcc.exe").exists()` 写死 `.exe`——ubuntu 上二进制无后缀，预检必败；失败返回 precheck error 无 metrics → verify 侧 `errors:-1`、约 190ms 速败。`make_exe` 检查（211 行）`Path(...).exists()` 对裸命令名误拦（CI 恰好写了绝对路径 `/usr/bin/make` 才躲过）。本地（Windows）全绿与远端红的矛盾由此完全解释。
- **F-165a**：`scripts/serial_runtime.py:151-160` `make_timing` 用墙钟（`datetime.now().timestamp() - start_time`）且 `int()` 截断；`tests/test_runtime_contract.py:126-127` 以 `start_time=time.time()-1.0` 喂名义 1 秒再断言 `elapsed_ms>=1000`——CI runner NTP 微调使墙钟回拨几 ms 即得 999。断言实际在赌"时钟单调 + 无截断负漂"，不成立。
- **F-165b**：`scripts/runtime_common.py:160-209` `state_write_lock` 降解路径依赖真实 `sleep(0.05)` 轮询 + `time.time()` deadline；`tests/test_state_write_lock.py:98-119` 用伪造 pid 造"新鲜他锁"再断言 `elapsed>=0.4`——ubuntu 上 pid 空间差异与调度噪声令判活结果、轮询节奏均不确定。

## 第 1 节 F-164：gcc_build 预检平台化（最小 A 档）

### 改动

`scripts/gcc_build.py` 预检两处（约 209-211 行）统一改走 `shutil.which`：

```python
gcc_ok = shutil.which("arm-none-eabi-gcc", path=machine.get("gcc_path") or "")
# nt 下 which 自动补 PATHEXT(.exe); POSIX 查无后缀可执行位
make_ok = bool(shutil.which(machine.get("make_exe") or ""))
# 裸名查 PATH; 带目录的候选名 which 走存在+可执行判定, 绝对路径同样适用
```

- 预检错误措辞不变（`gcc_path invalid in machine.json: ...` / `make_exe invalid in machine.json: ...`），仅判定式替换。
- `shutil` 若模块未 import 则加入 import 块（保持 F-022 风格分组）。
- Windows 行为等价性论证：`which` 对含分隔符的候选名检查"存在且 `os.X_OK`"；Windows 上 `.exe` 判定由 `PATHEXT` 分支覆盖（`which("arm-none-eabi-gcc", path=d)` 在 nt 上会试 `d/arm-none-eabi-gcc.exe`）。

### 测试

`tests/test_gcc_build.py` 补 4 枚 mock/形态钉：

1. `shutil.which` 返回 None（gcc 侧）→ 预检报 `gcc_path invalid`（构造 machine 含 gcc_path）；
2. `shutil.which` 返回 None（make 侧）→ 预检报 `make_exe invalid`；
3. which 双命中 → 预检放行（走到后续，可 mock `_run_make` 或断言不再出 precheck 错误）；
4. 形态钉（F-159 AST 法）：`gcc_build.py` 预检函数源码内不再出现 `"arm-none-eabi-gcc.exe"` 字面量。

### 范围外（明确不做）

- `examples/sim-demo/.workbench/config.json` 的 `"log_dir": ".workbench\\build"` 反斜杠：ubuntu 上产生怪名目录但不阻塞构建，YAGNI 不动、不登记。
- 全仓 `.exe` 硬编码大审计（B 档）：本单只修 build 预检链，其余留 F-031 债框架下另议。

## 第 2 节 F-165：两枚计时钉去墙钟化（注入假时钟）

### 2a. `test_runtime_contract.test_make_timing_is_name_collision_not_dup`

- patch `serial_runtime` 命名空间的 `datetime`（注入固定起点 `T0` 与 `now()=T0+1.0`），断言 `elapsed_ms == 1000` **逐字零容差**；
- 键形状钉（`{"started_at","finished_at","elapsed_ms"}`）与 wb 版透传钉（`make_timing("2026-09-01T00:00:00+08:00", 123)` 两键逐字）保持；
- 该测试不再产生任何真实墙钟依赖。

### 2b. `test_state_write_lock.test_timeout_degrades_honestly`

- patch `runtime_common` 的 `time`（`time()` 走虚拟钟；`sleep(s)` 把虚拟钟推进 `s` 并计次）与 `_state_lock_is_stale`（返回 False，隔离"降解"契约——陈旧锁偷取由既有他钉负责，实施时确认其在场，缺则补一枚最小钉）；
- 断言：①上下文最终正常放行（yield 恰好一次进入）；②stderr 含"降级"告警；③sleep 轮询次数 ≈ timeout/0.05（虚拟钟下精确，可断等式）；④**外来锁文件内容未被改写且结束时仍在场**（finally 只在 acquired=True 时 unlink，降解路径不得删他人锁——这是既有语义 `runtime_common.py:201-206` 的行为钉）；
- 全程零真实等待。

### 判据边界

- 只动测试文件与（若 2b 需要）极小的可注入性重构；**不放宽任何既有语义**——注入假时钟后钉住的是"行为顺序与形态"，比墙钟版更强。
- 若实施发现 `time`/`datetime` patch 点位与模块内引用方式不兼容（如 `from time import sleep` 形态），在对应模块命名空间上打补丁即可，不改生产代码结构；确需生产代码让路时报 DONE_WITH_CONCERNS。

## 第 3 节 验收、流程与销账

- **账目**：F-164（`fix+test`：gcc_build.py / test_gcc_build.py / README / CHANGELOG）与 F-165（`test`：两测试文件 / README / CHANGELOG）分两笔记；README 已知遗留两笔预置债条目改写"已闭合"（append 式订正）。
- **本地门禁**：全量 unittest 绿（853+新钉）+ ruff 零违规 + coverage 棘轮不降 + F-089 卫生。
- **远端销账（唯一终判）**：新 PR（`ci-stabilize-20260914` → master）触发 CI，**全绿**（unittest×4、coverage-gate、coverage-lint、lint、syntax-smoke、sim-demo）方销账；"Sim Verify Results" reporter check 照常在场（F-162 通道复用，顺带回归验证）。
- **止损条款**：F-164 修复后 sim-demo 若转在 **capture 段**红（ubuntu apt qemu 8.2 vs 本机 11.1 行为差），根因定位到即停：CHANGELOG 记"F-164 闭合预检债；sim-demo 残余红点=capture 平台差，新预置债登记"，README 增一条，本单不强行修 qemu 版本差。
- **流程**：brainstorming（本文）→ writing-plans → subagent-driven-development（每任务独立审查）→ fresh-checker 终审 → PR 合并销账。
- push 授权：比照 F-162 惯例——实施 push 前向维护者请示一次（分支 push 与 PR 开立即视为授权范围）。

## 判据回顾（与债务登记行逐字对齐）

README 登记原文（2026-09-13，F-162 副产物条 + 计时脆钉条）要求修复的正是：sim-demo ubuntu `build_failed（errors=-1, 190ms）` 与 `elapsed_ms 999<1000` 型抖动。本设计两节与之一一对应，无扩项。
