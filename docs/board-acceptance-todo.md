# 板子回来后的真机验收待办

> 拟定 2026-11-17（板不在身边时写）。用途：F-250 物理检查清单闸上线后的**首次真机验收**，
> 顺带把 9 个工程的清单与实物对一遍。
> 验收口径（铁律）：**只看 `verify.py` 的 verdict + 物理操作实测**，不看 review、不看单测。

---

## 0. 这次要验什么（先明确，免得做完不知道算不算过）

| 项 | 判据 | 现状 |
|---|---|---|
| F-250 物理清单闸 | 被拦一次 → attest → 全链 PASS | 单测绿，**真机未证实** |
| 清单内容 | 逐条与实物对得上（清单是按代码写的，没对过板） | 未核对 |
| verify 全链回归 | 13/13（沿用 v0.10 基线） | 未跑 |

预期耗时：单板 15 分钟；9 板全过约 2 小时。

---

## 1. 插板之前（5 分钟，不接板也能做）

- [ ] 探针/进程预检
      ```bash
      python D:/claude/tools/cc-ops/hw_preflight.py
      ```
      **通过** = 末行 `RESULT: clear to open a hardware session`。
      **探针没插时的正确输出** = `no supported pyOCD probe could be opened` —— 这不算异常。
      红（有 HOLD / BUSY / 无探针）先清僵尸进程，别带着跑。
- [ ] 工具链体检
      ```bash
      python D:/claude-embed/embedded-toolkit/scripts/verify.py --doctor --strict
      ```
- [ ] 确认没别的窗口占着同一个 ST-Link（McuBuddy / OpenOCD / 另一个 VS Code 调试会话）。
      连不上时的**归因顺序**：先问"是不是你自己拔的线" → 供电/接触/枚举 → 最后才是适配器坏。

---

## 2. 第一块板：stm32f103-mpu6050-oled（发布门禁 fixture）

### 2.1 先验证"闸真的会拦"（关键一步，别跳过）

- [ ] 插上 ST-Link（3V3 供板），**不要**先 attest：
      ```bash
      python D:/claude-embed/embedded-toolkit/scripts/verify.py \
        --project D:/claude-embed/hw-projects/stm32f103-mpu6050-oled
      ```
- [ ] 期望：`exit 1`、耗时 <1s、**构建未启动**、打印 11 条清单。
      若它直接开跑了 → 闸没生效，停下来查（见 §5）。

### 2.2 对着实物核对清单（这一步才是人做的事）

清单文件：`hw-projects/stm32f103-mpu6050-oled/.workbench/physical-checklist.json`

- [ ] `I2C-1` SCL=PB8、SDA=PB9（`User/MyI2C.c:16-19`），OLED 与 MPU6050 同一组总线、共地
- [ ] `I2C-2` MPU6050 的 AD0 接地 = 0x68（接 3V3 = 0x69）；固件先探 0x68 再退 0x69
- [ ] `KEY-1` KEY0=PA0 **按下为高**（内部下拉）；KEY1=PB15 **按下为低**（内部上拉）——极性相反
- [ ] `ADC-1` 亮度电位器：抽头→PA6，两端→3V3/GND
- [ ] `IR-1` 红外 OUT→PB12（EXTI12）
- [ ] `PWR-1/CON-1/CON-2/POL-1/PROBE-1/DEV-1` 通用六条

**清单与实物不一致时**：直接改清单 JSON（这是设计允许的），登记时说明改了什么。
改完哈希会变，旧的 attest 自动作废——不用手工清。

- [ ] 确认后登记（`--note` 必填，写清"按什么核对的"）：
      ```bash
      python D:/claude-embed/embedded-toolkit/scripts/physical_checklist.py \
        --project D:/claude-embed/hw-projects/stm32f103-mpu6050-oled \
        --attest --note "按 docs/FSD.md + 实物核对，PB8=SCL/PB9=SDA，AD0 接地"
      ```
- [ ] 立刻再跑一次 verify，确认**这次不被拦**（TTL 内放行）：
      ```bash
      python D:/claude-embed/embedded-toolkit/scripts/verify.py \
        --project D:/claude-embed/hw-projects/stm32f103-mpu6050-oled
      ```
      人读输出里应出现 `[0] Physical: OK  attested ... items=11`。

### 2.3 全链

- [ ] 期望：`Verdict: PASS`，13/13（v0.10 基线）。
- [ ] 物理操作实测（不看日志看现象）：
      - [ ] OLED 显示 `MPU6050 OK @ 0x68`
      - [ ] PA0 单击换页、长按关屏；PB15 单击方块旋转、长按重校准
      - [ ] 旋转电位器亮度三档变化
      - [ ] 静止放置 Roll/Pitch 稳定（<1°）
- [ ] 把 verdict 与关键计数的原文贴进验收记录（不要写"看着正常"）。

---

## 3. 其余 8 个工程（按需，每个 10 分钟）

统一动作：`verify`（应被拦）→ 核对清单 → `--attest` → `verify`（应放行）。

| 工程 | 该工程最容易翻车的一条 |
|---|---|
| ch32v307-envmon | DHT11 DATA→PB0，**起始前空闲即低 = 短地/接错脚**；HC-05 需 TX/RX 交叉（PA2→RXD、PA3←TXD，9600） |
| ch32v307-rtc | LSE 不起振时固件**回退 LSI**——看到走 LSI 不是 bug |
| ch32v307-selftest | IWDG 一旦启动关不掉，调试中途会被狗打断 |
| ch32v307-hello | 日志串口接错 = 空捕获 |
| esp32-hello | console 走 UART0@115200；USB 线要数据线 |
| esp32s3-hello | S3 的 USB-JTAG 与 UART 是两条路，别混 |
| stm32f103-adc-oled | **FR-ALERT-01 必须把 PA5 电位器旋过 3V**，采集窗 30s（见 F-249 决策 B） |
| stm32f103-button-toggle | PA0 极性随接线漂移；PC13 LED **低电平点亮** |

批量跑（不改状态，只看该不该拦）：
```bash
for p in D:/claude-embed/hw-projects/*/; do
  python D:/claude-embed/embedded-toolkit/scripts/verify.py --project "$p" 2>&1 | head -3
done
```

---

## 4. 失败分支（按这个顺序查，别跳步）

1. **被拦截** → 正常。核对清单 → `--attest` → 重跑。
2. **`--attest` 后又拦** → 12h TTL 到了，或清单在这期间被改过（哈希变了）。重跑 `--attest`。
3. **verify 跑起来但失败**：
   - 先看 `steps.physical_checklist.status` 是不是 `ok`（确认闸已放行，不是它的问题）
   - 物理现象归因：供电 / 接触 / 枚举 → 再怀疑固件
   - 想看静态闸意见：`python D:/claude-embed/embedded-toolkit/scripts/fault_lint.py --project <工程>`
4. **确定要跳过闸**（例如只想知道固件能不能编）：
   加 `--skip-physical`，它会记进证据，**不会静默跳过**。
   **永远不要**替用户跑 `--attest` —— 确认的是"线接对了"，看不见实物就没资格签名。

---

## 5. 如果闸根本没拦（回归检查）

按顺序排：

```bash
# 1) 配置在不在
ls D:/claude-embed/hw-projects/<工程>/.workbench/physical-checklist.json

# 2) 闸自己怎么判
python D:/claude-embed/embedded-toolkit/scripts/physical_checklist.py \
  --project D:/claude-embed/hw-projects/<工程> --check ; echo "rc=$?"
#    期望未确认时 rc=1；rc=0 说明它认为已确认或未配置

# 3) 版本对不对
git -C D:/claude-embed/embedded-toolkit log --oneline -3   # 应有 d81479a/C.../9c3cefd
```

---

## 6. 验收通过后要回填的账（不做的话下次等于没验）

- [ ] `embedded-toolkit/CHANGELOG.md` 的 F-250 条目：把「**未做（不冒充验收）**」那段换成实测结果
      + 证据 commit（仓规矩：每条附证据 commit）。
- [ ] 记忆 `physical-checklist-gate.md`：「真机验收未做」改成实测结论 + 日期。
- [ ] 清单与实物不符而改过的工程仓：提交清单变更（这本身就是产出——清单第一次对过实物）。
- [ ] 若 adc-oled 补了故障注入用例：把 `hw-smoke.yml` 的 fault_lint 步骤升级为 `--strict`（F-252 留的口子）。

---

## 7. 判定口径（防自我欺骗，抄自 CLAUDE.md）

- 验收 = 真机端到端；**review 与单测通过不算**。
- 只跑过一次的数字，结论写「未证实」并附复测命令。
- 「没有 X」必须引原文；引不出来写「没拿到」。
- 量化结论同会话前后各测一次，两次数据都摆出来。

---

## 附：命令速查

```bash
# 预检
python D:/claude/tools/cc-ops/hw_preflight.py
python D:/claude-embed/embedded-toolkit/scripts/verify.py --doctor --strict

# 清单：看状态 / 登记 / 判据
python D:/claude-embed/embedded-toolkit/scripts/physical_checklist.py --project <工程>
python D:/claude-embed/embedded-toolkit/scripts/physical_checklist.py --project <工程> --attest --note "..."
python D:/claude-embed/embedded-toolkit/scripts/physical_checklist.py --project <工程> --check

# 闭环
python D:/claude-embed/embedded-toolkit/scripts/verify.py --project <工程>
python D:/claude-embed/embedded-toolkit/scripts/verify.py --project <工程> --json

# 静态闸
python D:/claude-embed/embedded-toolkit/scripts/fault_lint.py --project <工程>
```
