# Changelog

格式约定: 每条含发现编号（代管期 findings 编目）与证据 commit。当前版本以
`VERSION` 文件为准（`wb_common.toolkit_version()` 读取）。

## Unreleased — 0.6 封袋后新账（F-173 起）

- **F-176 (fix, CI): coverage-gate 缺 requirements 安装——F-174 合入即现形**:
  根因: F-174 分支未推过, 其测试从未在 CI 跑; `step_capture_uart` 内部
  `import serial` (pyserial, requirements.txt 声明件), 本地"已装环境"全绿而
  coverage-gate (F-084 设计只装 coverage) 连爆 3 例 ModuleNotFoundError/断言
  漂移。处置: coverage-gate 补 `pip install -r requirements.txt`——**套件跨 job
  等价**优先于最小安装 (unittest 四金丝雀本就装 requirements, 棘轮/失败面不该随
  job 依赖差异漂移)。教训重演 F-164 口径: **分支"本地全绿"≠"CI 全绿"**——新增
  依赖面的分支, 合入前应经 draft PR 让 CI 真跑一次; 至少台账显式标注"CI 未验"。
- **F-175 (chore, 仓级): 脱敏换血与转公开 (2026-09-18, 秋招准备)**:
  公开前全仓复检发现——09-01 两轮重写后, 新增提交把 `<user-home>` 绝对路径带回
  CHANGELOG 引文与 docs 计划 (F-2 纪律回归, 防回归缺口: 守卫只拦提交时点不拦
  叙述), 且 10 个 commit 以个人 QQ 邮箱为 author (署名漂移)。处置: filter-repo
  多 pass——`--replace-text`(blobs/paths) + `--mailmap`(旧邮箱必须 `<old@x>`
  尖括号形态, 裸地址静默整行忽略) + `--message-callback`(实测本版本 replace-text
  不覆盖 commit message; 回调变量名是 `message` 非 `msg`, 写错即 NameError 崩
  fast-import)。全部失败形态零报错——**执行日志绿不是判据, blob/message/身份
  三通道独立复扫才是** (322 revs 复扫零命中收口; ghp_/github_pat_ 命中系
  SENSITIVE_FINDINGS 模式表自身, 良性)。重写后全量 898+6 绿 + 真机中性背书
  (esp32s3-hello status=ok, post_reset=skipped, F-174 台账)。
  ⚠ **新坑记录 (filter-repo 第四坑)**: `refs/pull/*/head` 不可变——9 个已合并 PR
  把重写前旧历史钉死原仓, force-push/删分支均无法触及, 公开即成挖掘通道。处置经
  用户批准: **净仓换名**——旧仓改 `embedded-toolkit-legacy-archive` (私有归档),
  新建同名仓承接干净历史 (master+5 tags+5 Releases+14 topics 搬运), README 徽章
  路径零变更, CI 当日绿, 2026-09-18 转 Public。凡有 PR 历史的仓转公开前, 先
  `git ls-remote | grep refs/pull` 评估, 别等收官才发现。
  证据链: 重写前全量 commit 图 bundle 备份 (维护者 archive 区登记, 旧短 hash 账目
  一律以其为回放映射源); 复检报告在维护者 reports/ (仓外)。

- **F-174 (feat, 合入收口 2026-09-18): ESP32-S3 最小闭环——三后端 idf/esptool/uart**:
  09-16 板到唤起 [[multi-mcu-tooling-roadmap]] (决策史见 esp32 挂账记忆)。新
  `scripts/esp_runtime.py` + verify 三派发点各加一分支 (`builder=idf` 经 idf.py
  build / `flash.backend=esptool` 经 idf.py flash, flash_args 单一事实源 /
  `capture.backend=uart` esptool chip_id 确定性复位 + pyserial 定时窗);
  **缺省路径逐字节回归钉**全绿 (不配置 = 行为与今日完全一致, F-150 先例同构)。
  - 真机: esp32s3-hello 全链双 PASS (74 行 capture, expect 双靶命中) + 负路径 4/4
    (错 port/错 expect/占口/panic 标记); 真机钓出 host 不可见 2 真 bug——Git Bash
    的 MSYSTEM/MSYS 继承被 IDF export 拒激活 (`_idf_env` 清除) + IDF 5.4 内置
    esptool v4 拒 dash 形式 `--after hard-reset` (通吃下划线集)。教训入册:
    封装外部工具链的 mock 单测过 ≠ 通路过, 真机首跑必留调试预算。
  - 终审#2 (sonnet, 包 f17a29c..6dda398): 修后可合 → 修复波 I-1 `_esp_backend_mode`
    三标记 OR 闸 (post_reset/hardfault 层 2 双路抑制——09-16 双 PASS 属 ST-Link
    失联碰巧无害) + port/chip 白名单 (合入前置票: port 拼 PS 命令串的注入面,
    COMn//dev tty 形态白名单 + shell 元字符拒收, chip 归一+有限集) + I-2/I-3/minor×2;
    scoped re-review 判可合入, 撤销实验实证 14 例双向钉非空洞 (撤任一闸红点精确,
    判据恒真时 STM32 回归 3 红)。
  - 真机收口 (09-18, 销双挂账): ESP 快验 **post_reset=skipped** (闸兑现, 全链零触
    OpenOCD) + 全链 status=ok; STM32 回归 adc-oled 4/4 matched **post_reset=ok**
    (缺省路径零破坏的反向真机证明)。merge 后全量 898+6+282 绿复跑落账。
  - 仍挂 (deferred 全裁"可留"或后续票): F-174a state.json 无锁写 / F-174b bin glob /
    N-3 空捕获提示语 ESP 措辞 / N-4 physical_gate 入 `_esp_backend_mode` 闸。
    非目标未做: WiFi/BLE、probe-rs、xiaozhi 接入、panic 符号化。

- **F-173 (docs) 叙事层正名——产品名 arbiter 入 README，仓名不动**:
  走读介绍时发现名实脱节——`embedded-toolkit` 暗示的是一只可挑拣使用的零件盒，
  而 0.5 之后内核已长成判定链（G1 门禁拒绝、证据分级、哈希锚都是裁判属性不是
  工具属性），名字停在演化起点（0.1~0.4 纯工具期）。处置: README 头部加代号
  arbiter + 命名沿革注记——只动叙事层，仓名/tag/GitHub 地址/CI 徽章/机器路径全部
  不变（钉在"发布锚点不可变"同一纪律上）。教训: 改名与封袋注记同层——人看的可改，
  机器用的不动。

## 0.6 — 2026-09-15（总工单 v2 全量 + 治理三件套 + 无板闭环 + 真机全链收口）

> 封袋定义: 自 v0.5 标签（commit 2d75209, 2026-09-10）之后落入本账本的
> 全部 Unreleased 节归入 0.6（账本时间线与 v0.5 tag 有交叠——0.5 节封袋
> 写于 tag 前, 核对以 git 锚点为准, 勿以本文件行位置为准）。
> 封袋区间内 F 号大体范围 F-094~F-172。要点导览:
> - **总工单 v2 全量**（F-117~F-166）: Claude 侧 P0/P1/P2 + z code 侧
>   A/B/C/N/D 系列合流（分工变更致 F-134~144 空置）; 终审退回代修 F-161
> - **治理三件套**: F-112 expectations 负断言（prohibited_outcomes 进机器）
>   / F-113 fsd_coverage 需求↔断言对账（欠条与豁免两级不混用）
>   / F-145 hw_lease 机器级设备锁（探针互斥, OS 放锁）
> - **无板闭环与接入面**: F-150 qemu sim 后端（examples/sim-demo 即跑）
>   / mcp_server 六工具有界包装（白名单校验, 不给 agent 任意 shell）
> - **互锁链与取证加固**: F-109 SCB 粘滞位真机取证 / F-115~116 RTT 工程
>   HardFault 闭环补齐 / F-155+F-163 N-3 构造性标记双消费面 / F-127 写锁
> - **生成器时钟树参数化**: F-110/F-111 --hclk 单入口 + APB 标准分频推导
>   （846 例逐字节兼容实证）
> - **CMSIS 浅裁三树**（F-169b）+ 三工程真机全链收口: adc-oled 4/4、
>   mpu6050-oled 11/11、button-toggle 2/2（09-13~15, 含人工交互项）
> - **封袋当日收编**: F-171 采集窗纪律五条入 README / F-172 openocd_run
>   CLI 烧录标记不可达修复（封袋前走读钓出, 真机复验 status: ok）
> - 质量面: 测试 325→860, CI 六 job（ubuntu×windows 矩阵/coverage 棘轮/
>   ruff/零覆盖 strict/syntax-smoke/sim-demo+test-reporter）

- **F-172 (B 类缺陷) openocd_run CLI 烧录构造性标记永不可达，fix+tests+真机复验**:
  0.6 封袋前走读发现——`openocd_run.py flash` 恒判 `action_incomplete` 假红
  （`programmed: true, verified: true, rc: 0` 俱在却拒收）。双根因: ① builder
  把 `program … verify reset exit` 做成**单字符串内嵌 exit**，标记装配处
  "摘尾部门闩"只 pop 列表元素、摘不掉字符串内嵌者，`echo MARK` 落在 OpenOCD
  退出之后永不执行; ② 既有 mock 钉 `assertEqual(cmd[-1], "echo MARK…")`
  钉的是"装配意图"而非"OpenOCD 执行序"，恰好掩盖此缺陷（verify.step_flash
  在 F-163 已改 "-c program / -c MARK / -c exit" 拆序先例，CLI 面未同步）。
  处置: flash 串去内嵌 exit（reset 保留）+ 装配处门闩收敛（pop 尾部
  exit/shutdown → echo MARK → exit）; 测试订正为执行序钉（门闩后不得有动作
  命令 + erase 重排钉 + flash/erase 双 action subTest）。真机复验: mpu6050-oled
  CLI flash `status: ok`（programmed/verified 俱真）; 全量 860 绿（+2 新钉）。
  教训: **构造性证据链自身也要有构造性测试**——判据"标记在场"依赖命令执行
  序，测试须钉执行序而非装配意图; 双消费面（verify/CLI）共享判据时须共享
  顺序先例。


- **F-169 (清账) R7 历史遗留处置=登记永久 FAILED 语义，docs（README 已知遗留节）**:
  挂账自 F-114（"重锚注记 or 永久 WARN 并登记"二选一）。**根因今日拿到构造性
  证据**：mpu6050-oled v0.5 记录 `contracts.config_sha256`=2d3f57cbc999.. 经
  实测 = git_head(422e45f) blob 的 **LF→CRLF 往返哈希**（逐字节精确复现,
  blob 原样 sha=062cca37.. ≠ 记录值）——发布发生在工作树 CRLF 时代、入库定在
  eol=lf 之后, 字节错位纯属行尾切换历史遗留, 无内容差异、非篡改。
  **处置=不重锚不改记录**: 发布记录是防篡改审计锚, 为消警告回填哈希与 R1~R8
  设计目的直接冲突（改记录者可得工具帮助篡改, 本末倒置）; expectations 侧
  本就一致（blob-match）, 错位面仅此一键。后续对该记录跑 release_audit
  预期 R7 FAILED=登记语义（HANDOFF §6-2.5 同口径, 勿当新伤）; 工程记录本体
  零改动。

- **F-169b (联动销账) 三工程 CMSIS 浅裁施工 + RTT e2e 复验全绿**: 用户拍板浅裁
  三在役树（删 Lib/DSP/NN/RTOS*/Core_A/Core/docs, Makefile 引用面零触达, 各
  工程浅裁 commit 799b7ee/7e5052b/6954775）; 门禁=clean rebuild 0W0E ×3 +
  size 三元组逐字节一致 + adc-oled 真机链复验: 首跑 build/flash/capture 全 ok
  (evidence=hardware_validated, FR-ALERT-01 缺属旋钮未过阈如实判定), 拧满复跑
  **4/4 全 pass**（raw=4095 mv=3300, bf_20260914_223109 落账）。vendor
  stm32f103-cmsis-seed（18M）建立防胖拷贝复发, 顶层 README 登记。教训:
  ST-Link 掉线先问一句"是不是你拔了"——本笔实为**维护者自己拔的**（事后
  澄清）, 我归因"克隆片间歇失联"是抢答; 判别法不变: 软件面排查前先过物理
  面一问（与既有 stlink-clone-intermittent 记忆同款纪律）。回收 ~150M;
  工程仓已推 origin（adc-oled/button-toggle）。深度记忆见
  [[cmsis-drivers-slimming]] 已执行态。
- **F-171 (09-15 板前收口) 采集窗纪律五条入 README + 三工程人工项全闭合，docs（README 5 分钟上手节后）**：
  ① 五条纪律（窗口在烧录后才开 / 自持窗命令模板 / 连拍优于单点 / 判 fail 先查动作 /
  SWD 连不上先过物理面）收编 toolkit 单点事实源，勿工程各抄——源自当日
  mpu6050-oled 11/11（含 4 项人工交互一窗全收）与 button-toggle 冒烟 2/2
  （TGL 152 行）排障三次现形的教训；button-toggle PA0 极性翻高有效适配现接线
  （工程仓 a538701→93bef5e，README 漂移首例自查联动 HANDOFF §6-4.5 私约条文）。
  ② 同日教训两笔入工程账：全链 verify 的"开跑"通知必须发在窗口真开后
  （09-10 发布门禁老坑第三次现形）；探针读电平先对照用户当下动作再定性
  （"3V3 断路"误判被用户一句"我没有按下"纠正，[[stlink-clone-intermittent]] 变体）。
- **F-170 (挂账裁决单) L-2/L-6 结案 + L-4/cfg 收口改暂缓，docs（零行为改动，
  spec: embedded-handoff `docs/superpowers/specs/2026-09-14-f170-ledger-
  adjudication-design.md` 2026-09-14 批准; F-035 复审按 F-167/168/169 先例豁免）**:
  ① **L-2 结案（不修）**: OpenOCD 无时间戳前缀形态（14 条噪声正则全部实机
  照抄, F-106 测试 9 形态钉在场）——推测项判死; 正文行首恰撞锚定词=可预期
  误滤（概率≈0, 未来真出现按新事故立项）, 裁决入 failure_context.py 头注。
  ② **L-6 结案（不改）**: lint 无清单=配置错误 exit 1 / coverage 无 FSD=合法
  存量 SKIPPED exit 0——**不对称恰是正确建模**, HANDOFF §6 第 3 步判据依赖
  它, 改齐即塌方; 退出码语义分工入两脚本 docstring。③ **L-4 改暂缓**:
  今日消费方扫描（evidence_export/junit_xml/release/release_audit/tests 全量
  grep）零引用实证, 仅 verify 早退路径内部消费 legacy `missing: expect`
  （合法）。唤起条件 = 下一次契约整理工单顺路（回显置空+契约钉翻转+CHANGELOG
  契约变更段, 一个 commit 级）。④ **cfg 收口改暂缓**: 唤起条件 = 第二板型
  接入或 F-031 窗口（README 同步改口径）。验收: 全量 unittest 复跑零红
  （防注释措辞被测试内文断言引用——F-108 教训面）; push 后 CI 绿。
- **F-168 (清尾) D-2 分发形态立项状态改暂缓，docs（README 生态位节）**:
  总工单 v2 收官后唯一剩余工单级欠账 D-2（PyPI/uvx/插件分发形态 spike）经
  维护者评估降级: 当前无外部用户、git clone 自用形态满足全部在役工作流,
  且其服务对象"开源推广"本身是未行权期权——无验收人的体验工程不排产。
  README 措辞"已立项未实施"→"暂缓 (2026-09-14)", 登记唤起条件 = 决定对外
  推广 toolkit 之日, 届时仍按原风险点 (包数据定位策略) 先 spike 再立项。
  与 F-124 纪律一致性: 状态如实, 既不超前宣传也不藏账。

- **F-167 (清尾三笔) arXiv 引用撤销 + ADC-02 期望正则对齐 + FSD 退役残项勾销，docs(+工程仓联动)**:
  ① **arXiv:2509.09970 核实并撤销**（README 已落地/立项方向节）: 09-14 经
  WebSearch 实证该编号解析为 **Ultra-R1: RL for Reasoning in Unified
  Multimodal Models**（文本生成图像推理, cs.CL）——与嵌入式闭环验证完全无关,
  系 D-3 点名登记时的编号错误, 当年 arxiv.org 不可达照录未验所致。README
  措辞改单条引用 (闭环评测论文保留) + 如实记撤销; 本仓不引不实来源。
  ② **ADC-02 期望正则对齐**（联动, 改动在 stm32f103-adc-oled 工程仓
  `.workbench/expectations.json`）: 固件 `Format_Raw4` 对 raw<1000 输出右对齐
  前导空格（`ADC raw= 105`）, 原 pattern `raw=\d+` 隐含 raw≥1000 才命中
  (Task 5 真机复验发现)。改 `raw=\s*\d+`, 六形态正则实测全对 (含低值/零值/
  高值/两类坏行反例)。**生效验证挂下次真机 run** (本笔为静态对齐)。
  → **同日销**: ST-Link 重连后真机 verify, FR-ADC-02 于旋钮低位
  (raw= 105 前导空格形态) **首次命中 pass** (evidence=hardware_validated);
  工程仓 commit 19f9a21。ALERT-01 判 fail 属旋钮未拧过阈预期语义 (min=3000)。
  ③ **FSD 退役残项勾销**（记录性, 改动在已退役 blink 归档之外无代码触点）:
  blink 时代 5 项账面——FR-TGL-07 计数回绕 / FR-IMU-04 yaw 漂移 (两项 host
  pending) + FR-UI-04 渲染周期 / FR-SRV-03 PWM 实测 / FR-OLED-04 全屏刷新
  耗时 (三项 bench, 需示波器/逻辑分析仪)——载体工程 stm32f103-blink 已于
  09-03 退役 (archive zip 封存 FSD), 需求未被在役工程 (adc-oled 4 项契约 /
  mpu6050-oled 自有 FR 体系) 承接, 判定语义不随工程迁移。处置 = 正式作废
  登记 (记忆账本 fsd-template-stm32 行同步), 非欠账: bench 三项的测量手段
  议题 (时序测量) 归 mpu6050-oled 自己的 bench 项一并再议。

- **F-166 (CI 矩阵复绿) py3.10 双腿红——evidence_export PEP701 降级 + stderr pump 逐出策略根因修，fix+test+docs，scripts/openocd_runtime.py / tests/test_evidence_export.py / tests/test_openocd_startup_wait.py / CHANGELOG**:
  PR #9 (ci-stabilize-20260914) CI 观测: 除计时噪声外 py3.10 双腿自
  F-151 起从未绿过（ubuntu-3.10 另有一枚确定性红被计时噪声掩盖，F-165
  消噪后显形）。随本 PR 一并修复（Task 5 远端复绿终判的组成部分）。
  ① **(a) test_evidence_export.py:93 PEP701 嵌套同引号 f-string**：
  `f"...{r"D:\local\other"}..."` 双引号套双引号是 py3.12+ (PEP701) 才
  合法的语法，仓库地板声明 py3.10 (ci.yml matrix 含 3.10) 下 SyntaxError
  ——63dbb78 (F-151) 引入。修复: 提为模块常量 `_WIN_OTHER` 后普通插值。
  全仓扫描结论: 对仓库全部 115 个 .py（scripts/ tests/ 及根目录, AST 级
  JoinedStr 插值表达式扫描——内含反斜杠 / 复用外层同种引号 / 换行三类
  3.10 拒收形态, 检测器用已知违例的修复前文件反向校验命中），
  **零残留**；gen_periph.py 的 `{{` 双写是转义非 PEP701，安全。
  ② **(b) openocd_runtime stderr pump 丢最旧→丢最新（真缺陷，非测试
  兼容）**：旧策略"满队列 get_nowait 腾位再塞"在**启动即爆发刷日志**
  （首批 >maxsize=1000 行、consumer 尚未就位）时恰好逐出队头
  `Listening on port ...` 就绪行 → wait_server_ready 永等不到 ready →
  ubuntu-3.10 `test_pump_drains_without_blocking_writer` 15s 确定性超时
  红（PR #8 起即红）。新策略: 满队列直接丢弃当前行（丢最新）——就绪/
  Error 关键行全在流头部，丢最新只截断洪水后段；排空活性与内存上界
  （"长会话内存不增长"）不变。EOF 哨兵收尾路径保留腾位逐出——该路径
  进程流已关，无早期行风险，且必须保 EOF 送达否则消费端空转等哨兵。
  影响面: wait_server_ready / wait_itm_ready 全体消费方
  （openocd_gdb / openocd_telnet / openocd_itm 三入口）统一受益于此修，
  无接口变更。
  ③ **回归钉** `StderrPumpDrainTests.test_startup_firehose_keeps_ready_line_alive`:
  `_FirehoseProc(3000)`（3×maxsize 爆发 + 永久沉默尾巴, 与真 gdb server
  启动形态同构——刻意不立即 EOF: 有限迭代器收尾"腾位保 EOF"同样逐出一行
  队头, 修复后代码也保不住就绪行, 那就不是存活服务稳态的判别器）。两层断言:
  队列层钉"保住的必须是流头部一段"（head=Listening, 次行=drain line 0,
  保留数恰=maxsize 的有界性同钉），端到端层真调 `wait_server_ready` 必须
  ready=True。**flip 红证**: 临时回退为丢最旧，本钉红（head 实测
  `drain line 2000 ...` ≠ Listening），已复原，flip 未入任何 commit。
  既有钉冲突排查: 全仓 grep "丢最旧/pump/逐出" 仅命中本单新改文本，
  无任何先钉锁死旧逐出契约（F-123 历史条目里的"满丢最旧保活性"是当年
  账目，append-only 保护区不回写，以本条为契约更正）。
  ④ **验证**: 聚焦 23 例绿（startup_wait 11 + evidence_export 12）; 全量 858 OK (skipped=6)（+1 新钉）; ruff
  scripts/tests 干净; F-089 卫生钉绿。本机 py3.14 无法编译级证明 3.10
  兼容, 以 AST 扫描 + flip 红证 + CI 矩阵实测（Task 5 push 后）为终判。
  - **终判回填（2026-09-14）**：✅ CI 矩阵实测通过——PR #9 run 34816266924
    （head 2695cf7）py3.10 双腿（ubuntu+windows）首次转绿，10/10 checks
    全绿；pump 排空钉与 evidence_export 导入钉在 3.10 上均绿，(a)(b)
    两修同时生效实证（本条目即本单三笔 F-164/165/166 的合并终判凭据）。

- **F-165 (预置债销账) CI 计时脆弱钉去墙钟化——两枚钉改注入假时钟，零真实等待，test+docs，tests/test_runtime_contract.py / tests/test_state_write_lock.py / README / CHANGELOG**:
  F-162 副产物登记的计时脆弱钉（ubuntu 降解钉翻车 + windows 实测
  999<1000）两枚一并收口（(a) 段先行落 431b37c，本条记账覆盖 (a)+(b)）。
  ① **(a) test_runtime_contract ser 版耗时钉**：旧版喂 `time.time()-1.0`
  再赌 `elapsed_ms>=1000`——墙钟下界断言，CI NTP 微调回拨即 999；改注入
  假 `datetime`（未来固定 epoch），耗时逐字 `==1000` 零容差，墙钟回潮即红。
  ② **(b) test_state_write_lock 降解钉**：旧版真 `sleep(0.05)`+真 0.5s
  超时+`elapsed>=0.4` 墙钟下界 = ubuntu/py3.12 抖动源；改 patch
  `runtime_common.time`（模块级 `import time`，`time.time()`/`time.sleep()`
  均经模块属性调用可注入）+ `_state_lock_is_stale=False`，零真实等待。
  节拍钉实测 **11 跳**非简报预估的 10 跳：deadline 判定先于 sleep 且
  IEEE754 累加使 10 跳后 t=1000.4999999999995 差 5e-13 未及线，第 11 跳
  越线 break——节拍语义不变（轮询直到虚拟 deadline），全平台确定可逐字
  钉死。降解路径三重行为钉：放行恰好一次 / stderr"降级"留痕 / 外来锁
  **不被删除**（finally 仅 acquired=True 时 unlink，runtime_common.py:201-206）。
  `_STATE_LOCK_THREADS.acquire(timeout)` 走真 C 层 threading 不经假 time，
  单线程测试无竞争瞬拿，不受影响。
  ③ **偷取钉在场确认**：`test_stale_lock_is_stolen`（超龄锁 unlink 重取）
  在场且不受本改造影响（降解钉的 `_state_lock_is_stale=False` patch 为
  with 域内局部，不泄漏）——未补新钉，总数 857 不变。
  ④ **验证**：聚焦 7 例绿；全量 857 OK (skipped=6)；ruff 通过。
  - 终判边界：本条为 host 层证据（Windows），远端复绿（ubuntu/py3.12
    降解钉 + windows 耗时钉在新 CI 上连续绿）以 F-164/F-165 合并 PR 的
    CI 全绿为终判（挂本计划 Task 5）。
  - **终判回填（2026-09-14）**：✅ PR #9 run 34816266924 全绿——ubuntu/py3.12
    降解钉与 windows 耗时钉均在 CI 连续绿（py3.10 双腿同 run 经 F-166 复绿）。
  - 顺路收尾（前序任务审查裁定）：F-164 条目搬 Unreleased 堆绝对顶部
    （latest-on-top，位置搬迁非文本重写）并在卫生自纠子条归因处补
    "（95d66de 引入）"；(a) 段 t0 注释订正——1.8e9 实为 2027-01，旧注
    "2026-09 附近"失实，改"未来固定 epoch, 远离 pre-epoch 边界"。

- **F-164 (预置债 D-3 候选闭合) gcc_build 预检平台化 shutil.which — 去 .exe 硬编码，ubuntu sim-demo 速败根因闭合，fix+test+docs，gcc_build.py / tests/test_gcc_build.py / README / CHANGELOG**:
  F-162 副产物登记的 sim-demo job ubuntu `build_failed`（errors=-1，190ms
  速败；该 job 自 F-150 入仓起从未真跑过 CI，本地全绿，登记时根因未查、
  非 F-162/F-163 引入——此处照录原登记以保留追溯）根因查明并闭合。
  ① **根因**：`gcc_build.py` main() 预检写死 `arm-none-eabi-gcc.exe` 字面量
  ——ubuntu runner 上二进制无 `.exe` 后缀必败，预检报 `gcc_path invalid`
  速败（errors=-1 即未经 make 的预检出口）；② **替换判定**：两条路径检查
  统一 `shutil.which`（gcc 查裸名 `arm-none-eabi-gcc` +
  `path=machine["gcc_path"]`；make 查 `machine["make_exe"]` 全路径/裸名）
  ——nt 下 which 自动试 PATHEXT（.exe）与旧判定等价，POSIX 查存在+可执行位；
  `not machine.get(...)` 空值短路措辞原样保留（空配置仍直接判 invalid，
  不进 which，语义不漂移）；③ **4 枚钉**（PrecheckPlatformPortableTests）：
  三枚行为 mock 钉（gcc 查无→报 gcc_path invalid / gcc 有 make 查无→只报
  make_exe invalid / 双命中→不再报 precheck）+ 一枚 F-159 同款 AST 形态钉
  （main() 源码不得再含 `.exe` 字符串字面量，防回潮）；红基线 4 例全红转绿
  （先死于 `module 'gcc_build' has no attribute 'shutil'`——恰证旧码无 which
  路径），本文件全量 13 例 OK；④ **Windows 等价活证据**：
  `python scripts/gcc_build.py build --project examples/sim-demo --json`
  实测 `"status": "ok"`、`metrics` 0 errors 0 warnings，PATHEXT 等价性在
  真机跑通；全量套 857 OK (skipped=6)；⑤ **README 销账**：F-162 副产物
  （预置债 D-3 候选）条目改写为"已闭合（F-164, 2026-09-14）"。
  - 追加（F-089 卫生自纠，commit 0352665）：本单计划文档（随 95d66de 入库）
    自指行含裸机器路径字面量（95d66de 引入），违反其自身宣布的 F-089 规约，被
    `test_source_hygiene_paths` 扫描钉拦截判红；实现者按最小措辞修复合规入账。
  - 终判边界：本条为 host 层（Windows 活证据 + 行为/形态钉）证据，ubuntu
    远端复绿以 F-164/F-165 合并 PR 的 CI 全绿为终判（挂本计划 Task 5）。
  - **终判回填（2026-09-14）**：✅ PR #9 run [34816266924](https://github.com/xujiujiu0628/embedded-toolkit/actions/runs/34816266924)（head 2695cf7）10/10 checks 全绿——sim-demo job 转绿实证本修生效。

- **F-162 (审核遗留 M-4) CI 接线：sim-demo job 产 JUnit + test-reporter 消费，ci+docs，.github/workflows/ci.yml / README / CHANGELOG**:
  `verify.py --junit-xml` 旗标自 F-147 起仅有单测层可解析性证据，从未被真实
  GitHub Actions reporter 消费（M-4 指出的"产物无人吃"洞）。本条接线：
  ① sim-demo verify 步骤加 `--junit-xml build/junit-sim.xml`（`build/` 已被
  .gitignore 覆盖，产物不入库）；② 新增 `dorny/test-reporter` 消费步骤，
  **SHA 锁定** `a43b3a5f7366b97d083190328d2c652e1a8b6aa2`（= v3.0.0；解引用
  核验命令 `gh api repos/dorny/test-reporter/git/tags/<tag-object-sha>`，
  供应链纪律：升级走 CHANGELOG、只升不降）；③ job 级显式最小权限
  `contents: read / checks: write / pull-requests: read`。两个决策：
  `if: always()` 让失败运行的 XML 也被消费（M-4 要验证的正是 reporter
  吃得下四态混合产物）；`continue-on-error: true` 防 reporter 自身故障把
  CI 判红掩盖真因。本地钉：qemu 11.1.0 全链 verify exit=0，
  `build/junit-sim-local.xml` 产出且 `xml.etree.ElementTree.parse` 通过
  （4 testcase：3 passed + 1 skipped）。销账判定由人盯首个真实 PR 的
  "Sim Verify Results" 检查（README M-4 条目暂标"闭合中"，PR 复验通过后
  收尾 commit 改"已闭合"并回填检查名/URL）。
  - 追加（收尾，2026-09-13）：reporter 步骤显式 `fail-on-error: false`
    （dorny 默认 true 会把"消费"误升为"门禁"——产物含失败态属预期，
    门禁由 verify 步骤本身负责）。
  - 实吃销账记录：PR #8 run 34755875069（https://github.com/xujiujiu0628/
    embedded-toolkit/actions/runs/34755875069）——**失败态产物消费成功**，
    日志 `Using test report parser 'java-junit'` + check run "Sim Verify
    Results" 摘要 "0 passed, 1 failed and 4 skipped"，四态映射逐条正确
    （FR-SYS-01/FR-TGL-01/FR-ADC-01/FR-FUTURE-1 skipped + preflight
    failed），`if: always()` 设计在真实数据上得证；M-4 闭合。
  - 订正（fresh-checker M-1/M-2, 2026-09-13, append-only——上行走措辞失实
    就地订正如下）：① 上行"check run 'Sim Verify Results'"**不实**——
    v3.0.0 默认 `use-actions-summary: true` 走摘要模式（只写
    GITHUB_STEP_SUMMARY，从不 `checks.create`），实证：该 run 远端
    check-runs 列举 18 条无 Sim Verify。首吃证据成立本体收窄为：run
    34755875069 日志中 java-junit 解析 + 四态映射（摘要模式）；check run
    形态待复观。② 本 run 销账所用配置系**修订前配置**（`fail-on-error`
    当时默认 true，步骤判绿靠 continue-on-error 兜底）；终态配置（新增
    `use-actions-summary: false` 显式贴 spec "PR 页面出现检查结果" 原意 +
    `fail-on-error: false`）尚未被远端执行——复观挂终态配置 push 后下轮，
    M-4 状态相应回退为"闭合中"（README 同步）。
  - 预置债两笔（同 run 暴露，均非本条引入，登记 README 已知遗留）：
    ① sim-demo job 在 CI ubuntu runner 上 build_failed（errors=-1，
    190ms；该 job 自 F-150 入仓从未真跑过 CI，本地全绿，根因待查，
    D-3 候选）；② 计时脆弱钉抖动——test_state_write_lock 超时降解钉
    （ubuntu/py3.12）与 test_runtime_contract `elapsed_ms>=1000` 钉
    （windows，实测 999<1000），F-159 加固残余边界。
  - 复观记录（2026-09-13, append-only, M-4 终态定稿）：终态配置
    （`use-actions-summary: false` + `fail-on-error: false`）已获远端执行——
    PR #8 run 34762552201（head 20e350d）产出 check run "Sim Verify Results"
    （check 103737895345，https://github.com/xujiujiu0628/embedded-toolkit/
    runs/103737895345）：已创建且通过，输出摘要 "0 passed, 1 failed and
    4 skipped"（失败态产物被消费，`checks.create` 生效）。check run 形态成立，
    与首吃（run 34755875069 日志解析，摘要模式）构成双形态证据；sim-demo job
    本体仍红属预置 ubuntu build_failed 债（上行 ①），不阻塞本 check 结论。
    fresh-checker M-1/M-2 残余勾销，README M-4 改"已闭合"。

- **F-163 (总工单遗留 L-4) verify.step_flash 接入 N-3 构造性标记 — rc=0 且标记在场才算烧成，feat+test+docs，openocd_run.py / verify.py / tests/test_openocd_n3_marker.py / tests/test_verify_failure_paths.py / README / CHANGELOG**:
  L-4 登记的 N-3 覆盖洞闭合（F-155 只覆盖 openocd_run 的 flash/erase，
  `verify.step_flash` 直连 openocd `program` 的高频真机路径不经该链）。
  ① **共享件抽取**：`openocd_run.ACTION_DONE_CMD` 公开别名 +
  `marker_present()` 纯函数（缺席判定单实现，无双漂移）；② **cmd 串尾
  echo**：`program {hex} verify` 后接 `-c ACTION_DONE_CMD -c exit`——
  exit 截胡时标记 echo 不会在场，"脚本没跑完"获得构造性证据；reset 不再
  挂在 program 串内，由主流程 post_reset（F-129）与 capture 会话各自
  reset halt 起点负责；③ **缺席判定**：rc=0 但 stdout+stderr 无标记 →
  `action_incomplete` error 拒绝按成功入账（构造性证据优先于退出码，
  与 openocd_run 同款判据；OpenOCD 日志走 stderr，校验拼接同款第 305 行
  `combined` 口径）；④ 测试：红基线三例（rc0+标记 ok / rc0 无标记拒 /
  rc≠0 旧契约不变）转绿，共享件三钉在 test_openocd_n3_marker。真机复验
  待 Task 5（本条为 host 层证据；`program` 拆序后 halt 态衔接结论回填此条）。
  - 追加（M-4a, 审核 Minor 即时收口）：`_run_flash_step` attempts 消费端
    补 message 回退——旧 `flash.get("stderr", get("stdout", ""))` 对
    message-only 错误 dict（action_incomplete / 无 hex）恒得空串，根因在
    最终 JSON 隐身；改为 stderr/stdout 缺席时回退读 message，
    `attempts[].message` 现在能看见 `action_incomplete` 字样
    （测试钉 FlashAttemptsMessageFallbackTests，fail-closed 行为不变）。
  - 真机复验 2026-09-13（L-4 销账，Task 5）：adc-oled 在位闭环——
    flash 带标记 PASS（attempt 1 即成、无 retry，`** Verified OK **` 后
    `MARK_ACTION_DONE` 在场）、capture rtt 91 行 ok、post_reset=ok、
    evidence=hardware_validated。反证抽查一次：临时删除 cmd 中
    `ACTION_DONE_CMD` 段重跑，flash 即报
    `action_incomplete: 构造性标记缺席`（rc=0 无标记被拒入账），
    证实标记判定在真机路径生效；`git checkout` 还原后工作树干净，
    破改态未进任何 commit。ALERT/ADC-02 两项因旋钮未拧满
    （mv≈105<3000，且低电压 raw 为空格右对齐不匹配 `\d+`）FAIL，
    属 09-13 已知人工交互缺口非本工单回归（两次运行
    expectations_sha256 一致，capture/verify 路径 F-163 未触碰）。
  - 边界说明（fresh-checker L-1, append）：上文"reset 由 post_reset 与
    capture 起点负责"仅覆盖正常收尾链——capture 失败早退路径
    （`verify.py` sim/rtt/semihosting 三处失败 `sys.exit(1)` 及
    `_finish_capture_timeout` 收尸出口，行号锚 917/944/978 系当次快照）
    不做复位，目标滞留 halt 残留态；下一轮 run 经 capture 起点
    `reset halt`（或直接烧录）自愈，非累积性状态污染，属已知可接受边界。

- **F-161 (审核退回 M-1/M-2/M-3/M-4/M-5/L-1~L-5) fresh-checker 终审处置，fix+test+docs，hw_lease.py / test_hw_lease.py / CHANGELOG / README**:
  终审"通过但有保留" (C0 H0 M5 L5)。① **M-1**: `hw_lease.release()` 对
  "合法 int 但失效 fd"裸抛 OSError 违反恒返回 dict 契约——`_unlock_byte`
  改返回 bool、release 捕获后报 ok=False 说明"fd 失效→OS 已随 close 放锁、
  重取无碍"（verify 收尾 8 出口不得 traceback）; ② **M-2**: release 删锁
  本体文件引入"旧 inode 持锁者+新 inode 获取者"共持窗口 (OS 锁锁 inode
  不锁路径)——锁本体改为留置不删 (代码注释自证"文件留置无害", 删除操作
  恰多余), meta 旁车照清; 测试随契约: 新 M-1/M-2 两钉 +
  `test_winner_holds_lock...` 的"锁文件已清理"断言翻转重取钉。终审 M-2
  为静态推理未实测复现, 本钉为结构性消除; ③ **M-5**: CHANGELOG 16 处
  `@ 本条 commit` 占位符按 git 对账回填真实短 hash (F-145=17232a5 …
  F-160=bbe9295, 顺序以条目内文号为准); ④ **M-3**: README 路线图补
  D-3 点名的学术引用登记 (arXiv:2509.09970 编号照录, 内容本机网络不可达
  如实标"未核实"); ⑤ **M-4/L-4**: 已知遗留两条入账 (junit reporter 实吃
  未验证 / verify.step_flash 不经 N-3 标记链); ⑥ **L-1/L-2/L-3/L-5**:
  节标题 T9 重复笔误修正 + 号段跳空注记 + lint E2 缺 id 标签
  `expectations[0]`→`<idx 0>` 漂移登记 (行为等价, 文本无消费方, 不再改
  回以免牵动逐字钉) + 交接文档"9 例 hooks 失败"与实测 7 例全过的精度差
  记账。终审全文与复现命令见桌面《Claude审核交接文档》§9 回填。

- **F-154 (T10/P2-6) 红基线 22 钉转绿 — 边角缺陷打包实现，fix+test，serial_monitor / physical_gate / svd_to_json / rm_lookup / duration_profile / openocd_telnet / openocd_run / openocd_gdb / openocd_itm / capture_semihosting / serial_mux / serial_runtime / runtime_common**:
  F-133 红基线 (tests/test_p2_edge_pack.py, 16 用例 22 断言) 逐条实现:
  **a** `serial_monitor.emit_line` 过滤器异常 fail-closed + stderr 告警
  (旧 except pass = 坏过滤器全放行污染监控输出); **b** `physical_gate`
  expected<=0 前置守卫 — 碰子进程前短路返回 probe_error (旧版除零使
  deviation 恒 0 恒绿); **c** `svd_to_json` 删 `resolve_derived_from` 死
  函数 + `merge_into_ref` 不再硬编码覆写 `_meta.version/updated` (ref
  语义版本与是否跑过 SVD 同步无关); **d** `rm_lookup.format_result` 增
  显式 ref_data 参数 (库态调用不再 NameError), `--list` 的 peripherals
  裸下标改 `.get` 链; **e** `duration_profile` 工程根发现收编
  `wb_common.find_project_root` (本地 while 上溯简版缺双布局兜底);
  **f** `openocd_telnet`: 新增 `parse_hex_addr` (地址必须 0x 前缀十六
  进制, 十进制 "134217726" 曾被 int(x,16) 静默误读) + 地址类动作在启动
  OpenOCD 前显式解析, 非法 → invalid_address 错误契约; **--exe 缺省
  None 走 resolve_param 链 (cli>config.exe>machine.json>PATH, 旧
  default="openocd" 使配置永不生效 — 行为变更)** + gdb/telnet 端口缺省
  None 读工程配置 (openocd 段 gdb_port/telnet_port), 非整数 →
  invalid_config 契约; **g** `openocd_run` operation_mode 非数字 →
  invalid_config JSON 错误契约 exit 1 (旧版裸 ValueError traceback;
  附带 output_json 的 reconfigure 加 StringIO 重定向守卫); **h** 三入口
  `ROOT_DIR=parents[2]` 无效锚清除 (指向仓外 D:\ 层, 插 sys.path 从不
  命中); **i** `capture_semihosting`+`serial_mux` Popen 补
  `hidden_subprocess_kwargs()` (Windows 不弹控制台窗; serial_runtime
  增补该再导出); **j** `save_json_file` 写失败 finally 清 .tmp 残骸;
  **k** `get_serial_config` 注解修正 `tuple[dict | None, dict]`。
  验收 = 22 钉全绿 + 全量回归 (合流时 Claude 复审重点抽查项)。
  （zc/hardware @ 4e7ccd2，待审）
- **F-155 (T8v2/N-3) openocd 构造性标记法 — flash/erase 完整性证据，feat+test，openocd_run.py / tests/test_openocd_n3_marker.py (新)**:
  OpenOCD 克隆适配器偶发打印吓人文案 (Error:/Warn: 行) 但脚本实际完整跑完
  ——旧"退出码 + 措辞嗅探"两头吃亏。flash/erase 命令串尾追加
  `echo MARK_ACTION_DONE`, 只有脚本真跑到底标记才在场; **成功 = exit 0
  且标记在场**, exit 0 但标记缺席 → `action_incomplete` 拒绝按成功入账
  (构造性证据优先于退出码); 失败措辞行收集进 `details.backend_warnings`
  (截尾 10 行) **不改判**; probe/targets 只读动作不上标记 — rc!=0 +
  jtag_tap/core 实证的既有豁免原样保留 (F-090 契约不动)。在 F-154 的
  f/g/h 改动之上叠加 (同文件, 顺序按任务清单 T8 在 T10 之后)。
  测试 `tests/test_openocd_n3_marker.py` 5 例 (三条验收 mock 钉: 标记在
  串尾且成功 / 措辞行留痕不改判 / exit 0 无标记 → action_incomplete;
  rc!=0 → command_failed 不变; probe 反向钉), test_hw_lease 假 openocd
  输出补标记 (夹具随契约同步)，先红后绿。
  （zc/hardware @ c28812c，待审）
- **F-156 (T9v2/P2-1) serial 族剩余收编 — 规范输出/公共骨架/状态映射/扫描去重，refactor+test，serial_runtime / serial_monitor / serial_hex / serial_send / serial_log / serial_scan / openocd_runtime / openocd_run / openocd_gdb / openocd_itm / openocd_telnet**:
  ① **output_json 规范版**: serial_runtime 新增 `output_json` (indent=2,
  原 send/log/scan 本地副本形态) 与 `output_jsonl` (紧凑单行, 原
  monitor/hex JSON Lines 形态) — 两种字节形态不可互替, 五入口本地副本
  删除改 import, 身份钉+逐字节钉锁死 (实测 reconfigure+print 与 buffer
  直写在真实 stdout 字节一致, 取 print 形兼容测试缝; output_json 自
  runtime_common 再导出列表移除, F811 清零); ② **公共骨架**:
  `resolve_serial_config` (取配置→失败分流→写回确认配置) +
  `connect_serial` (开串口+mux 警告) — 四工具 85% 同文块删除, fail 回调
  注入各家 error_exit 签名差异, mux 警告文案经 mux_warn 参数化
  (monitor/hex/log 与 send 的文案差异保留); monitor 的正则编译等中间步
  原顺序保留; ③ **PARITY_MAP ×4 死码删除** (monitor/hex/send/log 模块级
  定义零引用; open_serial_port 内功能性本地映射保留); ④ **_state_lookup
  ×3.5 收编 openocd_runtime.state_lookup** — run/gdb/itm 三份逐字拷贝 +
  telnet 内联第四份合并为超集单实现 (gdb 的 gdb_port/telnet_port/
  elf_file/debug_file + run 的 flash_file 并入, 各入口按需取键), 四入口
  `_state_lookup` 改别名 (调用面不变); ⑤ **serial_scan** 本地 40 行扫描
  副本删除改委托 `serial_runtime.scan_serial_ports` (load_chip_map 保留
  — test_zero_cov_finish 钉在; 错误态 ports None→[] 收敛, main 只判 err
  行为不变)。
  测试: 新 `tests/test_serial_dedup.py` 12 例 (身份钉×2/字节钉×2/死码×1/
  scan 委托×1/骨架×6) + test_openocd_dedup 补四入口 _state_lookup 身份
  钉; 共享测试缝迁移: test_serial_log_record 改 patch
  resolve_serial_config/connect_serial, test_zero_cov_finish 的 scan
  错误态断言与 hex json-mode 假 stdout 随收编更新 (共享测试文件改动
  记账); 全量 840 例仅 9 例本机 WSL 环境失败 (CI ubuntu 正常)。
  （zc/hardware @ 4aead90，待审）
- **F-157 (T10b/P2-3) 双源收敛 — 判据/时间戳/哈希/原子写/咒语五族归一，refactor+test，expectations.py / expectations_lint.py / wb_common.py / runtime_common.py / verify.py / hardfault.py / feedback_db.py / release.py / release_audit.py / gen_periph.py / phase_minus_one.py / rm_lookup.py / coverage_lint.py / duration_profile.py / fsd_coverage.py**:
  ① **expectations E2~E8+E12/E13 双写收敛**: 新增
  `expectations.item_rule_errors(item)` 单一判据源 (check_forbidden_fields
  同款 (code,core) 模式), loader (首条 raise) 与 lint (全量收集) 双消费方
  拼接各自的 label 形态 — 消息文本逐字保持; E2 id 重复 (跨条目) 与 E9
  min>max (结构矛盾) 仍归 lint 专项 (loader 不查的语义分工不变);
  ② **now_iso 三份收编**: verify/hardfault/feedback_db 的 UTC+8 硬编码
  本地版删除, 统一 runtime_common 共享版 (`datetime.now().astimezone()`)
  ——**时区口径变化: UTC+8 固定 → 本机本地时区** (checkpoint_ledger:10-12
  有账; 本机即 +08:00 零可见变化, 非 +08 时区机器上新台账时间戳随本地
  时区), CHANGELOG 记账; ③ **sha256_file ×2 收编** wb_common (release/
  release_audit); ④ **load_ref ×3 收编** wb_common (gen_periph/
  phase_minus_one/rm_lookup, REF_PATH 同迁); ⑤ **原子写行尾统一**:
  runtime_common.save_json_file 补 newline="\n" 与
  wb_common.atomic_write_json LF 口径对齐 (此前 Windows CRLF/LF 两套,
  注释固化 + 收敛); ⑥ **feedback_db 改 wb_common.atomic_write_json**
  (save_feedback_db/save_calibration; F-014 .corrupt 兜底保留) +
  test_writeback_guards 新增 FeedbackDbAtomicWriteGuardTests (损坏读 →
  .corrupt 现场 → 原子写回 → 零 tmp 残骸); ⑦ **UTF-8 reconfigure 咒语 ×5
  收编** `wb_common.force_utf8_streams` (coverage_lint/duration_profile/
  expectations_lint/feedback_db/fsd_coverage; StringIO 无 reconfigure 静默
  跳过)。
  测试: test_writeback_guards +1 类 (feedback_db 原子写卫兵) — 其余靠
  既有 841 例全量回归零语义漂移钉死 (lint E1~E13 消息、loader 报错文案、
  发布记录字节全部原样)，先红后绿。
  （zc/hardware @ f382438，待审）
- **F-158 (T11/P2-4) gen_periph 数据外置 + phase_minus_one 占用表外置，refactor+test，data/stm32f103-gen-maps.json (新) / gen_periph.py / phase_minus_one.py**:
  ① **gen_periph 数据外置**: GPIO_BASE/GPIO_CLOCK_BIT/GPIO_CR_OFFSET/
  GPIO_MODE_MAP (CNF:MODE)/TIM_CH_PINS/TIM_CLOCK_BIT/TIM_BUS/
  TIM_IRQ(函数内 irq_map)/I2C_CLOCK_BIT/SPI_CLOCK_BIT/SPI_BAUD_DIV/
  I2C_SPEED_MODES 十二张表外置 `data/stm32f103-gen-maps.json` — 生成器
  纯逻辑, 数据单一事实源; 载入后还原与旧字面量完全相同的内存形态
  (tuple 键/整型键/元组值: JSON "TIM2:1"→("TIM2",1), "100000"→100000,
  list→tuple), 全部调用点与 argparse choices 零改动。**硬验收: 黄金母版
  生成物逐字节不变** — test_gen_periph 黄金钉与语法烟测 67 例原样全绿
  即证。② **phase_minus_one 占用表外置**: 仓内硬编码 FIXED_PINS (维护者
  adc-oled 专属引脚占用, 数据走私) 删除, 改读工程
  `.workbench/fixed_pins.json`; **缺省 (文件不在场) 跳过冲突检查不报错**
  (check_pin_conflicts 第三参 None → OK+skipped 说明); check_pin_conflicts
  未用 ref 参清除; run_check 死参 features (解析即弃) 删除, --features
  CLI 旗标同删 (从未参与判定); run_check 增 workspace 形参 (main 经
  find_project_root 注入)。测试: test_zero_coverage_pure 的 pin_conflict
  用例改传占用字典 + 新增 skip 分支钉, run_check 冒烟调用随签名更新
  (共享测试文件改动记账)。
  （zc/hardware @ d18cbee，待审）
- **F-159 (T12/P2-7) 测试套加固 — 三处易碎钉根治，test，test_gcc_build.py / test_verify_failure_paths.py / test_serial_mux_lifecycle.py**:
  ① `test_gcc_build_source_uses_ms_conversion` 文本钉 ("* 1000" 子串匹配)
  **AST 化**: 遍历 gcc_build.py 的 make_timing Call 节点, 断言实参子树含
  Mult×1000 BinOp — 换行/空格/写法漂移不再假红假绿 (行为钉
  test_timing_ms_is_milliseconds_not_seconds 兜底不变); ②
  `test_verify_failure_paths` 两处 argv 位置索引 `call_args.args[0][3]`
  → 按值定位 `cmd[cmd.index("--log") + 1]` — feedback_db 命令行参数顺序
  调整不再误读; ③ `test_serial_mux_lifecycle` 端口 29876/29877 硬编码 →
  `serial_mux.find_free_port()` 动态空闲口 + 死亡标记 setUp 先清 +
  addCleanup 兜底 — 全局 tempdir (tempfile.gettempdir()/serial_mux/) 的
  跨运行残留不再假绿/假红。
  （zc/hardware @ 3ec908b，待审）
- **F-160 (T13/P1-4) verify.py main() 拆分 — 550 行编排分解为九段纯接线，refactor，verify.py**:
  B-1/N-1/N-2/C-1/N-4/N-3 全部进仓后的行为零变更重构 (机械块级搬移, 零改
  写): `main()` 瘦身为 parse→doctor 分流→pipeline 三行接线; 新增九段 —
  `_parse_args` (argparse 装配) / `_run_doctor` (诊断分支) /
  `_prepare_context` (工程根发现+配置/版本装载) / `_run_build_step`
  (build+analyze+重试) / `_run_flash_step` (设备锁+flash+重试) /
  `_run_capture_step` (sim/rtt/semihosting 三后端分派) / `_run_judgement`
  (HardFault 检测+物理门控+四态判定+顶层 status) / `_finalize_run`
  (post_reset+租约释放+失败现场+落账+checkpoint+唯一出口) / `_run_pipeline`
  (编排骨架串接)。早退 sys.exit 语义、exit 0/1/2 契约、_JUNIT_OUT 与
  WORKSPACE 模块级状态、全部步骤函数调用面原样保留。
  **硬验收**: ① 全量 842 例零测试文件修改仍全绿 (仅本机 WSL 缺席的 9 例
  hooks 环境失败, CI ubuntu 正常); ② `--json` 输出逐字段结构一致 —
  sim-demo 端到端实跑比对拆分前后顶层/steps/capture/verify 键集合与
  status/evidence/records/post_reset 值完全相同。顺手收 verify.py --doctor
  帮助文本 "四键→三键" 一行 (F-131 拆挂项; doctor.py 侧 F-131 已改)。
  （zc/hardware @ bbe9295，待审）

- **F-145 (T1/B-1 v2 修订) 机器级设备锁 — OS 级文件锁 + 用户目录 device-locks，feat+test+docs，hw_lease.py (新) / verify.py / openocd_run.py**:
  同一探针/板子同时只被一个 agent 占用——这是 P1-3 (F-127 state 写锁) 的
  功能级答案: state 锁防数据竞争, 设备锁防硬件资源竞争 (两个并发 verify 抢
  ST-Link, 后者烧到一半被前者复位)。设计按总工单 v2 修订三点: ① 锁本体 =
  OS 级文件锁 (Windows `msvcrt.locking` / POSIX `fcntl.flock`, 非阻塞独占
  1 字节), **进程崩溃 = OS 自动释放, 不做 PID 探活 (F-117: Windows os.kill
  是 TerminateProcess) 不做 mtime 超期回收** (OS 锁无泄漏, 无需兜底);
  ② 锁位置 = 机器级用户目录 `%USERPROFILE%\.embedded-toolkit\device-locks\
  <device>.lock` (同一台机两份 clone 互斥), 元数据 acquired_at/pid/token/
  purpose/workspace 写同名 `.meta.json` 旁车 (崩溃残留由下次成功获取覆写);
  ③ 冲突 fail-fast → error 含 `resource_busy` 并点名持有者 purpose +
  acquired_at, `--lease-wait N` (verify/openocd_run 双 CLI + acquire(wait=N))
  有界等待 (0.2s 轮询)。接入点: verify flash+capture 段全程持有 (胜利方
  flash 执行瞬间锁在场; 正常出口 / flash_failed / capture 三处失败早退 /
  HIL 守卫拒绝 / capture 超时 (_finish_capture_timeout 新增 lease kwarg) /
  HIL capture 守卫拒绝共七类出口全释放), openocd_run flash/erase 动作粒度
  acquire→subprocess→finally 释放 (probe/reset 只读不抢), 默认设备名
  "stlink" 两工具同名互斥, `ETK_DEVICE_LOCK_DIR` 支持多环境重定向。
  hw_lease.py CLI (status/acquire) 供人工排查; release 子命令如实说明
  "OS 锁只认持锁 fd, 不能跨进程代放"。README 工程契约节补设备锁段。
  测试 `tests/test_hw_lease.py` 18 例: 验收五条 (获取含旁车字段 / 冲突
  fail-fast 点名持有者 / 正常释放可重取 / **真实 subprocess 持锁再 kill
  后立即可重取** / 与 F-127 state 锁共存互不干扰) + 伪造 lease dict 不可
  释放 / 有界等待成败两侧 / 设备名命名空间 / 环境重定向 / verify 集成
  四钉 (一成一败, 败方 exit 2 报错可行动) / openocd_run 集成四钉
  (flash/erase 上锁, probe 零 acquire, resource_busy code)，先红后绿;
  全量 743 例仅本机 WSL 缺席的 9 例 hooks 环境失败 (CI ubuntu 正常)。
  （zc/hardware @ 17232a5，合流待协调）
- **F-146 (T2/A-1 v2 retro-fit) evidence 命名对齐 AEL 四档 + 发布记录 fidelity 契约 + approve 批准回填，feat+test+docs，verify.py / release.py / release_audit.py / README**:
  F-128 落地的三档证据分级按总工单 v2 修订对齐 agentic-embedded-lab 的
  claim+fidelity 五级命名 (裁剪 model_dependent): `real-hardware` →
  `hardware_validated`、`simulator` → `simulation_validated`、`static` 不变,
  新增第四档 `production_approved`——**一次性切换不留别名** (仓内无外部
  消费方, 行为变更由本条目与 README 注记说明迁移)。verify.py 新增
  EVIDENCE_LEVELS 四档元组; production_approved 不由 verify 产出, 是
  release_audit 新增 `--approve <tag>` 在发布后对 hardware_validated 记录的
  人工批准回填——record 必须 ① 存在可解析 ② R1~R8 审计无 fail ③ 现有
  evidence == hardware_validated (仿真/静态/已豁免记录不配"投产"), 通过后
  原子写 (F-022 同款 tmp+replace): evidence 翻转 + `production_approved_at`
  批准留痕 + fidelity_boundaries 追加批准声明, signature 保持留空不假装
  已签; R8 对 production_approved 缺批准留痕 = fail (手工改值视同篡改),
  带留痕 = pass。release.py: G2 门措辞同步新命名; 发布记录补 fidelity
  契约字段——`fidelity_boundaries` 按证据等级落"证明了什么/没证明什么"
  边界声明 (默认值表 _FIDELITY_BOUNDARIES, 显式传入胜出)、`limitations`
  缺省空列表 (不虚报)、`signature` 留空占位。release_audit 模块定位从
  "只读"改为"默认只读, --approve 唯一写路径" (模块 docstring 同步)。
  README 证据分级表改四档 + 迁移说明 + fidelity 字段说明。
  测试: test_verify_evidence +1 例 (EVIDENCE_LEVELS 四档契约 + verify
  运行永不产出 approved), test_release +2 例 (fidelity 契约默认/自定义),
  test_release_audit +6 例 (approved 缺留痕 fail / 带留痕 clean / approve
  回填主路径含 signature 不动 / 非真机证据拒绝 / 篡改记录拒绝 / 幂等),
  既有 evidence 字面量全量改名 (9+6+4 处); 全量 752 例仅本机 WSL 缺席的
  9 例 hooks 环境失败 (CI ubuntu 正常)。
  （zc/hardware @ 2d3e9b4，合流待协调）
- **F-147 (T3/N-1) verify --junit-xml JUnit 报告旁路，feat+test+docs，junit_xml.py (新) / verify.py**:
  CI 测试面板只认 JUnit XML — verify 的四态判定与 preflight 拒绝此前在
  GitHub Actions test report 里不可见。新增 `scripts/junit_xml.py` (生成
  逻辑全部住这里, 纯函数可测), verify.py 只做最小接线 (argparse + 唯一
  出口汇点 _output, 模块级 _JUNIT_OUT 由 main 设置): 映射契约按总工单
  v2 N-1 全文——expectations 逐条 → testcase; pass → 直认; fail →
  `<failure type="fail">`; xpass → `<failure type="xpass">` (XPASS 判红,
  文案提示翻转 xfail); **xfail 未翻转 → `<skipped>`** (欠条不是通过,
  报告不计失败, 文档明写); lint/preflight 拒绝 (build/flash/capture 失败
  等没跑到判定的状态) → 期望清单逐条 skipped (ID 从 workspace 的
  expectations.json 现读) + 一条 preflight `<error>` case 点名 status/error;
  **只写实测时间** (testsuite time = elapsed_sec 正数才写, testcase 不编造
  per-case 时长); 父目录自动创建; 写失败不抛 — result 记 `junit_xml_error`
  且**拉低退出码** (ok 判定 + 报告没落盘 = exit 1, CI 必须知情报告缺失);
  早退运行同样经 _output 出报告 (preflight 形态)。
  测试 `tests/test_junit_xml.py` 15 例: 四态映射 / preflight 全 skipped+
  error / 无期望仍留 error case / XML 可解析+计数正确 (failures=2 含
  xpass, skipped=1) / 特殊字符 id 转义不破格式 / time 只在实测时写 /
  父目录自动创建落盘可解析 / 写失败错误信封 / main 端到端 / 写失败拉低
  退出码; 全量 762 例仅本机 WSL 缺席的 9 例 hooks 环境失败 (CI ubuntu
  正常)。
  （zc/hardware @ 0f89c69，合流待协调）
- **F-148 (T4/N-2) 期望判定三件套 — 行终止符防早判 / ordered 按序 / record 命名捕获组，feat+test+docs，expectations.py / expectations_lint.py / verify.py**:
  ① **行终止符语义 (防早判)**: "未终止的值超时才判"——判定发生在采集窗
  超时后, 全文 (含未终止尾行) 参与匹配; 当存在已终止前缀而命中避开它
  (值只落在未终止尾行) 时, 结果行标注 `unterminated_hit: true` (值可能
  在窗口关闭瞬间被截断, "mv=319" 实为 3192 前缀, 数值断言消费方谨慎采信),
  **状态不变零回归** (全文无任何终止行时不标注——半主机收尾常无换行, 无
  相对信号可归因; 该语义取舍登记, 主控可否决)。② **ordered: true 按序
  命中**: texts 依次 find(自上一命中末尾)、patterns 依次
  re.search(output, pos)(自上一 match.end()); 默认 False 既有"任意位置
  命中"逐字节不变; capture_group 数值断言仍作用于 patterns[0] 首个
  match。③ **record 命名捕获组**: patterns[0] 全量匹配 (finditer), 每次
  匹配一行 {组名: 值} — 行级 results[*].records + verify 顶层 `records`
  平铺数组 ([{id, 组名: 值}, ...]); 与 capture_group/min/max **互斥**
  (全量记录 vs 首匹配定界, 二选一), loader 四重校验 (非空字符串数组/
  仅与 patterns 搭配/互斥/命名组须在 patterns[0] 定义) 抛
  ExpectationError, lint 新增 **E12** (record 同判据) 与 **E13** (ordered
  须为布尔), 判据单一事实源不另起分叉。
  测试 `tests/test_expectations_f148.py` 17 例 (独立文件—避免与 P2-3
  双写收敛的共享测试冲突面): 尾行标注/无终止行不标注/截断值仍按数值边界
  fail/标注不翻四态 (含 xfail+尾行命中仍 XPASS 红)/ordered 文本与正则
  顺序成败/无 ordered 键零回归/ordered×capture_group/records 行级+顶层
  平铺/多命名组/无命中空数组/loader-lint 校验×6 (先红后绿);
  test_verify_expectations 的 master 基线钉按新增 records 聚合键同步
  (共享测试文件改动登记)。全量 782 例仅本机 WSL 缺席的 9 例 hooks 环境
  失败 (CI ubuntu 正常)。
  （zc/hardware @ 500bbcf，合流待协调）
- **F-149 (T5/C-1 spike) qemu-system-arm 跑 STM32F103 可行性 — 结论 GO，docs，spikes/c1-qemu-spike/ (新, 可回放现场)**:
  实测环境 QEMU 11.1.0 (Windows x64, winget `SoftwareFreedomConservancy.QEMU`
  一键装; **CI 安装路径: ubuntu `apt-get install qemu-system-arm`**) +
  arm-none-eabi-gcc 10.3.1。机器模型 `-M stm32vldiscovery` (STM32F100,
  Cortex-M3) 确认在 QEMU 支持列表 (另一 M-profile 选项仅 olimex-stm32-h405,
  Cortex-M4)。三个实验 (spikes/c1-qemu-spike/ 可回放):
  ① printf 全文采集 ✓ — semihosting SYS_WRITE0 (`-semihosting-config
  enable=on,target=native`) 输出走 **stderr** (与 OpenOCD semihosting 采集
  stdout+stderr 合并的既有口径一致); ② 超时行为 ✓ — 固件自旋时外部 kill,
  部分输出仍完整可采 (对齐 F-003 归因纪律: 采集超时是工具故障不是程序无
  输出); **关键发现: M-profile 旧 SYS_EXIT(0x18) 被 qemu 无声忽略, 进程
  永不退出** — 必须 SYS_EXIT_EXTENDED(0x20) (r1 指向 64 位
  {ADP_Stopped_ApplicationExit, 0} 内存块) 才干净退出, sim 后端模板与
  C-1 实现须用 0x20, 自旋固件依赖外部 timeout; ③ 附加: USART1 直写 DR
  转发到 `-serial stdio` 的 **stdout** (qemu 不 gate RCC 时钟位) — UART
  备选通道可行。Renode 未测 (本机未装): qemu 通路已证足, 方案定为
  **qemu-system-arm + semihosting 单一后端** (不引 Renode 双方案)。
  结论 **GO** → T6 立项: capture_sim.py 驱动 qemu, method="sim",
  evidence="simulation_validated" (不进发布门禁, F-146 呼应)。
  （zc/hardware @ 335b57e，合流待协调）
- **F-150 (T6/C-1) capture.backend: "sim" — 无板全链路闭环，feat+test+docs，capture_sim.py (新) / verify.py / examples/sim-demo (新) / ci.yml / machine.example.json / .gitignore**:
  基于 F-149 spike GO 结论, qemu-system-arm + semihosting 单一方案 (不引
  Renode)。新增 `scripts/capture_sim.py`: 命令形态 `-M <machine> -kernel
  <elf> -semihosting-config enable=on,target=native -nographic -no-reboot`
  (spike 实证); exe 解析链 config capture.sim.exe > machine.json **qemu_exe
  (新可选键, 模板已注)** > PATH > 缺省名; 控制流契约与 capture_semihosting
  同款 (成功返回 (stdout, stderr) / 超时 SimTimeout 携 proc 不收尸 / 异常
  原样抛), communicate 双管道排空 + stdin DEVNULL (F-123 readline 地雷不在
  本路径); qemu 缺席的 WinError 2 裸抛改为点名 exe+解析来源的可行动报错。
  verify.py 分派: backend=sim → flash 步骤 skipped (带 reason), 内核 =
  config capture.sim.kernel > 构建 details.elf_file (--no-build 走
  state.json last_build), 缺内核/文件不在场 → capture_failed 早退;
  capture method="sim"、evidence="simulation_validated" (F-146 四档直接
  生效); **不持 F-145 设备锁、不跑 F-046 HIL 守卫、不落 HIL 台账** (sim 非
  硬件步骤, CI 可并行); post_reset 自动 skipped; 判定逻辑零改动——同一份
  expectations 四态判定, F-148 record 命名捕获组在 sim 下照常提取。
  _finish_capture_timeout 参数化 method/tool (sim 超时复用 F-003 收尸/
  归因出口, OpenOCD 口径逐字节不变)。**CI 大奖**: examples/sim-demo
  (微型 Makefile 工程 + 自带 .workbench 契约, 四态齐备含 F-148 record)
  + ci.yml 新 `sim-demo` job (apt 装 qemu-system-arm + gcc-arm-none-eabi →
  写 CI machine.json → 端到端 verify)——"陌生人克隆"路径第一次覆盖
  build→capture→judge 闭环判定链。施工实录: -O1 下固件 fault 进不完整
  向量表 (HardFault 向量取到 .text 字节被当指令执行 → qemu 报 Unsupported
  SemiHosting SWI 0xdeadbeef), 补全向量表 + 模板定 -O0 后端到端绿;
  .gitignore 为 sim-demo 的 .workbench 契约文件开白名单 (state/build 仍
  不入库)。README: 5 分钟上手加"无板闭环"路径, 证据表更新, 工具速查补行。
  验收: 本机 Windows 真跑端到端绿 (build 0.3s → qemu 0.4s → 四态判定
  status=ok, evidence=simulation_validated, records=[{id: FR-ADC-01,
  mv: "3192"}]); 真机路径回归零影响 (791 例仅 9 例本机 WSL 环境失败);
  文档明写 sim 证据不进发布门禁 (README 证据表 + G2 契约)。
  测试 `tests/test_capture_sim.py` 9 例 (解析链×3/命令形态+stdin DEVNULL/
  SimTimeout 携 proc/端到端 green 钉 flash-skip+method+evidence+零锁/
  缺内核 capture_failed/sim-demo 契约 lint+四态齐备)，先红后绿。
  （zc/hardware @ a6c277f，合流待协调）
- **F-151 (T7/N-4) evidence_export — verify 结果/发布记录 → GITHUB_STEP_SUMMARY，feat+test+docs，evidence_export.py (新) / ci.yml**:
  CI 测试页要人话摘要 — verify --json / 发布记录渲染成 Markdown 判定报告
  (四态表 ✅/❌/⏭/❌ + record 提取值 + F-146 fidelity 字段 + junit 报错
  留痕 + 采集输出前 500 字符折叠块), 写入 GITHUB_STEP_SUMMARY (追加语义);
  环境变量不在场/写失败时回落 --out (缺省 job-summary.md)——**if: always()
  安全**: 输入缺失/非法 JSON 只 exit 2/1 报错不抛 traceback, CI 失败运行
  的摘要步骤不会把绿变红。脱敏统一走 `redact()`: Windows 盘符路径与
  POSIX 家目录族 → `<path>` (workspace 根/TOOLKIT_ROOT → `<toolkit>`,
  长前缀先替换), **machine.json 内容从不被读取** — 摘要可能进公开 CI 页
  (SENSITIVE_FINDINGS 脱敏口径)。ci.yml sim-demo job 接入实际用法
  (`tee verify-result.json` + `if: always()` 摘要步骤) 作文档示范。
  测试 `tests/test_evidence_export.py` 12 例: 渲染×3 (四态标记/record 值/
  junit 报错/发布记录含批准留痕与签名占位) / 脱敏×3 (双平台路径/长前缀
  优先/machine.json 键值零进入红线钉) / 降级落盘×3 (无 env 回落/GH 追加
  语义/GH 写失败回落并留痕) / CLI×3 (端到端脱敏输出/非法 JSON exit 2 无
  traceback/缺失输入 exit 2)，先红后绿; 全量 803 例仅 9 例本机 WSL 环境
  失败 (CI ubuntu 正常)。
  （zc/hardware @ 63dbb78，合流待协调）
- **F-152 (T8/D-1) 真机 CI 冒烟 workflow — self-hosted runner 门控，feat+test，hw-smoke.yml (新) / tests/test_workflows_valid.py (新)**:
  新增 `.github/workflows/hw-smoke.yml`: `workflow_dispatch` 手动触发 +
  `if: vars.HW_RUNNER_READY == 'true'` 仓库变量门控 — **仓库未配置真机
  runner 时永不运行**, 主 CI (ci.yml) 零影响。内容: self-hosted windows
  runner 上 doctor 环境矩阵 (含 SWD 连通性) → 仓库变量 `HW_VERIFY_PROJECT`
  在场时对指定真机工程跑完整闭环 verify (schedule origin, F-046 审计
  口径; 未设置则仅 doctor 冒烟——真机工程不在仓内, 指向由维护者配置) →
  F-151 evidence_export 摘要 (if: always())。与主 CI sim-demo job 的分工
  文档化: sim 无板闭环在主 CI, 真机 hardware_validated 证据走本 workflow。
  验收: 双 workflow `yaml.safe_load` 本地校验通过 (施工中修掉两处
  "name/run 值含 ': ' 被 YAML 当映射"错误——一处在本文件, 一处在 F-151
  的 ci.yml machine.json 步骤); 回归钉 `tests/test_workflows_valid.py`
  3 例 (双文件可解析 / 门控契约钉含 `on:`→True 的 YAML 1.1 坑 / 主 CI
  六 job 清单完整; pyyaml 缺席环境自动 skip——CI 各 job 零第三方依赖
  纪律不破)，先红后绿。
  （zc/hardware @ 012691b，合流待协调）
- **F-153 (T9/D-3) README 生态位与路线图更新，docs，README.md**:
  新增"生态位"短节: 同类一句带过 (agentic-hil 的 MCP+租约+plan 门禁 /
  AEL 的仿真控制面与 claim+fidelity / pytest-embedded、Renode 的仿真判定
  后端 / hardci、jlink-mcp 的分发路径), 强调本仓独有链路——需求→判定→
  发布门禁→事后审计→知识沉淀的完整治理链六点 (四态判定+XPASS 判红 /
  FSD 对账 / G0-G3+R1-R8 证据四档门禁审计 / feedback 校准 / 寄存器知识库
  +代码生成 / 构建错误知识库)。路线图重构为两节: "已落地/立项方向"登记
  MCP 接口 (F-130 落地)、无板仿真闭环 (F-150 落地+spike F-149)、分发形态
  (PyPI/uvx/插件——**已立项未实施**, 风险点=包数据定位策略)、真机 CI 冒烟
  (F-152 门控形态), 各带调研来源; "已知遗留"节保持 F-031/F-032 等既有
  编目不动。措辞逐条对仓内实际能力核对过 (mcp_server.py / capture_sim.py /
  hw-smoke.yml 均在库), 禁止超前宣传 (F-124 纪律): 分发形态如实标"未实施"。
  （zc/hardware @ 482ba5d，合流待协调）

## Unreleased — 2026-09-12（F-117~ 第三方审查工单第一批 P0 逐条清账）

- **F-117 处置（工单 P0-1 is_mux_alive Windows 杀进程，fix+test，serial_runtime.py / serial_mux.py）**:
  `os.kill(pid, 0)` 在 Windows 上非探活——CPython 对非 CTRL 类信号一律
  `TerminateProcess`，每次开串口（`open_serial_port → get_mux_info → is_mux_alive`）
  都会无条件杀掉被探测的 mux 进程；PID 不存在时 OpenProcess 失败抛 SystemError
  穿透 `(ProcessLookupError, PermissionError)` 捕获面。修复: Windows 分支改
  TCP 连通性探测（`connect_ex(("127.0.0.1", tcp_port)) == 0` 即存活，mux 本就是
  本机 TCP 服务），POSIX 保留原语义。`serial_mux.py:449-459` 的逐字拷贝删除，
  改 import 共享实现（收编方向见工单 P2-1，本项完成 is_mux_alive 一半）。
  当前被 mux 的 socat Linux 门掩蔽、`--no-pty` 落地后即爆，属提前拆弹。
  测试 `tests/test_mux_alive_probe.py` 6 例: Windows 零 os.kill / 死端口 False /
  缺 tcp_port False / POSIX 双 pid os.kill / 身份钉 `serial_mux.is_mux_alive IS serial_runtime.is_mux_alive`。
- **F-118 处置（工单 P0-6 EXC_RETURN 解码索引错误，fix+test，hardfault.py）**:
  `diagnose` 旧实现 `idx = lr & 0xF` 配 4 项表——合法值 0xFFFFFFF1/F9/FD 分别
  落 1/9/13，最常见的 0xFFFFFFF9（返回 Thread/MSP）恒落 "unknown"，0xFFFFFFF1
  被错标。修复: 按 ARMv7-M 语义 bit3(返回模式)/bit2(返回堆栈) 取
  `idx = (lr>>2)&3` 映射回 F1/F5/F9/FD，文案改为"返回到哪"口径，保留值 F5
  （M3 上 Handler+PSP 非法组合）显式标注不再静默 unknown。
  测试 `ExcReturnDecodeTests` 4 例（F1/F9/FD/F5，先红 4 后绿）。
- **F-119 处置（工单 P0-4 gen_adc 通道域校验，fix+test，gen_periph.py）**:
  `gen_adc` 对 ch 零校验——`--ch 20` 写 SMPR1 保留位（硬件静默无效），负数
  生成负位移 C 代码（UB）；且 adc 分支是 `main()` 里唯一裸 `print` 出口
  （F-103 的 `_emit` ERROR→exit 1 收敛漏网），错误产出恒退 0。修复: 库级
  `0<=ch<=17` 显式 ERROR（仿 gen_pwm F-103 三连守卫），CLI 改走 `_emit`，
  16/17 内部通道（vrefint/temp）合法放行并生成"无需外部引脚"注记，
  `--ch` help 同步 ADC 范围（不设 choices: PWM 1-4 / ADC 0-17 共用参数，
  choices 取交集会伤另一侧）。测试 `GenAdcTests` +4 例（越界/边界/内部注记/
  CLI exit 1，先红 4 后绿）+ `test_adc_type_requires_pin` 等既有钉零改动。
- **F-120 处置（工单 P0-2 JSON 模式失败退出码为 0，fix+test，openocd_run/gdb/telnet + serial_mux）**:
  执行失败的 JSON 出口只 output_json 不退出（run `return`、gdb/telnet 落
  if/elif/else 后隐式退 0、mux main 全程无退出码），而同文件早段校验失败
  JSON 分支是 exit(1)——同一契约自相矛盾，机器消费方按 rc 判成败会漏报。
  统一为 `output_json(result); sys.exit(0 if status=="ok" else 1)` 覆盖四脚本
  执行结果出口（telnet 本地 `output_json` 拷贝暂留，收编在工单 P2-1 方向
  一并处理; 早段校验出口本就正确、零改动）。注: mux `stop` 未运行按既有
  契约是 error（not_running）→ 现在退 1，属契约统一而非回归; 全仓无
  subprocess 依赖 mux 退出码, verify.py 不在此列。
  测试 `tests/test_json_exit_code_contract.py` 8 例: 进程内 mock 驱动 main,
  error→1 / ok→0 正反各钉（先红 4 后绿），gdb 用假 proc 覆盖"真跑失败"分支。
- **F-121 处置（工单 P0-3 gdb server 启动失败孤儿进程，fix+test，openocd_gdb.py）**:
  finally 旧条件 `command != "server"` 不区分"启动失败"与"常驻服务正常退出"
  ——server 模式 ready 未达成（超时但进程仍活）时 sys.exit(1) 穿过 finally
  也不 cleanup，OpenOCD 留存独占 ST-Link。修复: `server_ready` 标志区分两态，
  仅 ready 成功的常驻 server 跳过 cleanup，启动失败经 SystemExit 照常回收。
  测试 `tests/test_gdb_server_orphan_cleanup.py` 3 例: 启动失败必 cleanup /
  ready 成功不回归 / 非 server 模式原行为零改动（先红 2 后绿）。
- **F-122 处置（工单 P0-5 gen_pwm TIM1 缺 BDTR.MOE 永远无输出，fix+test，gen_periph.py）**:
  TIM1 为高级定时器，MOE=0 时 OC 输出被硬件强制关闭（RM0008 §17.4.23）——
  旧版生成时钟/GPIO/PSC/ARR/CCR/CCMR/CCER/CR1 全套唯独缺 BDTR.MOE，编译通过
  但永远无波形（B 类静默缺陷）。TIM1 是合法输入（TIM_BUS F-077 认真处理 APB2、
  gen_timer_int 处理 TIM1 向量），故按工单推荐方案 a 补齐: timer==TIM1 追加
  `TIM1->BDTR |= (1<<15)`，TIM2~4 无 BDTR 寄存器不得误加。语法烟测的 stub
  契约本就含 BDTR 成员，`pwm-tim1-apb2` 用例即覆盖 TIM1 输出。templates/docs
  无引用（grep 零命中）。测试 `GenPwmTests` +2 例（TIM1 有 MOE / TIM2~4 反向
  钉无 BDTR，先红 1 后绿）+ 烟测 67 例全绿（本机 arm-none-eabi-gcc 在场实跑）。
- **F-123 处置（工单 P0-7 wait_server_ready 阻塞 readline 使 timeout 失效 + 长会话不排空 stderr，fix+refactor+test，openocd_runtime/gdb/telnet/itm/run）**:
  三份拷贝（gdb/telnet/itm 的 wait_server_ready）同病——`proc.stderr.readline()`
  在"进程存活但沉默"时无限阻塞，外层 while-timeout 永不可达（timeout 形同虚设）;
  且 gdb server 常驻与 itm 主循环 ready 后无人再读 stderr，OpenOCD 刷日志填满
  管道缓冲（~64KB）后自身阻塞→全链死锁。收编为 openocd_runtime 单实现（正解
  同 capture_rtt daemon 排空先例）: `_start_stderr_pump` daemon 线程把 stderr
  灌入有界队列（满丢最旧保活性），主循环 `q.get(timeout=0.1)` 非阻塞轮询墙钟
  真超时; `wait_server_ready`（gdb/telnet 口径）与 `wait_itm_ready`（itm 口径:
  全行收集/critical 即时否决/1s grace——契约原样保留）分立，itm 的 error: 词表
  与 server 版不同属真分叉不强并。同批收编 `build_openocd_cmd`（gdb/telnet/run
  三副本→参数化单实现, run 传 gdb_port=telnet_port=None 关端口行输出与旧副本
  逐元素一致; itm 扩展版 F-029 裁决保留本地）、`cleanup`（gdb/itm 逐字副本 +
  telnet cleanup_proc→单实现+别名）、itm 的 start_openocd_server 第三份逐字副本。
  四入口本地定义全删改 import 再导出。测试: 新 `tests/test_openocd_startup_wait.py`
  10 例（timeout 真生效×2 / server 口径语义×4 / itm 口径×3 / 真子进程 3.2MB 灌
  stderr 排空不死锁×1——末项即"长会话死锁"的直接回归钉）+ `test_openocd_dedup.py`
  补三件套身份钉与 itm 入 start_server 钉名单。
- **F-124 处置（工单 P1-1 CI 增加 Windows 矩阵，change，ci.yml）**:
  四个 job 全跑 ubuntu-latest，而 README 宣称"Windows 为主要开发/真机平台"
  与"Win/Linux 全绿"——CI 从未在 Windows 验证过，Windows 专属测试
  （test_verify_failure_paths 的 CREATE_NEW_PROCESS_GROUP 钉）恒 skip，宣传
  与事实矛盾。unittest job matrix 扩为 os:[ubuntu, windows]×py[3.10,3.12]
  （fail-fast:false 已有, 每平台注入 PYTHONIOENCODING/PYTHONUTF8 防中文
  stderr 在 ANSI 代码页上乱码/报错）。syntax-smoke 暂留 ubuntu（arm-none-eabi
  安装脚本平台专属, 工单允许后续再扩）。.gitattributes 现仓已有, checkout
  行尾归一行为两平台一致。**注: 本笔在 Windows runner 上的首跑属"立此存照"
  ——若暴露存量 Windows-only 失败, 按 F 编号记账修复, 不回头降级矩阵。**
- **F-125 处置（工单 P1-2 测试类定义在 unittest.main() 之后，fix，test_gcc_build.py）**:
  `MakeTimingScaleTests`（F-099 回归钉）定义在 :84-85 的 `unittest.main()`
  之后——单文件直跑时该类不被收集, 钉形同虚设。`__main__` 块挪至文件尾并
  注记原因。全仓扫描（grep 行号序比对）: 其余文件均无同类问题
  （test_release.py 无 main 块属 collect 友好而非缺陷）。验收:
  `python tests/test_gcc_build.py` 实跑 **Ran 9** 且 OK（修复前旧文件实跑
  Ran 7——两个 F-099 钉缺席）。
- **F-126 处置（工单 P1-5 CI 引入 ruff lint 门禁，change，ruff.toml / ci.yml / 30 文件清理）**:
  仓库从未有 lint/类型检查。起步: `ruff.toml` 选默认 E/F、白名单登记四项
  纯风格存量债（E501 行宽 491 / E741 19 / E701 15 / E402 3——sys.path
  bootstrap 启动模式属标准用法）；正确性类逐条处置——F541 ×136 安全自动修
  （`f"{{}}"` → 字面 `{{` 的转义行为经 gen_periph 全套母版钉验证不变）、
  F401 基线 44 处: 死 import 删除 35 处（capture_rtt.os / verify.hashlib / duration_profile.statistics（P2-6 顺带提前做一条）/ serial_runtime.signal
  / 四入口冗余再导出 / 六串口工具 Path 等——删前逐一 grep 确认无 mod.X
  属性面消费方; verify.py F-041/055/058/059 再导出有 test_doctor/test_fixture_doctor/
  test_checkpoint_ledger 钉消费, 余 9 处补 noqa: F401 声明再导出契约）、
  F841 ×9 死局部量删除
  （gen_periph.nss_port / telnet.start_time / serial_runtime.local_cfg /
  svd_to_json.incr+merged / handoff_guard.commit / verify 测试块 analyze_result）、
  F811 ×1 test_serial_mux_lifecycle 尾部重复 import 删除。ci.yml 新增 lint job
  （astral-sh/ruff-action@v3, `ruff check scripts tests`）。验收: 本地 ruff
  All checks passed + 全量 **653 例零测试文件语义改动仍全绿**（清理纯减法）。
- **F-127 处置（工单 P1-3 state.json 读改写竞态丢更新，fix+test，runtime_common.py / serial_mux.py / serial_runtime.py）**:
  F-019 的原子替换只防撕裂不防丢更新——serial_mux start 的"取快照 → 起子进程
  等数秒 → 旧快照整体覆盖落盘"与 `update_state_entry` 的无锁 RMW 互相静默回滚
  对方写入（两个工具同时 update 不同 category 同丢）。修复: 新增
  `runtime_common.state_write_lock`——O_CREAT|O_EXCL lockfile + 超时重试 +
  finally 删除，进程内 threading 锁与跨进程 lockfile 双层（lockfile 只辨进程
  不辨线程）; 陈旧锁回收只认超龄（Windows 不做 PID 探活, F-117 教训: os.kill
  在 Windows 是 TerminateProcess 不是探活; POSIX 用信号 0 真探活）+ holder==本
  pid 不回收防线程误拆; 等锁超时向 stderr 诚实告警后降级无锁执行（state.json
  是可再生缓存, 工具卡死比丢一次更新更糟），绝不改判定绝不阻塞。四处 RMW 收编
  持锁读最新再改: `update_state_entry`、serial_mux start 的僵尸清理与落盘、
  stop/status 清理路径、`get_mux_info` 探活失败清理。测试
  `tests/test_state_write_lock.py` 7 例: 双线程交错 update 双存活（写盘窗口
  拉宽复现旧竞态）/ 锁文件建删 / holder pid / 超龄锁秒抢 / 超时降级 stderr
  留痕 / mux mutate 不回滚他人条目 / 读改写调用序钉（先红后绿——红灯由
  no-lock 桩实测双更新必丢其一）。
- **F-131 处置（工单 P2-2 Keil 退役清扫收尾，fix+test+change，6 文件）**:
  ① `doctor.py` `_DOCTOR_KEYS` 移除 `uv4_exe`（与 machine.example.json
  "仓内零 Keil 引用"对齐; `load_machine`/doctor 按下标取键，旧 machine.json
  残留该键自动容忍——本机 machine.json 实测含 uv4_exe, 行为零变化只是不再
  进报告），`test_doctor` 三处键集钉同步 + 新增"旧键无害"反向钉；
  ② `failure_context.py` build_failed agent_hint 的 "ARMCC V5 C90
  incompatibility" 换 GCC 诊断语境（-Wall/C23/链接脚本越界）；
  ③ `gen_periph.py` gen_usart printf 重定向从 Keil Microlib
  `int fputc(int, FILE*)` 改 newlib 系统桩 `int _write(int fd, char*, int)`
  （fputc 在 GCC/newlib-nano 下 printf 根本不调用——重定向静默失效;
  `_write` 形态经 arm-none-eabi-gcc -fsyntax-only 四变体实测选定，含
  `#include <unistd.h>` 落在生成块内/函数体内两态）, 母版钉
  `test_gen_periph:169` 同步为 `_write` 正钉 + `fputc` 反向钉；
  ④ `gcc_build.py` artifacts 键表删死键 `axf_file`（Keil 产物, gcc details
  从不产出, elf_file 才是 GCC 侧主产物）；
  ⑤ `cube_to_keil.py` 改名 `cube_usercode.py`（git mv, 工具与 Keil 无关——
  服务 CubeMX 重生成的 USER CODE 保全）: docstring 第 4 步 "Keil 编译验证"
  改 GCC 验证、PROJECT_ROOT 锚从 `parents[1]` 死锚仓根改
  `wb_common.find_project_root` 懒解析（import 期零 IO 零 exit, 纯函数
  `extract_user_code/_dedent` 可安全 import; 命令入口 `_bind_roots()` 发现
  失败体面 exit 1 + 中文指引），`test_zero_cov_finish`/
  `test_coverage_lint_reachability` 引用同步（alias import 保留旧符号面）。
  ⑥ `machine.example.json` _help 与 doctor 实际口径核对后更新（三键预检 +
  uv4_exe 旧键容忍声明）; doctor.py/verify.py 帮助文本"四键→三键"
  **拆挂**——verify.py 是并行会话在改文件（F-128~130 工单二），单行文案
  修复并入 P1-4（verify 重构）一起做，避免搅动他人在制品。
  测试: 定向 13 模块（doctor/gen_periph/smoke/gcc_build/zero_cov/
  reachability/failure_hints/hooks/machine_fallback 等）全绿。
- **F-132 处置（工单 P2-5 文档漂移同步，docs+fix，hooks-install.md / test_hooks_behavior.py）**:
  ① `docs/hooks-install.md` "已知限制（F-096 登记, 修复待拍板）"节改写为
  "F-096 已修复"事实态（hooks 三脚本 2026-09-09 已 --cached 优先+工作树
  回落, 金丝雀组已翻转改名）；② `test_hooks_behavior.py` 模块 docstring
  从"行为记录+缺陷登记, 不是回归钉"改写为回归钉口径（与 :110 翻转注记
  对齐）；③ :74 注释 typo "System32\x08sh.exe"（写注释时 `\b` 被转义层吃掉
  成退格控制符）修为可见文本 `System32\bash.exe`——F-053 同款教训的又一例,
  docstring/注释含 `\b` 一律用 raw 字符串或双写。
- **F-133 登记（工单 P2-6 边角缺陷打包，test-only 红基线，实现移交 zc/hardware）**:
  `tests/test_p2_edge_pack.py` 16 用例 22 钉先红入账覆盖 a~k——a 过滤
  fail-closed / b 物理门 expected<=0 守卫 / c svd_to_json 死函数+meta 覆写 /
  d rm_lookup format_result 参数化 / e duration_profile 共享根发现 /
  f telnet 地址显式解析 / g operation_mode JSON 契约 / h 三入口 ROOT_DIR 死锚 /
  i Popen 平台守卫 / j save_json_file tmp 残骸 / k serial_runtime 注解。
  j 项设计注记: 真实落盘 + os.replace 失败制造 tmp（mock write_text 不落盘
  是假绿陷阱——已修）。基线实跑 **16 例全红（15 failures + 7 errors 含 subTest）**;
  实现与转绿由 zc/hardware 完成（桌面《zcode 任务清单 v2》T0 项），本条待合流补账。

## Unreleased — 2026-09-12（工单二: GitHub 同类项目借鉴落地）

- **F-128 (工单二 A-1) verify --json 证据分级字段 evidence，feat+test+docs，verify.py / release.py / release_audit.py**:
  借鉴 agentic-embedded-lab 的 claim+fidelity 概念（"仿真通过永不升级为硬件等价
  声明"）。verify 结果 JSON 顶层新增 `evidence` 字段，三档取值:
  `real-hardware`（capture 后端 rtt/semihosting 实跑）/ `simulator`（sim 后端,
  C-1 预留, 方法映射表落位即生效）/ `static`（仅构建+lint、capture 未跑成——
  build/flash 失败早退与 capture_failed 一律 static, 不给"差一点就是真机"的
  模糊地带）。实现取 main() 唯一出口汇点 `_output` 统一落字段（八处出口零
  逐点改动）, 判据 = steps.capture 实际后端, 判定 verdict 与证据等级正交。
  release.py: G1 结果透传 evidence 入发布记录; G2 新增证据等级门——非
  real-hardware 拒绝发布, `--allow-non-hardware-evidence` 显式豁免并以
  `evidence_waiver: true` 留痕入档（旧版 verify 无 evidence 键按 static 拦）。
  release_audit.py: 新增 **R8** 证据等级一致性——缺 evidence（R8 之前旧记录）
  警告; 非 real-hardware 且无豁免留痕 fail（防门禁被绕过/记录被篡改）; 有豁免
  留痕警告可见; real-hardware 带豁免留痕按字段矛盾警告。README 效果预览的
  0.2 真机实录按 F-034 诚实化原则不加字段、以加注补当前输出契约（含三档表）。
  测试 `tests/test_verify_evidence.py` 14 例（三档映射/未知 method 落 static/
  四态判定×真机与 sim 正交/早退出口不缺键/main() 成功线端到端/--no-flash 不
  降级）+ test_release 7 例（G2 证据门拦 sim/缺键按 static 拦/豁免旗标留痕/
  build_record 透传与缺省 static）+ test_release_audit 5 例（R8 四分支+static
  拦截），先红后绿; 全量 660→686 全绿（仅本机 WSL 缺席的 9 例 hooks 环境失败,
  CI ubuntu 正常）。
- **F-129 (工单二 A-2) verify 判定结束后硬件自恢复 post reset，feat+test+docs，openocd_runtime.py / verify.py**:
  借鉴 agentic-hil 的失败自恢复——"板子状态不留给下一次运行"。旧行为判定后
  无论红绿都不复位目标, 超时/卡死场景留下挂着断点或半初始化外设的板子污染
  下一次 verify。新增共享函数 `openocd_runtime.reset_target(exe, cfg)`:
  `openocd -f <cfg> -c init -c "reset run" -c shutdown` 形态, cfg 缺省与
  step_flash 同款 stlink+stm32f1x（exe 由调用方经既有 resolve 链取好传入,
  本函数不读 machine.json 保持纯函数）; 判据沿 swd_probe 内容口径
  （"shutdown command invoked" 在场且无 "init mode failed"——克隆适配器偶发
  非零退出不否决）。verify.py 正常路径判定结束后调用: flash 实际发生
  (steps.flash.status=="ok") 且 capture.post_reset 非 false 才触发, 结果落
  顶层 `post_reset`: "ok"|"failed"|"skipped"——复位失败仅 stderr 告警, 绝不
  改判 verdict; --no-flash / flash 未跑成 / 无判定的早退出口 (build/flash/
  capture_failed) 一律 skipped 不触发。6 处既有 main() 驱动测试补 reset_target
  mock（本机有真 openocd+ST-Link, 测试零触硬件纪律）。README config 片段补
  post_reset 键说明。测试 `tests/test_verify_post_reset.py` 13 例
  （reset_target 内容判据×7 含超时/OSError/非零退出容忍; main 流: FAIL 判决
  后复位被调 / 绿也复位 / 复位失败 verdict 不变 / --no-flash / post_reset:
  false / flash 失败早退不复位且无字段），先红后绿。
- **F-130 (工单二 A-3) MCP server 包装现有工具，feat+test+docs，mcp_server.py (新) / hardfault.py**:
  借鉴 agentic-hil / hardci / jlink-mcp 的第一接口形态: agent 经有界 MCP 工具
  使用本工具库, 不再靠 shell 拼装。新增 `scripts/mcp_server.py` (stdio
  transport) 六工具: run_verify / lint_expectations / gen_peripheral /
  rm_lookup / diagnose_hardfault / doctor。两条铁律第一版守住 (agentic-hil
  安全设计): ① 工具 = 对现有脚本的子进程调用透传, 零业务逻辑复制 (CLI 仍是
  唯一事实源, 注册表单一数据结构, 测试钉"每个工具映射的脚本真实存在"); ②
  入参白名单校验——未知键拒绝、值以 "-" 开头拒绝 (flag 注入)、整数边界/正则
  逐项校验、bool 显式类型检查 (True 不得冒充 ch=1)、工程根必须存在
  .workbench/config.json (不给文件系统探测面), **不给 agent 任意 shell**。
  架构: plan_tool_call (纯计划层, 校验→argv/stdin/cwd/timeout) + 
  run_planned_call (子进程透传, F-120 后 returncode 判 ok, JSON 结果与
  stderr 尾巴透传, 本层不加工语义)。MCP SDK 可选依赖 requirements-mcp.txt
  单列, 缺失时给可行动报错 (指向安装命令, 注明其余工具零依赖不受影响);
  仓根 .mcp.json.example 模板入库 (.mcp.json 已在 .gitignore, 照抄
  machine.json 模板惯例)。hardfault.py 新增 `--no-probe` 仅解析通道
  (MCP diagnose_hardfault 底座): 跳过 OpenOCD 现场读取, 仅用 --fault-text
  层 1 [HF] PC=/LR= 行出 fault_site+符号解析, 状态诚实标 parsed_text_only
  / no_fault_marker, 无 live 寄存器不伪装完整诊断。README 新增"MCP 接入"节
  (含 Claude Code .mcp.json 配置示例) + 工具速查表补两行。
  测试 `tests/test_mcp_server.py` 27 例 (注册表完整性/工程守卫×4/参数白名单
  ×6/分发计划×5/mock 子进程透传与错误透传×4/SDK 缺失文案×2/--no-probe
  专项×3 含"绝不触 run_openocd_diag"安全钉)，先红后绿。

## Unreleased — 2026-09-10（F-103~F-107 P3 清账第一轮：边界报错泛化 / 迁移告警 / ID 唯一性 / 过滤收窄 / 文档回填）

- **F-103 处置（审计 P3 数值边界组，fix+test，gen_periph.py）**: 四项
  "静默产出错误配置"统一改为显式 ERROR（F-086 报错路线泛化）——
  ① `gen_systick` LOAD 无 24 位上限（`--freq 2` → 35999999 > 0xFFFFFF
  被硬件截断; 实测边界: 最低可表 5Hz, freq≤4 报错）;
  ② `gen_usart` 低波特率 mantissa 越 12 位域（RM0008 §27.5.5 BRR
  DIV_Mantissa=bit[15:4]; USART2@300 报错, @600 起有效, 1200 反向钉不误伤）;
  ③ `gen_pwm` `ch≥5` 写 CCR5 保留位硬件静默无效 + `duty∉[0,100]` +
  `freq≤0` 除零 → 三连前置校验;
  ④ `gen_gpio` 未知 mode 静默降级 0x3 推挽（旧测试 `weird-mode` 契约
  翻转为 ERROR 钉; 既有契约测试先红后绿）+ `--mode` 加 argparse
  choices（mode_map 提为模块级 `GPIO_MODE_MAP` 单一事实源, 两处判据
  永不漂移）。新增 CLI 退出码钉: 全部 ERROR 出口经新 `_emit()` 收敛
  （exit 1, F-086 timer-int 通道行为不变——subprocess 反向钉全程保持）。
  测试 `NumericBoundaryTests` 5 例 + 契约翻转 1 例。
- **F-104 处置（审计 P3 expectations 静默失效，change+test，verify.py）**:
  `.workbench/expectations.json` 存在时 `config.verify.expect`/
  `expect_patterns` 整体不参与判定曾是**静默**行为——双配工程改 expect
  的人得不到反馈。manifest 模式检测到被遮蔽的 legacy 配置即向 stderr 打
  迁移告警（只告警不改判定）。测试 4 例（触发 + 双反向钉: 单配 manifest
  与纯 legacy 工程不得被噪音骚扰）落 `ExpectationsMigrationWarningTests`。
- **F-105 处置（审计 P3 feedback_db 同秒覆盖，fix+test，feedback_db.py）**:
  事件 ID 秒级粒度, 同秒两笔落账 → 后者覆盖前者 events/<eid>.json,
  主索引却记两条。`log_event` 自动 ID 冲突时追加 `-2`/`-3` 序号（显式
  传入 ID 尊重调用方不改名; 首笔 ID 格式不变向后兼容）。测试
  `SameSecondEventIdTests` 2 例（固定时间戳三连落账 ID 互异 + 三笔详情
  互不覆盖在盘; 显式 ID 反向钉）。
- **F-106 处置（审计 P3 capture 黑名单误杀，fix+test，failure_context.py）**:
  `_filter_capture_lines` 第二层从**子串包含**黑名单收窄为**行首锚定
  正则**白名单化噪声形态——固件正文含 "GDB"/"http://"/"dropped" 不再被
  整行误删（旧 `xPSR:`/`Info :`/`Warn :` 裸串项与 `_LOG_PREFIX_RE`
  重叠, 随收口删除; 正则 IGNORECASE 兼容大小写变体）。测试 2 例
  （5 行含噪声词正文全保 + 9 种真实 OpenOCD banner 行首形态全滤）。
- **F-107 处置（审计 P3 文档卫生，docs×3）**: ① README「多 MCU 评估——
  见 docs 档案」悬空指针（docs/ 已迁出仅剩 hooks-install.md）→ 改为直接
  陈述（暂缓+esptool/probe-rs 路线保留前置项清单）; ② OPENSOURCE_READY
  快照回填——F-3 行 ⏳→✅（经 F-026 落地 tempfile 化）、handoff 分支行
  补处置去向（F-070 + 09-09 tag 删除）、第五节加 F-107 实况注（118 受
  跟踪文件/0.5 材料/502 基线, 快照原貌保留不删）; ③ SENSITIVE_FINDINGS
  F-3 "尚未拍板"补处置结果段（与文件头 F-026 指向收口一致）。
- 测试 **502 → 515 collected**（净 +13 用例，F-108 按复审 M-1 订正口径——
  首记 "+7" 系 collected 502 与 passed 509 混减的机械错误; `git grep -c
  "def test_"` 两 revision 实测 504→517）, subtests 另计 207; 全量
  **509 passed, 6 skipped** 实跑绿; `coverage_lint --strict` 未覆盖清单
  保持 0。仍挂账（本轮未动）: 时钟树参数化 `--pclk`（架构增强非缺陷）、
  SCB CFSR/HFSR 粘滞位（需真机取证）、0.5 真机门禁（等板子）。

## Unreleased — 2026-09-11（F-110 gen_periph --hclk 时钟树参数化：P3 架构增强项落地）

- **F-110 处置（审计 P3「时钟树前提硬编码」，feature，Orchestrator 亲执行;
  spec: embedded-handoff `docs/superpowers/specs/2026-09-11-f110-hclk-param-design.md`）**:
  新增单一入口 `--hclk <MHz>`（默认 72, 合法域 [2,72], 越界经 `_emit`
  ERROR→exit 1——F-103 边界纪律）, 按 F103 **标准 APB 分频假设**
  （HPRE=1/PPRE2=1/PPRE1=2, CubeMX 复位默认）推导：APB2=hclk、
  APB1=hclk//2（floor）、TIM2~4 内核=APB1×2=hclk（RM0008 §7.3.7 双倍
  特性抵消）、SysTick=hclk。八常数点收敛到单一事实源 `apb_clock_mhz`：
  usart 三目 72/36、systick 72000000×3 处、pwm/timer-int 默认参
  （`tim_clk_mhz: 72→None`, 优先级契约: 显式 tim_clk > hclk 推导）、
  i2c `pclk1=36`、spi `SPI_CLOCK_BIT` 表内频率字面量退化为总线归属、
  adc ADCPRE 从固定 /6 改**自动选最小合规分频**（/2~/8 中首个 ≤14MHz,
  KB 明文上限; hclk=72 还原 /6 逐字节不变）。
  **兼容性核心性质（测试证明非口头）**: 缺省 72 时七个生成器输出与
  master `ef6ffa0` 逐字节一致（DefaultCompatTests 显式传 72 == 缺省 ×7
  + 既有四测试文件零修改全绿——首记"81 例"系手加漏数 syntax_smoke 3 例,
  实测 84, 由 F-111/M-2 订正; 教训升级见 F-111 段）; 非默认实样钉 hclk=8 手算值
  （USART1@115200→BRR 0x0045 / USART2→0x0023 / SysTick LOAD=7999 /
  I2C CR2=4 / ADC /2=4MHz / timer-int ARR=110）+ 奇数 hclk floor 注释
  如实（PCLK1=4MHz 不伪装 4.5）+ gpio 类型不受 hclk 校验波及。
  **登记不做**: RCC/SystemInit 生成器（审计原文伴生项, 独立议题）;
  链条检查点（读工程核对实际 hclk）——参数化消除"无法表达", 不消除
  "不声明就默认", 前提已在 CLI help 与本段双重声明。
  测试 +14 例（`test_gen_hclk_param.py`, 含 subtests 15）, 全量
  **533 passed, 6 skipped**; coverage_lint --strict 未覆盖清单保持 0。

## Unreleased — 2026-09-11（F-111 fresh-checker 复审 F-110：H-1 floor 粉饰修复 + M×4 + L 钉补齐）

- **复审结论**（对象 `cbb3c9f`, 分支 pclk-param-20260910）: **通过但有保留**
  ——Critical 0 / High 1 / Medium 4 / Low 4。**核心兼容声称获最强证实**:
  基线双模块 846 例同入参逐字节对比 0 差异（含全部数字插值文案与
  ERROR 路径）; 变异探针 4 组敏感度确认。
- **H-1 处置（ADCPRE floor 粉饰越限，fix+test）**: `pclk2 // div <= 14`
  改精确比较 `pclk2 <= 14 * div`——旧式把 hclk∈{29,57,58,59} 的 14.25~
  14.75MHz 越限选档并显示 "14MHz 合规"（B 类静默, 恰犯本仓自定义缺陷
  类型——**且是 Orchestrator 自审时点名的疑点, 复审坐实**）。显示层同步
  诚实化: 非整除档输出真值两位小数（29→"/4 7.25MHz"、57→"/6 9.50MHz"）。
  72/8/56/28 整除场景选档与显示逐字节不变（兼容契约延伸, `28→/2 恰 14`
  边界同钉）。新钉 `AdcExactBoundTests`。
- **M-1 处置（spec-实现域分歧，docs）**: spec「合法域 1≤hclk≤72」与实现
  [2,72] 分歧——实现取 2 有防御理由（hclk=1→pclk1=0 产出 0MHz 总线）,
  按"实现优于 spec"回改 spec（含理由注记）, 状态行同步"已实施"。
- **M-2 处置（记账数字不实，docs）**: 上一段"既有四测试文件零修改 81 例
  全绿"——实测四文件为 **84** 例（58+14+9+3, 首记漏数 syntax_smoke 3 例;
  F-108 刚自首过同类口径错误又复发, **教训升级: 计数必须跑 --co 实测,
  禁止手加**）。本段即订正。
- **M-3 处置（域校验只在 CLI 层，fix+test）**: F-103 惯例是生成器函数内
  返回 ERROR, hclk 校验却写在 main()——库直调 `gen_systick(1000, 0)`
  绕过守卫产出 `LOAD = -1` 伪合法代码。`_hclk_error()` 下沉全部 7 个
  涉时钟生成器（CLI 层保留, 两层互补）; `tim_clk<=0` 同族入域
  （旧病 tim_clk=0 → ARR=-1 一并收口）。钉 `LibraryDomainTests`。
- **M-4 处置（spec §6 三处声明只兑现 1/3，docs+test）**: 生成物侧——
  `_hclk_precondition_note()` 在非默认 hclk 时注入横幅前提注（HPRE/
  PPRE 假设 + 异常分频指引）, **hclk=72 不注入**保兼容契约; README
  gen_periph 行补 --hclk/--tim-clk 说明。钉 `PreconditionNoteTests`
  （7 生成器 ×有/无注记两态）。
- **L-1 处置（tick 文案失真，fix）**: timer-int 溢出 ERROR 恒写 "1MHz
  tick", tim_clk=8 下实际 111111Hz → 文案随 tim_clk 计算, 72 下逐字节
  不变。L-2/L-3 处置（CLI 缺省钉 + spec 承诺缺失钉补齐）:
  `CliDefaultAndMissingPinsTests`——CLI 不传 --hclk == 显式 72（堵
  "CLI default 单独改错全绿"盲区, 9 处默认 72 的漂移面钉住行为）、
  usart --hclk 8 subprocess 钉、pwm PSC=7@8MHz 钉。
- **登记不做（L-1 附带发现, 基线既有）**: timer-int 非整除 target_hz
  的名义频率注（如 8MHz 下 ARR=110 实际 1001Hz 注释仍写 1kHz）——
  72MHz 下同样存在（target 非 tim_clk 因子时）, 属 gen_timer_int 固定
  PSC 设计的固有近似, 与 hclk 参数化正交, 挂账。
- 测试 +9 例（F-111 组）, 全量 **542 passed, 6 skipped**;
  coverage_lint --strict 未覆盖清单保持 0; 既有四生成器测试文件
  继续零修改。
- **P3 挂账剩余**: 仅 fresh-checker 复审 L-2（行首噪声词正文）/ L-3
  （显式 ID 覆盖）/ L-4（manifest 回显 legacy expect）三登记项。

## Unreleased — 2026-09-11（F-112 expectations 负断言：prohibited_outcomes 进机器）

- **F-112 处置（互锁链加固 A2，feature+test+docs，Orchestrator 亲执行;
  spec: embedded-handoff `docs/superpowers/specs/2026-09-11-negative-assertion-schema-design.md`
  2026-09-11 批准）**: FSD 模板的灵魂字段 `prohibited_outcomes` 此前只活在
  文本层、靠人审兜底（"去掉 Must NOT happen 契约就只是描述"——模板 294 行
  的论断一直缺一环兑现）。本单补上：expectations 条目级新增
  `forbidden_texts` / `forbidden_patterns`（与 texts/patterns 正交），
  **求值优先律**：捕获全文任一命中 → 该条目无条件 FAIL，先于正向匹配、
  亦先于 XPASS/XFAIL（spec §2 五行走查全钉）——"靠重启恢复的重连"这类
  假阳性从此有机器出口。
  - `expectations.py`: 新纯函数 `check_forbidden_fields`（结构+自杀配置判据
    单一事实源，loader 与 lint 共用——F-029 惯例）+ `_forbidden_hit`
    （子串/正则双形态；**不**自动注入 MULTILINE/锚定——尊重调用方正则完全
    控制权，强制会重演 L-2 误杀面，F-106 教训）+ `evaluate_expectations`
    头部负断言短路；loader 违规抛 ExpectationError（与 E 系列同源不漂移）。
  - `expectations_lint.py`: 新规则 **E10**（forbidden 结构/非法正则）+
    **E11**（同串并存 texts 与 forbidden_texts 永远 FAIL 的复制错→ERROR；
    xfail 条目配负断言语义错位疑点→WARNING）。docstring/计数文案随动
    （E1~E9→E1~E11）。
  - `verify.py`: import 面再导出两新符号（wire 兼容手法）；判定/JSON 契约
    形状不变 → **release G1/G2 自动继承负断言拦截，零改动**；
    `contract_hashes` 哈希算文件字节，负断言版本锚定天然成立。
  - `templates/fsd-template-stm32.md` §4.1 补机器落地映射段：可机检项→
    forbidden 字段；不可机检项保留人审面并注明理由——与豁免登记同一诚实
    哲学，不存在第三条路（沉默）。
  - 测试 +16 例（F-112 组；`ForbiddenAssertionTests` 10 例 = 优先律 5 +
  兼容基线 1 + loader 4 + lint 侧 E10/E11 新 6 例中归本组另计——原记
  "11 例（4+1+4）"系手加错误, F-114/H-3 按 --co 实测订正:
  `test_verify_expectations` 24→34、`test_expectations_lint` 21→27,
  `grep -c "def test"` 与 `--co` 双口径吻合）, 全量
  **558 passed, 6 skipped** 为该分支时点值（终值见 F-114 段）;
  coverage_lint --strict 未覆盖清单保持 0。
  - 向后兼容契约：无新键旧清单零行为变化（逐字段基线钉）；三现役工程
    不强制回填。mpu6050-oled 示范（FR-MPU-02 配
    `forbidden_patterns: ["\\[DIAG\\] MPU6050_UpdateEuler FAIL"]`）随真机
    回归窗口收口（板子在场时执行，本地不假验）。
- 全量套件 **558 passed, 6 skipped, 248 subtests**（F-110/111 基线 542/6 +
  净增 16 例 + 口径注：本条为 pytest collected 计, unittest discover 口径
  在 CI 实跑同步复核; F-108 教训——计数先统一口径再落账）。

## Unreleased — 2026-09-11（F-113 fsd_coverage 对账器：FSD↔expectations 最后一道手工缝焊上机器）

- **F-113 处置（互锁链加固 A1，feature+test+docs，Orchestrator 亲执行;
  spec: embedded-handoff `docs/superpowers/specs/2026-09-11-fsd-coverage-reconciler-design.md`
  2026-09-11 批准）**: 考题从 FSD 抄进考卷（expectations.json）此前纯人肉,
  漏抄/多抄/同 ID 异义全部沉默。新工具 `scripts/fsd_coverage.py`（纯函数
  三件套 parse_fsd/load_waived/diff + 薄 IO, lint 同款退出码 0/1/2）三判:
  **C1** 孤儿断言（无 FSD 出处）ERROR / **C2** FR 需求欠账（无断言无豁免）
  ERROR / **C3** 豁免不完备（缺 reason/孤儿豁免）ERROR + 双侧 ID/标题对照表
  （语义漂移"必须过目"面——v1 如实声明不判语义等价）。expectations 顶层
  新增 `waived` 数组（豁免登记, loader 对未知顶层键宽容 → 旧清单零影响）;
  **xfail（欠条）与 waived（豁免）两级语义分界写进模板 §4.3 与 README 契约段**。
- **首跑红→整改→绿（对 mpu6050-oled 实扫, 三类问题全部现形）**:
  C1 `FR-BOOT-01` 孤儿断言 → FSD 补录需求（source: existing-implementation
  回填, 附模板 §2 规则 1 裁决注记）; C2 FR-OLED-03/FR-KEY-03/FR-PWR-01/02
  四条欠账 → 5 条 waived 登记（bench-manual/物理观察, 证据指向 releases
  v0.5）; **同 ID 异义 `FR-OLED-02`**（FSD=10Hz 刷新 vs expectations=关屏
  节流, v0.5 判绿实际按后者）→ FSD 侧 FR-DISP-02 新编号迁出原义 +
  FR-OLED-02 对齐现义并留 superseded 注记（新增编号不回收, ID 稳定纪律）。
  整改后: mpu6050-oled WARN（exit 0, NFR×4 提醒）; button-toggle/adc-oled
  SKIPPED（无 FSD, 存量如实）。
- **首跑实证的两处设计修正（登记于 spec 外, 以本段为准）**: ① NFR 无断言
  从 ERROR 降 WARNING——NFR 多为性能/构建约束天然不走 capture 断言, 一刀切
  判死即制造假红（mpu6050 NFR×4 即现场）; ② 输入不可得（无 FSD/无 manifest）
  从 ERROR 改 **SKIPPED**——legacy 工程"无对账面"是现状非事故, 谎红会让
  HANDOFF 换回秒检对存量工程不可用; 但如实进 warnings, 不假装通过（教训 #9
  的反向应用: 沉默兜底与谎红同罪, 诚实标注边界即可）。
- 豁免随发布档案锚定: 采用 contracts 文件哈希方案——waived 数组并入
  expectations.json, 其改动使 `expectations_sha256` 变化, 在**下一次
  release** 的 G1 契约哈希与新记录绑定现形（F-114/M-5 订正本段原叙:
  原写"release_audit R7 与 git_head blob 比对现形"错位——R7 锚定的是
  发布时点的记录 vs 当时 git_head, 既有 v0.5 记录对事后 waived 改动
  **永远不可见**; 机制无漏洞但现形点在下次发版, 措辞以本句为准）;
  **不**在 G3 记录加 waived 字段（门禁面不扩, spec §4"待定不做"落定）。
- 挂接: HANDOFF-AGENT.md §6 换回第 3 步扩为 lint+fsd_coverage 连招
  （私仓 paired commit）; README 速查表 + 工程契约段 + FSD 模板 §4.3。
- 测试 `tests/test_fsd_coverage.py` **19 例**（--co 实测, F-111 教训: 计数
  跑实测禁手加: 解析 5 + 三判 8 + 宽容 2 + 端到端 3 + SKIPPED 钉 1）;
  全量套件本段首记 **561 passed（collected 567）为 F-113 分支时点值**——
  F-112 系 merge 才入树, 该数字**不含** F-112 的 +16 例, 原文"含 F-112
  合入/堆叠合并后终值"失实, F-114/H-3 订正: merge 后实测 **577 passed,
  6 skipped（collected 583）**; coverage_lint --strict 静态可达 0 未覆盖保持。
- **真机面**: 零（纯离线判定层）; FR-MPU-02 负断言示范随下次板前窗口
  verify 回归收口（F-112 段同约）。

## Unreleased — 2026-09-12（F-116 fresh-checker 复审 F-115：H-1 误归因根治 + M×4 处置 + 两工程收编）

- **复审结论**（对象 `b508898..b19d160`, 无上下文审计员 impl 模式）:
  **通过但有保留** C0/H1/M4/L5（落账 fc_20260912_005711）。核心定性:
  B1 主判据（marker 触发/fault_type/status/exit）**成立**——但
  "层 2 `resolved.pc=main+670` 命中"是**误归因**: halt 现场 xPSR=0x01000003
  的 IPSR=3 铁证 CPU 停在 handler 自旋内, live PC 不可能在 main;
  static 函数不进 map → "最近前导全局符号"兜底把 handler 地址吞成 main+N
  （审计实跑 resolve_address 复现: 0x08001400→main+856）。真实故障点
  只活在层 1 `[HF] PC=/LR=` 行里, 而层 2 从不读它——**未来任何真故障的
  层 2 头条都会指向 handler 自己**。
- **H-1 处置（fix+test+真机半）**: ① 模板 handler 体改
  `wb_hardfault_body` **非 static**（保 used）→ 进 map 全局符号, live PC
  如实命名; nm 实证两工程均落 `T wb_hardfault_body`。② hardfault.py 新增
  `parse_hf_site` 纯函数 + `--fault-text`（文件/stdin）→ 解析层 1 现场行,
  经 resolve_address 出 `fault_site{pc,pc_sym,lr,lr_sym,live_pc_note}`
  （live PC 与故障现场**分开呈现**, IPSR≠0 时附注）; verify marker 路径
  自动把 captured_text 从 stdin 递进去（`"[HF] PC=" in text` 才传,
  empty_fallback 面行为零变化）。③ 人读输出增 "Fault Site (层 1 压栈帧)"
  段。测试: test_hardfault_fault_site.py 13 例（解析 6 + 模板契约 6 +
  编译探针 1）+ 装配钉升级 2 例。
- **M-1（模板中文注释违反 spec §3.1 "纯 ASCII"）**→ 全模板注释重写为
  ASCII 英文（grep -P 字节级 0 非 ASCII + -Os -Wall -Wextra 真编译复核）;
  工具链中立理由本就在 spec 手里, 无偏离可登。
- **M-2（模板烟测两档皆缺）**→ TemplateContractTests 静态契约钉
  （marker/非 static/VALID 门控/printf 禁区/不清粘滞位）+
  TemplateCompileProbeTests 真编译器探针（which 定位, 缺则 skip 如实;
  本机 arm-gcc 10.2021.10 实绿, CI syntax-smoke 双档齐）。
- **M-3（adc-oled 未回填未挂账）**→ 已回填并 commit `969a618`
  （clean 重建 0e0w, text 9268→10404 +1136B handler; 配对括号法删桩——
  首轮 Allman 风格锚点截错炸出编译红, 当场回滚重做, 未伤及既有账）。
  既有脏项（My_OLED 回写等）**分毫未碰**。mpu6050 模板同步 commit
  `68b6f3b`。正常运行真机回归随复验一并补。**新账**: adc-oled 无
  .gitattributes（autocrlf 警告复现 v0.5 行尾漂移坑的前置条件）——挂
  "新工程入库照此办理"清单。
- **M-4（"text 29644B 与 0.5 基线一致"两头不对）**→ 订正: 29644 =
  0.5 基线 28580B + handler 增量 ~1064B（接线纯增量, "一致"是错的
  自洽声明）。F-115 段④已改写。
- **L 处置**: L-1 装配钉升级 `count('"trigger": hf_trigger')==3`（error
  分支漏装配不再假绿; 仍是源码级, 行为面由真机背书——如实）+ 新增
  `--fault-text` 装配钉; L-4 BFAR/MMFAR 按 BFARVALID(b15)/MMARVALID(b7)
  门控输出 `(valid)/(INVALID)`（E000ED38 伪装地址现象根除此）; L-5 模板
  头声明 STKERR 垃圾帧与 lockup 极限。**挂账**: L-2（RTT 半行截断使
  marker 失效的窗口——旧判据同险非新引入, 缓冲 512B 实测 9 行未触顶,
  登记 spec R1 伴生项）、L-3（8/8 补验 primary 落盘件在会话 tool-results,
  仓内以 checkpoint+feedback 事件为账, 成功路径不留原始文本是设计使然）。
- **真机复验（2026-09-12 板前完成, ST-Link 重连后）**——H-1 修复获端到端铁证:
  ① 注入复验: `fault_site = {pc: 0x0800100A → **main+198**, lr →
  My_OLED_Update+33, live_pc_note}`——真实故障点第一次被**正确**归因到
  main 内注入行（对照 F-115 时段的假命中"main+670"）; live PC 如实报
  `wb_hardfault_body+368`（非 static 后 handler 地址自带真名）。
  ② mpu6050 反向: 回退注入烧正式固件后 hardfault step 缺席、5/8
  （KEY×2+OLED-02 属人工动作期望）。③ adc-oled 回填后正常运行回归:
  hardfault 零误挂 + 3/4（FR-ALERT-01 需窗口内拧电位器过 3.0V, 人工轮
  未及配合, 与 KEY 同类交用户自持窗补验, `! ...verify.py --no-build
  --no-flash --json --timeout 40` 随时可跑）。板子已恢复 mpu6050 正式
  固件（Verified OK）。**真人期望窗自持纪律第三次印证**（09-10 门禁/
  昨日 8/8/本轮 ALERT）——工具侧不再代发"现在开始按"。
- 测试 +16 例（13+2 装配钉 +1 skip 编译探针口径注）, 全量
  **609 passed, 6 skipped, 248 subtests（collected 615, --co 实测）**;
  coverage_lint --strict 0 未覆盖保持。

## Unreleased — 2026-09-11（F-115 RTT 工程 HardFault 闭环补齐：C 级 RTT 现场 + verify 触发归因）

- **F-115 处置（互锁链真机断点 B1，feature+test+docs+真机，Orchestrator 亲执行;
  spec: embedded-handoff `docs/superpowers/specs/2026-09-11-rtt-hardfault-coverage-design.md`
  2026-09-11 批准）**: 层 1 C 级 handler 建于 semihosting（无 host 即 BKPT
  halt），RTT 成默认后端后两现役工程退化为"烧过但空捕获→层 2 兜底猜"——
  招牌诊断在默认路径下缺一半。补:
  - `templates/hardfault_rtt.c`（新）: naked 入口 EXC_RETURN bit2 甄别
    MSP/PSP（blink 成熟手法移植非重写）→ `SEGGER_RTT_WriteString` 输出
    `=== HARDFAULT ===` + `[HF] CFSR/BFAR/PC/LR + 位域解码` 纯整数格式
    （nano 浮点教训）；只读不清粘滞位（F-109 分工：保位留证据，清位归工具）;
    `for(;;) nop` 自旋保现场（不复位，OpenOCD 层 2 halt 取同一现场）。
    `_hardfault_body` 加 `__attribute__((used))`（仅被 naked asm 引用，
    -O2 会优化丢符号——自查修正）；位域一律 CFSR 绝对位号（MFSR0-7/
    BFSR8-15/UFSR16-31，自查修正: 早期按字节拆传把 UNALIGNED 位号错位）。
  - `scripts/verify.py`: 新纯函数 `_hardfault_trigger(text, capture_empty,
    flash_ran)` → "marker"|"empty_fallback"|None，三处 steps.hardfault
    dict 落 `trigger` 字段（诊断触发链后端无关，判据零改动；主/兜底路径
    从此可事后审计，教训 #9 落点）。map 发现 F-005 已 build/优先，零改。
  - 测试 `tests/test_verify_hardfault_trigger.py` 7 例（标记优先律/兜底/
    不触发/大小写敏感防误触/病态同帧归因 + 装配点行为钉）。
- **真机验收（板子在场，mpu6050-oled，全 GCC）**——B1 核心判据达成:
  ① 故障注入（main 循环 `*(volatile int*)0=1` → 真 BusFault, F-109"伪造
  被硬件拒须造真故障"照办）: RTT 现场捕获
  `=== HARDFAULT ===` + `[HF] CFSR=00010400 HFSR=40000000` + PC/LR 行;
  verify `trigger=marker` → fault_type `BusFault (IMPRECISERR)`、层 2
  `PC resolved=main+670`、整体 status=hardfault、退出码 1（主路径坐实，
  不再空捕获兜底）。② 反向: 恢复正式固件后 460~693 行正常 RTT 输出
  **零 HARDFAULT 字样 + hardfault step 不出现**（handler 不误挂）。
  ③ F-112 联动: FR-MPU-02 forbidden_patterns 真机每轮 PASS 无误杀。
  ④ clean rebuild→flash(Verified OK)→capture→verify 全链绿（text 29644B =
  0.5 基线 28580B + handler 增量 ~1064B；本句原写"与 0.5 基线一致"失实，
  F-116/M-4 订正——接线是纯增量，"一致"从两个读法都不对）。
  **教训**: openocd program 路径在
  Git Bash 下须正斜杠 `D:/...`（`/d/...` 与带反斜杠 `D:\...` 均被 tcl 吞
  分隔符 → couldn't open，首两次烧录白跑——与仓内既有"bash 命中 WSL stub"
  同族: 子进程参数经几层 shell 解析要逐层核）。
- **真机面三条按键期望补验闭合（用户自持采集窗，`verify --no-build
  --no-flash --timeout 90`）**: **8/8 pass、零 xfail、零 hardfault step**
  （capture rtt 715 行/90s，FR-KEY-01/02 与 FR-OLED-02 于真实
  短按/长按/关屏/唤醒序列下全绿；F-112 负断言 FR-MPU-02 同轮 PASS）——
  B1+F-112+F-113 三单真机收口证据齐。此前多轮 FAIL 根因=回合制指令与
  用户按键窗口对不齐（非固件/工具缺陷，三轮对照数据已证：无按键时
  [DIAG] PA0=0 恒定），用户自跑一次即过——**流程教训：真人输入期望的
  验收窗必须交给用户自持，AI 不得代发"现在开始按"的回合制协调**。
  （F-115 段初稿"FR-OLED-02 已 waived"为误记，自查更正：waived 五条为
  DISP-02/OLED-03/KEY-03/PWR-01/02，KEY-01/02/OLED-02 均为在场断言——
  H-3 计数/记账教训的当日复发当日截获。）
- 全量套件 **595 passed, 6 skipped, 248 subtests**（含 F-115 +7; collected
  口径 CI 复跑同步核; F-112 三犯教训: merge 前后分栏不混记）; coverage_lint
  --strict 静态可达 0 未覆盖保持。F-035: B1 待 fresh-checker 复审后合 master。

## Unreleased — 2026-09-11（F-114 fresh-checker 复审 F-112/F-113：H×3 全修 + M×2 修 + 挂账登记）

- **复审结论**（对象 fsd-coverage-20260911 分支 `7ef99b0..d3e6720`, 无上下文
  审计员 impl 模式）: **通过但有保留**——C0 / H3 / M7 / L6, "需收口后方可
  视为完成"。落账 fc_20260911_155323+0800（adc-oled, target 写明真实审核对象）。
- **H-1 处置（fsd_coverage 损坏输入裸 traceback，fix+test）**: 三探针实证
  （非法 JSON / 条目缺 id / 顶层数组 → JSONDecodeError/KeyError/AttributeError
  裸崩, 违背自宣"退出码对齐 lint 0/1/2"契约）。修复: `reconcile` 顶层非 dict
  报 C0; `normalize_expectations` 损坏条目报 C0 不 KeyError; `_read_project`
  捕获 JSONDecodeError → fatal → verdict=error。**语义分界**: 输入**缺失**
  =SKIPPED（存量现状）, 输入**损坏**=ERROR（坏文件必须响）——沉默兜底与
  谎红同罪的第三面: 裸崩同罪。钉 4 例。
- **H-2 处置（对照表双侧 desc 未实现，fix+test）**: spec §2"v1 对漂移的全部
  承诺"初版只落 FSD 侧标题、孤儿断言不进表。修复: rows 并入 `exp_desc`
  （缺侧 `—`）+ `forbidden` 列（顺带兑现 F-112 spec §9.5）+ 孤儿断言独立成行
  （`orphan=True, fsd_title=—`）——最需过目的对象此前恰好缺席; 人读输出双列
  并排 `FSD: 标题 ⇐ 断言: desc ⛔负`。docstring/模板改真。钉 3 例
  （双侧并排/孤儿成行/负断言列）。
- **H-3 处置（CHANGELOG 计数失实，docs）**: ① F-113 段"561（collected 567,
  含 F-112 合入, 终值）"——561 为 F-112 merge 前分支时点值, merge 后未复跑
  全量却标终值（**验证纪律反例入账: 证据先于声称, merge 后必重跑**）;
  实测订正 577/583。② F-112 段"ForbiddenAssertionTests 11 例（4+1+4）"
  明细与总数互斥——实测 `-k Forbidden` 10 例, 订正并改明细。F-108 同类
  三犯, 教训升级落记忆: **分支时点数与 merge 后终值必须分栏记, 手加即错**。
- **M-2 处置（waived 校验三薄弱，fix+test）**: C3 补 `evidence` 必填
  （spec 原文条款兑现, mpu 五 waiver 本就齐填——掩盖了规则缺失）;
  新 `validate_waived`: 非法项/重复 id 报 C3 不静默吞（"豁免登记写坏"本身
  必须响）; `load_waived` 保留为宽容映射函数并注明分工。
- **M-3 处置（E11 自杀配置盲区，fix+test）**: spec F-112 §3.3 原文
  "texts/**patterns** 完全相同"初版只做 texts 侧——patterns×forbidden_patterns
  同串零成本字面比对却放行。补齐双侧, 钉 1 例。
- **M-1 顺手落地（spec §2 条款非登记项）**: `.workbench/config.json`
  `fsd_path` 字段覆盖默认 `docs/FSD.md`（现役三工程无该字段全走默认,
  零行为变化）。M-4/M-6 登记为**实现立场**入 fsd_coverage docstring
  （Must/Should 分级 → FR/NFR 前缀替代; C1 孤儿豁免不可 waive——孤儿豁免
  本身即 C3, spec 字面勘误, 以 docstring+本段为准）。
- **L 组**: L-1 check_forbidden_fields 返回 (code,msg) 元组, lint 不再文案
  子串嗅探路由（文案一改即静默错码的雷拆了）+ 码路由钉 1 例; L-3 HANDOFF
  §6"两工程 CLEAN"改"不得为 ERROR（SKIPPED 属预期）"（私仓 paired）;
  L-4 parse_fsd docstring"如实报重复"与实现不符 → 措辞订正（判权归规格
  审读, 对账以去重集为准）。**挂账**: L-2 余项（tests/fixtures 补 forbidden
  样例 / MULTILINE 锚定示范钉 / 内联基线与 spec"逐字节"措辞差）、L-6
  （lint 无清单 exit 1 vs coverage SKIPPED exit 0 的不对称——连招双腿语义
  本就不同, 倾向不改, 复审议）。
- **新取证（审计附带, 非本单造成）**: `release_audit --project
  stm32f103-mpu6050-oled --tag v0.5` 实测 **R7 FAILED**——config.json 记录
  哈希=发布时工作树 CRLF, git_head blob=LF（422e45f"autocrlf=false+eol=lf"
  提交使发布字节与入库字节永久错位的**历史遗留**）。挂账处置: 重算 v0.5
  记录哈希（重锚注记 provenance）或接受 R7 该记录永久 WARN 并登记;
  处置前 HANDOFF §6-2.5 对该工程预期 FAILED 勿当新伤。
- 测试 +16 例（fsd_coverage 19→28 口径注: 本段实测 `--co` 数为准, 分类明细
  见文件内注释; lint +2; 其中 test_fsd_coverage 终值 28 例）, 全量
  **588 passed, 6 skipped, 248 subtests（collected 594, --co 实测）**;
  coverage_lint --strict 0 未覆盖保持; mpu6050-oled 对账 WARN（exit 0）
  复跑不变。
- **M-7 收口（paired, 工程仓）**: stm32f103-mpu6050-oled FSD/expectations
  整改 + toolkit F-112~114 内容以工程仓 commit 入档（HEAD 21afb15 之上,
  本地不 push——该仓无远端）; v0.5 发布记录不重开（其 R7 历史错位另账）。

## Unreleased — 2026-09-10（F-109 SCB 粘滞位真机取证结案 + hardfault 读后清除）

- **取证（0.5 门禁收官后趁板子在连, 真机 xPack OpenOCD 0.12 + F103C8T6）**:
  审计 P3 推测项"SCB CFSR/HFSR 粘滞位未清（推测项，需真机验证）"结案——
  T-A 复位后全 1 写清除读回 0（目标本就干净, 不构成置位证据）;
  T-B mww 直接注入 UFSR 位被硬件拒绝（故障位只能真故障置位——探针设计
  教训: 伪造残值不可行, 须制造真故障）;
  T-C1 制造真故障（reg pc 0x0800ff00 跳已擦除 flash → 升级 HardFault,
  handler while(1) halt 现场）读得 CFSR=0x00010000 / HFSR=0x40000000,
  多次 halt 重复读到同值 → **粘滞坐实**;
  T-C2 按位写 1 清除读回 0 → **W1C 有效**。
  **误诊路径实证**: 现场 halt 下连续两次跑旧版 hardfault.py, 第二次把
  上一轮已报告的同一故障位再次归因（UsageFault UNDEFINSTR）——跨运行
  陈旧位误诊从推测升级为实录。
- **处置（fix+test, hardfault.py）**: 诊断序列改"读→报告→W1C 清→复核":
  `run_openocd_diag` 首读后追加 `mww <addr> 0xFFFFFFFF` + 二次 `mdw`
  （清除全 1 安全——粘滞位写 1 才清、写 0 无副作用, 且 T-C2 后按位/全 1
  等效实测）; BFAR/MMFAR 不清（普通 R/W, CFSR VALID 位清后其值即声明
  失效）。解析层新增 `parse_mdw_all_values`（同址多读按序取, 首值诊断、
  末值 residual, 单次读不虚构）+ `sticky_hygiene`（cleared True/False/
  None 三态如实报告）; JSON 增 `sticky_hygiene` 字段, 可读输出增粘滞位
  复核行。**设计修正（相对任务单原文）**: 不在固件 handler 侧写清位——
  handler 保位即保留崩溃现场证据, 清位职责归诊断工具。
- **闭环验证（真机）**: halt 现场跑新工具 → 诊断 UNDEFINSTR +
  `sticky_hygiene.cleared=true (0x00010000→0x0)`; 同场再跑 → **no_fault**
  （旧版此处会误报）; 完毕 reset run 交还板子正常运行。
- 测试 +8 例 `tests/test_hardfault_sticky_clear.py`（命令序列顺序钉:
  读<清<复读 ×2 + BFAR/MMFAR 反向钉不列入清除; residual 解析三态;
  hygiene 报告三态）, 先红（7 failed）后绿。全量 **519 passed, 6 skipped**;
  coverage_lint --strict 未覆盖清单保持 0。
- **P3 挂账剩余**: `--pclk` 参数化（架构增强）、复审 L-2/3/4 登记项。

## Unreleased — 2026-09-10（F-108 fresh-checker 复审处置：M×3 + L-1 修复，L-2/3/4 挂账）

- **复审结论**: F-103~107 分支 `p3-clearance-20260910`（`902d563`）经
  无上下文对抗复审 **通过但有保留**——Critical 0 / High 0 / Medium 3 /
  Low 4; 五条声称的实现与边界全部实测成立, 变异探针 5/5 对应用例变红。
- **M-1 处置（计数失实, docs）**: 见上一段订正（502→515 collected /
  净 +13; 首记 +7 为口径混减机械错误）。
- **M-2 处置（"全部 ERROR 出口收敛"言过其实, fix+test）**: gen_i2c 2 个 +
  gen_spi 1 个**既有** ERROR 出口（F-103 前已存在）仍 `print` 直出 rc=0。
  i2c/spi 分发点接入 `_emit`, 现字面成立——gen_periph 全部 11 个 ERROR
  分支收敛 exit 1。新钉 `test_i2c_spi_error_exits_converged_to_emit_f108`
  3 subtests（I2C9 外设名 / speed=1MHz 非法 / SPI9）。
- **M-3 处置（README cfg 计数陈旧, docs）**: "verify 7 / release 2 /
  hardfault 2" 是 F-034 时代快照, release 已随 F-041 下沉
  `openocd_runtime`; 按实测更新为 6 脚本各一对
  `interface/stlink.cfg`+`target/stm32f1x.cfg`（grep 全量取证）。
- **L-1 处置（零值报错不对称, fix+test）**: systick `--freq 0`、usart
  `--baud 0`、timer-int `--period-ms 0` 曾裸 ZeroDivisionError traceback
  （rc 同为 1 但非可诊断输出, 与 F-103 泛化精神不符）→ 补 `<=0` 前置
  校验与 gen_pwm 对齐。钉 `test_zero_input_structured_error_f108` 4 例。
- **F-108 全量**: **511 passed, 6 skipped, 214 subtests**（Git Bash 实跑绿;
  注: 同套 hooks 行为测试在 PowerShell 下 9 红——`git diff` 输出行尾随
  core.autocrlf 漂移命中既有"Windows 测试基建"教训面, 以 Git Bash/CI 为
  权威口径, 登记不另修）。`coverage_lint --strict` 未覆盖清单保持 0。
- **挂账登记（复审确认非本轮缺陷）**:
  L-2 = 行首恰为噪声词的固件正文仍被 F-106 正则整行删（行首锚定的内在
  取舍, 半主机正文以 OpenOCD banner 词开头概率低; 时间戳前缀噪声行为
  推测项, 无实机日志佐证）;
  L-3 = 显式 ID 冲突仍覆盖（测试钉死的调用方契约）+ 自动 ID
  check-then-write TOCTOU 窗口（单机单会话场景风险低）;
  L-4 = manifest 模式 result JSON 仍回显 legacy `expect` 数组（基线
  同然, 非本轮引入, 消费方误读风险留待 0.5 契约整理时一并处置）。

## Unreleased — 2026-09-09（F-095 build_has_errors 死分支激活：失败语义区分）

- **F-095 处置（F-088 登记项 / 维护者拍板选项 A，fix，Orchestrator 亲执行）**:
  F-088 实测 `build_has_errors`（verify.py 主流程）为死分支——analyze 返回
  error 时不 break 出 build 重试循环 → 循环耗尽后恒走 build_failed 早退，
  两后端（gcc/keil）均不可达 583 行。维护者拍板: **analyze error 直接
  break**（编译器跑通但产物有错时重试同源码大概率仍 error, 纯耗预算）+
  循环后按 `analyze.status` 分流: error → `build_has_errors`
  （`Build has N error(s)`），否则 `build_failed`（`Build failed after N
  attempt(s)`）——两种失败语义（"跑通但有错" vs "没跑成"）对 AI 消费方
  可区分。验证类早退同样落台账（F-047 纪律延续）。S4 钉由"现实行为
  build_failed"翻转为"build_has_errors"，先红后绿（修复前新断言红）。
  全量 476 绿（478−2: S4 与 test_verify_main_success_path 的两例因语义
  分流整合为单例断言）。

## Unreleased — 2026-09-09（F-100~F-102 批次 6 收官：禁令机检 / CI 烟测 / 零覆盖清零）

- **F-100 处置（审计 P1-10 / WB-C6，test+ci）**: CONTRIBUTING 三条"可机检
  禁令"落为 `tests/test_layering_gates.py`（3 例, AST 静态扫描）——① 低层
  (Layer 0/0.5/1) 禁 import Layer 2；② 生产脚本禁 import verify；③ legacy/
  禁新增 runtime_common。红探验证: 向 wb_common 注入违规 import → 机检红 →
  还原绿。**登记**: openocd_gdb_common 实为"gdb 族共享件"（只被 openocd_gdb
  消费, 自身 import openocd_runtime）——CONTRIBUTING 分层图"三 runtime"
  未列它属图示遗漏, 机检按 Layer 1 归类并注释登记, Layer 1 族内互引放行。
  `coverage_lint --strict` 接入 CI（coverage-lint job）。
- **F-101 处置（审计 P2-11 / WB-C6，ci）**: ci.yml 新增 syntax-smoke job
  （ubuntu 装 gcc-arm-none-eabi）——语法烟测此前只在 Windows 本地跑,
  ubuntu 恒 skip, 生成器语法回归在 CI 上零防线; 现在 CI 三 job 变四 job。
- **F-102 处置（审计 P1-8 / WB-C7，test）**: 零覆盖收官——serial_hex
  （hex_dump/emit_chunk）、serial_monitor（include/exclude 过滤）、
  serial_scan（芯片映射+体面失败）、serial_log（text/csv/json 三格式
  落盘+引号转义+非法 UTF-8 hex 兜底+duration 停止）、serial_send
  （payload hex/文本×行尾）、cube_to_keil（USER CODE 块提取+_dedent）
  共 24 例纯 host 逻辑测试。**coverage_lint 未覆盖清单 6 → 0**,
  `--strict` 门禁转绿; 反向钉（P2-12）按"覆盖提升即移钉"纪律全部移除。
  施工实录: serial_hex.output_json 写 sys.stdout.buffer（text 层
  redirect_stdout 拦不住）——测试须替换整个 stdout 对象; serial_log.main()
  成功路径无显式 return（返回 None 非 0, mock 断言别假设退出码 0）。
  全量 **502 绿**（479+24−1 合并 S4）。

## Unreleased — 2026-09-09（F-096 hooks 漏报修复：判据加 --cached 优先【拍板 A】+ 工程卫生收尾）

- **F-096 处置（F-093 登记项 / 维护者拍板选项 A，fix，Orchestrator 亲执行）**:
  三条 C 铁律 hook（block-malloc / block-hal-delay-in-logic /
  warn-volatile-missing）的 `git diff -U0 -- <files>` 比对工作树 vs index,
  真实 pre-commit 时刻（staged 且工作树一致）恒空 → **三条 hook 全部恒
  exit 0 形同虚设**（F-093 金丝雀实测）。拍板 A = 判据改
  `{ git diff --cached -U0 -- $files; git diff -U0 -- $files; }` 双路合并
  （--cached 命中即拦, 未命中再查工作树——工作树路径的有效性此前已由
  探针钉住, 保留）。金丝雀组按承诺翻转为修复钉
  `StagedContentDetectionTests`（staged malloc/HAL_Delay → exit 2,
  staged 缺 volatile → 提醒; 先红后绿）。
- **工程卫生收尾（拍板 A）**: 远端 4 个 `handoff-*` 过程 tag 删除
  （handoff-start/round1/r2-close/pre-handoff, 指向 commit 全部 master
  可达、零独有内容, 本地同步删）; 远端 tag 终态 = v0.2/v0.3/v0.4。
- 全量 478 绿。

## Unreleased — 2026-09-09（F-097~F-099 批次 5：serial_mux 泄漏 / KB 补全 / 元数据三连修）

- **F-097 处置（审计 P1-3 / WB-A，fix+test，Orchestrator 亲执行）**:
  serial_mux 两处生命周期缺陷——① start_mux 的 wait_for_tcp_server 失败
  分支直接 return, 已启动的 serve 进程(p1)成孤儿独占真实串口 → 失败/异常
  分支统一回收 _mux_procs(terminate+wait+kill 兜底); ② _serial_read_loop
  异常静默 stop_event → 死因零留痕 → stderr 留痕 +
  `%TEMP%/serial_mux/serve_<port>.failed` 失败现场 + `os._exit(1)`（父进程
  早已返回, 非零退出码是唯一可见信号）。回归钉
  `tests/test_serial_mux_lifecycle.py`（3 例: 泄漏回收/死亡现场/正常关闭
  不误报）。**P2-12 反向钉按"覆盖提升即移钉"纪律移除 serial_mux 条目**
  （test_coverage_lint_reachability 原 assertIn 移除, cube_to_keil 仍保留）。
  - 变异: 撤 terminate 分支 → 泄漏测试红 → 还原绿。

- **F-098 处置（审计 P1-7 / WB-B，data，Orchestrator 亲执行）**:
  KB 实例级残缺补全——用 svd_to_json 从 Keil DFP 2.2.0 SVD 提取 4 个残缺
  实例的**全量寄存器表**合并（手工语义字段 desc/available_on_c8 保留）:
  TIM2 8→20 / USART1 4→7 / ADC1 5→20 / RCC 5→10（新增 36 寄存器）。
  NVIC.irqs 7→11（补 TIM1 四中断 24~27: BRK_TIM9/UP_TIM10/TRG_COM_TIM11/CC,
  命名按 RM0008 + CMSIS）。_relationships 补 **TIM1** 条目（APB2/base/
  clock rcc_bit=11——F-077 是代码补丁, 本条补数据根因; CH1~CH4=PA8~PA11;
  irq 契约形态 number=25/name=TIM1_UP_TIM10_IRQn, 完整表在
  TIM1.interrupts）。dma 字段**宁缺毋假**不写（RM0008 表未逐项核对）。
  - svd_to_json「FULL 一字不动」机制未改——本次是数据内容补全, 非管道
    变更; 残缺实例的"手工语义"仅 desc, 无丢失风险。

- **F-099 处置（审计 P2-4/P2-5/P1-11 / WB-C，fix+test，Orchestrator 亲执行）**:
  三个元数据缺陷打包——
  ① gcc_build timing_ms 秒当毫秒（P2-4）: 调用改 `(t-t0)*1000`
  （openocd_gdb 同款口径）; 性质钉（250ms 操作 elapsed_ms≥200）+ 静态钉
  （make_timing 调用必须带 *1000）。
  ② 三脚本 stdout 强制 UTF-8（P2-5）: coverage_lint/duration_profile/
  feedback_db 的 main() 加 F-025 先例的 `reconfigure(encoding="utf-8")`
  ——GBK 控制台下 ensure_ascii=False 中文不再崩/乱码（负向实测通过）。
  ③ coverage-data 测试组 GBK 必红修复（P1-11）: 四处 subprocess +
  _generate_coverage_data 的 env 补 `PYTHONIOENCODING=utf-8`
  （test_feedback_db.py:17-19 先例）。全量 479 绿。

## Unreleased — 2026-09-09（F-093 hooks 行为探针 + 安装文档 + F-096 漏报缺陷登记）

- **F-093 处置（审计 P2-9 / 批次 3 WB-C3，test+docs，Orchestrator 亲执行）**:
  hooks/ 三条 C 铁律此前仅过 `bash -n`，判据行为无任何测试。处置:
  1. **行为探针** `tests/test_hooks_behavior.py`（7 例，真实 git 仓 fixture +
     直接执行脚本）: 工作树路径（dirty worktree）下 malloc/HAL_Delay 阻断、
     volatile 提醒、非 .c/.h 放行均验证有效；**金丝雀组**（Canary）钉住
     staged 场景的现实行为（见下）。
  2. **⚠️ 新缺陷登记 F-096（hooks/ 是禁区，只登记不修复）**: 三条 hook 共用
     的 `git diff -U0 -- <files>` 比对的是**工作树 vs index**——真实 pre-commit
     时刻（staged 且工作树一致）该 diff 为空 → **三条 hook 全部恒 exit 0，
     形同虚设**（金丝雀实测）。修复选项: A. 判据加 `--cached`（最小）；
     B. pre-commit framework（重）。交维护者拍板。
  3. **安装文档** `docs/hooks-install.md`: 方式 A（单文件）+ 方式 B
     （core.hooksPath + 分发器，三条共存）+ F-096 限制声明。
  - **施工实录（三条 Windows 坑，测试基建类）**: ① subprocess 的裸 `"bash"`
    被 CreateProcess 命中 `System32\bash.exe`（WSL stub）→ 输出 UTF-16 错误
    且 exit 1——`shutil.which` 沿 PATH 找到的是 Git bash，但 CreateProcess 的
    安全搜索顺序不同，**外部脚本调用一律用绝对路径**；② 测试仓未关
    `core.autocrlf` 时全局 true 的行尾漂移会让 hook 内 grep 失灵——fixture
    仓必须显式 `autocrlf=false`；③ env 覆盖 `HOME` 会让 Git bash 初始化
    异常——隔离 git 配置用 `GIT_CONFIG_GLOBAL` 而非 HOME。
  - 全量 478 绿（471+7）。

## Unreleased — 2026-09-09（F-092 CHANGELOG 账本结构整理：单堆 + 去重指针）

- **F-092 处置（审计 P2-7 / 批次 3 WB-C2，docs，Orchestrator 亲执行）**:
  审计实测的三类账本结构债处置:
  1. **双堆收敛**: 尾部孤段（0.1.x 历史段之后的 F-078~084 共 7 段 / 110 行）
     整体搬入顶部 Unreleased 堆末尾（F-070 段之前）——**此后全文件无任何
     Unreleased 段位于已发布段（0.1.x/0.2/0.3/0.4）之后**（结构验证进本段）。
  2. **重复记账去重 ×2（留指针不删账）**: F-054 在「0.4 复核收口」段与
     「防腐方案 §3.3」段双记（内容同源、前者更完整: 306 全绿/收口链/AGENTS
     同步），后者改指针**以彼段为准**；F-062「登记+处置」与「处置」双记
     同法。指针行均标 F-092 可追溯。**未采信方案（记账）**: 直接删除重复段
     ——违反 append-only 账本纪律，断链风险大于整洁收益。
  3. **段标题失实**: 审计指「0.4 复核收口」段标题写 F-051~053 正文记到
     F-062——核实该段正文实际含 F-051/052/053/054/055~062 处置链，标题
     **不改**（append-only；本行登记事实，读者以正文为准）。
  - 结构终态: Unreleased 36 段全部位于 4 个已发布段（0.1.x/0.2/0.3/0.4）
    之前，顶部按时间新段在上；全文件 47 段。
  - 全量 471 绿（账本搬运不触碰代码/测试）。

## Unreleased — 2026-09-09（F-091 openocd 家族同源符号收敛：先钉后拆）

- **F-091 处置（审计 P2-1 / 批次 3 WB-C1，refactor，Orchestrator 亲执行）**:
  审计实测的家族内同源重复——`resolve_openocd_params` 在 openocd_gdb /
  openocd_run / openocd_telnet **三份逐字节相同**（sha1 9bd9af729c ×3）+
  openocd_itm 一份 +27 行扩展变体；`start_openocd_server` 在 gdb/itm 两份
  逐字节相同（bbe8f0aad8）+ telnet 差一行 docstring。**全部无 F-029 要求的
  「独立契约：…」留份 docstring、无账目裁决、无测试钉**——F-029 整车收口
  时只处理了 wb/serial 两族，openocd 家族是漏网（检查面再次只到"处理过的"）。
  处置 = 按先钉后拆三步:
  1. **先钉**: `tests/test_openocd_dedup.py`（7 例）——身份钉（三消费方
     符号 `is` runtime 同一对象，再导出非拷贝）+ 行为钉（CLI > project_config
     > state 三级优先 ×4 边界）；
  2. **后拆**: canonical 实现落 `openocd_runtime`（Layer 1 正确落点），
     gdb/run/telnet 三份副本删除，消费方 `from openocd_runtime import`
     再导出保持 `openocd_gdb.resolve_openocd_params` 调用面不变；净删 ~223 行；
  3. **留份裁决**: itm 的 tpiu/traceclk/pin_freq 扩展**不强行统一**——
     扩展字段是 ITM 特有需求，强并会迫使 Layer 1 runtime 携带 ITM 专属
     知识（分层违例）；变体特征钉 `test_itm_variant_not_unified` 固化
     "扩展键存在 + 主五参同源"。telnet 版 start_openocd_server 多的
     docstring 并入 canonical 版。
  - 全量 471 绿（464+7）。

## Unreleased — 2026-09-09（F-090 静默失败面修复：telnet 三 action 失败检查 + 烧录判据收紧）

- **F-090 处置（审计 WB-B2 / 简报 WB-20260909-04，fix+test，Orchestrator 亲执行）**:
  两处"失败被当成功"路径（审计 P1-1/P1-2）——
  **A. openocd_telnet 三 action 无失败语义检查**（write-mem/bp/rbp 查了，
  halt/reg/read-mem 漏查——同族不一致即遗漏非设计）:
  - halt: `halt` 响应 + reg 链路全部接入 `has_command_error`；**`halted:True`
    硬编码消除**——由 reg 响应推导（报错/pc 读不到 = 未确认暂停，summary 如实
    说"halt 已发送但未确认暂停"）；reg 链路本身失败 → status=error。
  - reg: 逐寄存器检查，空响应/报错/无法解析均计入 reg_errors；**全空 → error**
    （旧版"读取到 0 个寄存器"仍 ok）；部分失败 → ok 但 summary/details 如实
    带 errors（不谎报全量）。
  - read-mem: 接入 has_command_error + 空数据返回检查（非法地址 → error，
    不产出"读取成功+空 memory"假结果）。
  **B. 烧录成功判据 fail-open 移除**: verify.run_cmd 的
  `or 'verified' in stdout` 与 openocd_run 的 `action=="flash" and parsed.verified`
  （rc!=0 时）两处豁免删除——判据只信 returncode。理由: OpenOCD 日志实际走
  stderr（stdout 恒空），该豁免几乎只在异常时被 "not verified" 类文本误中；
  probe/targets 的 rc!=0 豁免保留（部分版本 probe 成功时 rc 仍非零，有
  jtag_tap/core 实证支撑，非纯文本子串匹配）。
  - 回归钉 `tests/test_openocd_telnet_failfast.py`（10 例: 三 action 负向 +
    正向不回归 + run_cmd 判据），假 Telnet 连接/假 proc，不碰真机。
  - 施工实录: 测试 fixture 的寄存器响应格式须与 parse_reg_single 真实格式
    一致（"r0 (/32): 0x0"，冒号形态解析不出）——**mock fixture 从实现的真实
    解析函数反向构造**，不凭想象；空响应在 has_command_error 之外（它只认
    错误关键词），"连接断=静默"也须视为读取失败。
  - 全量 464 绿（452+12: F-090 10 例 + F-089 扫描钉 2 例已在上一 commit 计入）。

## Unreleased — 2026-09-09（F-089 公开仓裸机器路径中性化 + 静态扫描钉）

- **F-089 处置（审计 WB-B5 / 简报 WB-20260909-03，fix+test，Orchestrator 亲执行）**:
  F-067b 自订"路径全部中性化、不允许新 commit 再回写机器路径"，但 legacy/README
  与 handoff_guard docstring 等仍带 `<d-claude-root>` 形态（F-069 二审 H-1 只查了
  `.github/`，漏了其余 tracked 文件——**检查面写成"上次查过的面"而非"全部面"是
  本次根因**）。处置两件:
  1. **中性化 15 处**（CHANGELOG 8 处历史账目段除外）: legacy/README ×8、
     README ×3、CONTRIBUTING ×1、SENSITIVE_FINDINGS ×1、handoff_guard
     docstring ×1。占位词按语境分两类: 工作区根 → `<d-claude-root>`
     （F-067b 既有惯例）; 私有仓指称 → `<维护者私有仓>`（指称对象是"哪个仓"
     而非路径本身）。handoff_guard 仅动 docstring 字符串，判据逻辑零改动。
  2. **静态扫描钉** `tests/test_source_hygiene_paths.py`（2 例）: 扫 git
     ls-files 的 .py/.md，断言零命中 `D:[\/]claude`（大小写不敏感、双分隔符）;
     先红后绿（临时放回一处 → 红 → 还原 → 绿）。**豁免 = {CHANGELOG.md}**:
     历史账目段属 append-only 保护区，路径是账目的一部分，事后擦写会断证据链
     （F-069 记账纪律）——豁免是显式决策并有最小性钉防静默扩大。
  - 施工实录: ① heredoc 传输层吞反斜杠把正则字符集变未闭合（PatternError）——
    含反斜杠的内容一律 chr(92) 构造（F-067b 教训第 2 条再验证）; ② 正则字符集
    内 `\]` 会转义闭括号，双反斜杠+斜杠才合法; ③ 红证注入后 `git checkout --
    README.md` 把已完成的中性化一并还原——checkout 恢复的是 HEAD 全文件，
    注入验证要在提交后做或用精确行还原。
  - 全量绿。
## Unreleased — 2026-09-09（F-088 verify 主流程失败/重试分支集成测试 + 死分支登记）

- **F-088 处置（审计 WB-B6 / 简报 WB-20260909-02，test，Orchestrator 亲执行）**:
  P0-1（F-085）漏网的根因是主流程「build 成功线」零覆盖。F-085 已补 happy path，
  本批扩面到**失败与重试分支**：新增 `tests/test_verify_mainflow_retry.py`（6 例，
  S1~S6），全部真实驱动 main()（临时 workspace + 步骤 mock + 真实台账/失败现场落盘断言）：
  S1 flash 重试耗尽 → flash_failed + last_failure.json（`.workbench/build/`，
  failure_context.py:70 实证路径）+ 早退落台账；S2 flash 第 3 次重试成功 → ok 且
  step_durations 含 flash；S3 build 重试耗尽 → build_failed；S4 analyze error 现实行为；
  S5 rtt capture 失败 → capture_failed + 失败现场；S6 HIL 守卫 exit 2。
  **⚠️ 新发现登记（超出原审计清单，按"只登记不修复"禁线处理）**：
  `build_has_errors` 分支（verify.py:583）**gcc/keil 两后端均不可达**——analyze
  error 不会 break 出 build 重试循环 → 循环耗尽后必走 build_failed 早退（543-556）。
  S4 用例钉住现实行为，修复死分支时翻转。处置选项：① 删死分支；② analyze error
  时 break 改判 build_has_errors（保留"产物存在但有错"语义）。交维护者拍板。
  **施工实录（三条 mock 教训）**：① `_slow(_flash)` 把函数对象当静态 result →
  flash.get AttributeError——带副作用的 mock 不能再被"静态返回值"包装器包一层；
  ② `mock.patch("verify.time.sleep")` 换的是**全局 time 模块**的 sleep（verify.time
  IS time），测试自用的 `_slow` 睡眠一并被吞 → duration_sec 全 0——改用
  perf_counter 自旋等待；③ last_failure.json 实际落 `.workbench/build/`（不是
  feedback/）。全量 452 绿（446+6）。

## Unreleased — 2026-09-09（F-087 生成器三连修：gpio 上拉 / systick Handler / adc 分频）

- **F-087 处置（审计 WB-B1 / 简报 WB-20260909-01，fix，Orchestrator 亲执行——WordBuddy 暂不可用）**:
  三个生成器各一处缺陷（来源：2026-09-08 全项目审计 P1-4/P1-5/P1-6）——
  **① gen_gpio 上拉实为下拉（B 类静默）**: `in-pullup` 只写 CRL/CRH（CNF=10/MODE=00），
  而 RM0008 该模式下上下拉方向由 ODR 决定、复位 ODR=0 → 实际是下拉，与标签相反。
  处置 = `in-pullup` 追加 `ODR |= (1UL << n)`；其他模式零波及（反向钉
  `test_non_pull_modes_do_not_touch_odr_f087`）。`in-pulldown` 同族语义**本仓无此模式**，
  已在简报声明"只报告不实施"——报告结论：mode_map 无 pulldown 条目，无需处置。
  **② gen_systick 的 delay_ms 永久挂死（fail-loud）**: Handler 空体（仅注释）而
  delay_ms 依赖 tick_ms 递增 → 首次调用即死循环。处置 = Handler 体补 `tick_ms++`
  （F-080 同族不变量："ISR 必须推进被等待的标志"）；伴随约束 tick_ms 声明提前到
  Handler 之前（生成物是可独立编译片段，先用后声明编译即失败，钉
  `test_tick_ms_declared_before_handler_f087`）。
  **③ gen_adc 无 ADCPRE 配置（与仓内 KB 自相矛盾）**: 默认 /2 → 36MHz 超出
  `f103_known_issues.json` 明文的 14MHz 上限。处置 = 先清后置 CFGR 位 15:14 = 10b
  （ADCPRE=/6 = 12MHz），`|=` 保留其他位（钉 `test_adclock_prescaler_set_within_14mhz_limit_f087`
  断言无整体赋值）。
  - 先红: 6 例新增断言全红（ODR×2 / tick_ms×2 / ADCPRE×2）；修复后绿。
  - 变异验证 ×3: 撤 ODR → 2 红；撤 tick_ms++ → 1 红；撤 ADCPRE → 2 红；各自还原绿。
  - **施工教训（烟测拦截）**: ② 首版把 `delay_ms` 定义搬进片段时**漏了它的收尾 `}`**——
    F-078 语法烟测（arm-gcc -fsyntax-only）当场拦截 `expected declaration or statement
    at end of input`。这正是 F-078 建闸的价值实证：语法烟测抓的是"人眼与单测都看不出
    的结构错误"。初版单测 `assertIn("tick_ms", handler_body)` 也被注释字面量骗过
    （"F-087: 必须递增"注释含 tick_ms），改为 `assertRegex(tick_ms\+\+)` 语义断言——
    **断言要钉行为不要钉字面量**。
  - 全量 446 绿（439+7 新例）；语法烟测全绿（arm-gcc 在场）。

## Unreleased — 2026-09-08（F-086 gen_timer_int 双 C 类缺陷修复）

- **F-086 处置（审计 WB-A2 / 简报 WB-20260908-04，fix）**: gen_timer_int
  两项 C 类静默缺陷——
  **缺陷 1（向量名）**: TIM1 产出 `TIM1_IRQHandler` / 注释 `TIM1_IRQn`，
  CMSIS 事实为 `TIM1_UP_IRQHandler` / `TIM1_UP_IRQn`（bit25 = TIM1_UP）；
  生成物编译链接都不报错（弱默认处理函数接管）→ ISR 永不执行，真机表象
  "卡死/无反应"。修法 = 按定时器分派向量名（TIM1 → UP 变体，TIM2~4 常规
  命名不动，TIM9/10/11 兜底语义不变）。
  **缺陷 2（ARR 溢出）**: timer-int 固定 PSC=71（1MHz tick）无缩放自由度，
  ARR = 1e6//target_hz - 1；period ≥ 63ms 即超 16 位（1000//period_ms 整除
  使阈值早于名义 65.5ms——63ms→15Hz→ARR 66665，简报"约 66ms"的估算未计
  该整除，以实测为准），硬件截断后注释仍写名义周期。
  **ARR 路线选择论证（简报 §3③ 二选一）**: 选 **(a) 报错退出**——对照
  gen_pwm 的"最接近值+旁注"依赖候选 ARR 表可缩放（PSC 联动调频），周期类
  配置在固定 PSC 下无此自由度，钳制 65535 会产出实际周期偏离请求值 16 倍
  的"看似正确"配置；仿 gen_systick/gen_i2c 先例返回 `/* ERROR */` 注释，
  且 main() 的 timer-int 分支检出 ERROR 时 `sys.exit(1)`（机器消费方按
  退出码判失败，stdout 仍留机器可读错误）。
  - 先红: test_gen_interrupt_safety 新增 Timer1VectorNameTests 3 例 +
    test_gen_numeric_sweep 新增 TimerIntArrBoundaryTests 4 例（ARR 精确值、
    ERROR 分支、CLI 退出码 1）→ 7 例红；转绿；双重变异（向量名回退 +
    守卫移除）→ 7 例红 → 还原绿。
  - 简报 §3⑤ 复现复核: TIM1 输出 `TIM1_UP_IRQHandler` / `TIM1_UP_IRQn = 25`；
    TIM2@1000ms 输出 ERROR 且 exit=1。gen_pwm 对照物零改动；data/ 禁区零改动。

## Unreleased — 2026-09-08（F-085 verify.py 成功路径台账漏参修复）

- **F-085 处置（审计 WB-A1 / 简报 WB-20260908-03，fix）**: verify.py 正常出口的
  `record_checkpoint(...)` 只传 6 个关键字参数，漏 `gate_run` 与 `step_durations`
  （早退路径两者都传）。契约后果（checkpoint_ledger.py:68-70 原文）：① 成功路径的
  门禁重跑照常 append 台账，污染 release audit 的"上次 PASS"语义；② F-050 时长画像
  只收到失败样本，成功运行被当"旧格式"跳过并误报警告。
  处置 = 按简报 §3② "复用早退组装逻辑、勿出新分叉"：提取共享 helper
  `_step_durations_from(result)`（step_keys + step_durations 组装），正常出口与
  `_record_checkpoint_early_exit` 共用，正常出口补传两参数。**范围说明（超出简报
  §1 字面的一处，单独论证）**：早退路径的内联组装改为调用同一 helper——行为逐字节
  不变（既有 test_verify_failure_paths / test_checkpoint_ledger 全绿佐证），否则
  组装规则必然两处分叉；filter 口径统一为 early-exit 严格形态（status None 不收，
  真实运行 steps 必有 status，无实际影响）。**契约未变声明**：checkpoint_ledger.py
  零改动，本任务只修调用方。
  - 新增 `tests/test_verify_main_success_path.py`（3 例）——本仓**首个驱动 main()
    走通 build 成功线**的集成测试：临时 workspace + mock build/analyze/flash/capture
    （各 ~60ms 真实耗时保证 duration_sec>0），真实 checkpoint_ledger 落盘断言：
    --gate-run 成功运行 jsonl 不追加且 state.json 标 gate_skip；正常成功
    step_durations 非空且键为实际步骤；同 workspace 两次运行 append 两行。
  - 先红：两例失败原因正是 gate_run 未生效 / step_durations 为空；变异验证：
    删掉补传的两参数 → 2 例红 → 还原 → 绿。


## Unreleased — 2026-09-08（F-076 补：行内注释期望值订正，验收 L-1）

- **F-076 补（docs，2026-09-08 验收发现）**: gen_periph.py 的 F-076 行内注释
  「应 0xCB00」为 F-071 笔误的注释残留（与测试断言 0xCC40 及 F-076 段账本订正
  自相矛盾）。处置 = 注释改 0xCC40 并加订正指针；本段为账本记录（append-only，
  不改 F-071 旧段）。

## Unreleased — 2026-09-08（F-077 修复 TIM1 时钟总线：APB1 → APB2）

- **F-077 处置（生成缺陷修复 #4，fix，2026-09-08 剖析报告遗漏项）**:
  gen_pwm / gen_timer_int 的时钟使能硬编码 `RCC->APB1ENR |= RCC_APB1ENR_{tim}`，
  TIM1 是 APB2 外设（RM0008: APB2ENR bit 0 = TIM1EN）——旧版对 TIM1 产出
  `RCC_APB1ENR_TIM1EN`，该宏在 CMSIS 头不存在（A 类，编译可拦）；更隐蔽的
  变体是 AI 消费者顺手"修"成使能别的位 → 定时器时钟从未开启（B 类）。
  处置 = 新增 `TIM_BUS = {"TIM1": "APB2"}` 映射，两个生成器按表取总线；
  未知定时器保持 APB1 兜底（fallback 语义由既有测试钉住，真实 TIM9/10/11
  挂 APB2 属"未知外设支持"范围，另立事项不入本修复）。新增 TIM1 APB2
  断言 ×2（pwm / timer-int 各一）。

## Unreleased — 2026-09-08（F-076 修复 BRR fraction 进位丢失 + 订正 F-071 笔误）

- **F-076 处置（生成缺陷修复 #3/3，fix）**: F-071 登记的第 ② 号缺陷——
  gen_usart 的 BRR 装箱用 `(m<<4)|f`，fraction 舍入到 16（= mantissa 进位）
  时奇数 m 的 bit4 已被占用，`|16` 静默丢进位。实测 baud=1377 @72MHz：
  div=3267.974 → 旧版输出 0xCC30（=3267.0），修复后 0xCC40（=3268.0）。
  实际波特率偏差约 0.03%（远小于 UART 2% 容限）——如实评估：逻辑缺陷成立、
  实战危害低，修复价值在"生成器数值装箱必须可证明正确"。
  处置 = fraction>=16 时 mantissa+1、fraction=0 再装箱。
  **账本订正**：F-071 旧段与本例 docstring 曾写"应 0xCB00"为算术笔误
  （3268<<4 = 0xCC40；0xCB00 = 3248.0），按账本 append-only 纪律不改旧段，
  以本段为准。该笔误的 expectedFailure 若在修复后未订正会 XPASS（期望值
  本身错误无法转绿）——恰好演示了"没见过红的测试不算测试"的另一半：
  期望值也要能被证伪。GenKnownGapTests 三例清空，类随之移除。

## Unreleased — 2026-09-08（F-075 修复 gen_usart 低引脚 CRH 硬编码）

- **F-075 处置（生成缺陷修复 #2/3，fix，B 类静默缺陷）**: F-071 登记的第 ① 号
  缺陷——gen_usart 的 GPIO 配置硬编码 CRH，低引脚 (<8) 的位移落在 CRH 的
  错误字段上：实测 `USART2 @ PA2/PA3` 生成 `GPIOA->CRH` 位移 8（实为 PA10
  的配置字段），PA2/PA3 保持浮空 → **生成物编译通过但 USART2 TX 无输出**
  （B 类：构建关卡失明，只能靠 capture/verify 或真机调试兜底）。
  处置 = 改用 `pin_cr_reg(tx/rx)` 按引脚号选择 CRL/CRH（位移沿用
  `pin_cr_shift` 的 (n%8)*4，与两段寄存器布局一致）——寄存器选择逻辑收敛到
  F-071 已测的 helper 上。翻转对应 expectedFailure，并新增
  `test_low_pins_use_crl_high_pins_use_crh` 钉（断言 PA2/PA3 输出全部走 CRL、
  高引脚 PA9/PA10 仍走 CRH 防止修过头）。

## Unreleased — 2026-09-08（F-074 修复 gen_doc 依赖段 ENR 双写）

- **F-074 处置（生成缺陷修复 #1/3，fix）**: F-071 登记的第 ③ 号缺陷——
  gen_doc 依赖段拼接 `RCC_{rcc_register}ENR`，而 KB 的 rcc_register 本身已带
  ENR 后缀（实测全表 55 外设仅 APB1ENR/APB2ENR/AHBENR 三值，无一例外），
  产出 "RCC_APB1ENRENR" 这种头文件不存在的宏，AI 照抄进 C 代码即编译失败
  （A 类：闭环 build 可拦，但每轮烧录迭代白跑一次）。
  处置 = 防御式归一化：不以 "ENR" 结尾才补后缀，未来 KB 条目只写 "APB1"
  也能拼出合法宏名。`tests/test_gen_periph.py` 的 GenKnownGapTests 对应
  expectedFailure 已翻转，完整正确形态断言收敛进 GenDocTests（3 例 → 2 例）。

## Unreleased — 2026-09-08（F-073 README 版本标注漂移修正：单一事实源核对钉）

- **F-073 处置（文档漂移，docs+test）**: README「项目结构」段把 VERSION
  标成 0.3，而 VERSION 文件已是 0.4 —— 与 F-034"文档单一事实源"纪律冲突。
  处置 = 最小修正 + 机器核对:
  1. README:225 改为 `当前 0.4（版本唯一事实源 = VERSION 文件，经
     wb_common.toolkit_version() 读取）`——标注值与事实源指向同框写明;
  2. 新增 `tests/test_version_single_source.py`（2 例）: README 中任何
     "VERSION ... 当前 X.Y"标注必须等于 `toolkit_version()`; 找不到标注
     也会显式失败（防空转），测试 docstring 写明"改为完全不写版本号"
     是合法解法，届时须同步改写测试并记账。
  - 先红后绿: 临时把 README 改回 0.3 → 测试红（报 README:225 漂移），
    还原 → 绿。
  - 未采信方案（记账）: 由脚本从 VERSION 生成 README 该行——属引入
    生成步骤的重构，超出"最小修正"范围；机器核对钉已达到同等的防漂移
    效果且零构建成本。

## Unreleased — 2026-09-08（F-072 coverage_lint 口径修正：与真实覆盖率对齐）

- **F-072 处置（coverage_lint 双向脱节，fix）**: 2026-09-08 coverage 实测坐实
  旧口径（F-049 只看"tests 是否直接 import 模块名"）与真实行覆盖率双向脱节:
  - 假阳: `expectations.py` 24 例测试全部经 verify 再导出（tests 只
    `import verify`），旧口径报"未覆盖"，真实覆盖 95%;
  - 假阴: 模块仅被 import 但语句从未执行，旧口径算"已覆盖"。
  处置 = `scripts/coverage_lint.py` 判定口径重写为双模式:
  1. **static-reachability（默认，零依赖）**: seeds = tests 直接 import 的
     模块名，沿 scripts 内部 import 图（AST）做可达闭包——复现本仓
     "拆分件再导出"惯例（F-029/F-055~F-061）的间接覆盖;
  2. **coverage-data（`--coverage-data <.coverage>`）**: 用 coverage 包逐文件
     重算 executed/stmts，文件级"是否至少执行过一条语句"与真实行覆盖率
     同源; coverage 包缺失/数据文件缺失 → exit 2 带可行动指引。
  - JSON 契约新增 `mode`（static-reachability | coverage-data）、
    `coverage_data`、`coverage_pct`（仅真实模式）—— 纯增量，无破坏，
    `toolkit_min_version` 无需上调（契约变更三件套: 本段 + 同 commit
    test_coverage_lint_reachability 契约钉 + 此处声明）。
  - 回归钉 `tests/test_coverage_lint_reachability.py`（11 例）: 密封 fixture
    复现再导出链（修复前断言失败）、仓库级断言 expectations.py 不再误报且
    真零覆盖文件（cube_to_keil/serial_mux）仍被抓出、import 环终止性、
    coverage-data 模式抓"被 import 但 0 语句执行"（封假阴）、缺数据文件
    exit 2、strict 门禁双模式可用。coverage 包未装时相关 5 例自动 skip
    （CI 默认不装，静态模式不受影响）。
  - 实测（HEAD 8b8f2ba 基线）: 静态模式未覆盖清单 14 → 12，
    expectations.py / gen_periph.py 误报消失，真零覆盖 12 文件全数保留;
    coverage-data 模式与 coverage 实测逐文件一致。
  - 如实声明残余局限: 静态模式"可达 ≠ 每行都执行过"（tests import 但低
    执行率的文件仍会算已覆盖），该场景由 coverage-data 模式兜底——docstring
    与测试注释均已写明。

## Unreleased — 2026-09-08（F-071 gen_periph 测试补齐：0% → 99%）

- **F-071 处置（gen_periph.py 零覆盖补齐，test）**: 2026-09-08 全仓 coverage
  实测 scripts/ 6,664 语句仅 31%，`gen_periph.py` 528 语句 0% —— 而它是给
  AI 产出寄存器级 C 代码的唯一入口，生成物会被直接粘进固件。
  处置 = 新增 `tests/test_gen_periph.py`（50 例），只补测试不动生产代码:
  - pin_* helpers 逐条钉（位移 %8 环回 / CRL-CRH 分界 / 多位数引脚）;
  - 9 个 gen_* 各走"平凡路径 + 分支/边界": APB1/APB2 总线选择、SMPR1/2 与
    CCMR1/2 与 CRL/CRH 寄存器选择、BRR/CCR/PSC-ARR 换算、未知外设与非法
    参数的错误分支、gen_doc 的 relationships-only 兜底与输出目录默认值;
  - main() argparse 分发与 4 个必填校验的退出码 1;
  - 变异验证（先红后绿纪律）: 注入 3 处变异（pin_cr_shift ×8 / SysTick
    LOAD-2 / I2C fast CCR ÷3→÷2）→ 19 例转红; 还原后全绿。
  - 实测覆盖: `gen_periph.py` 0% → **99%**（528 语句缺 7，余量为
    `__main__` 守卫）。
  - 副产品（登记不修，范围限定"补测试"）: 发现 3 个生成缺陷，按 xfail
    纪律以 `expectedFailure` 钉在 `GenKnownGapTests`（修复后 XPASS 须翻转）:
    ① gen_usart 硬编码 CRH，低引脚 (<8) 应走 CRL; ② BRR fraction 舍入到
    16 时 `|` 拼装在奇数 mantissa 下丢失进位（1377 baud → 应 0xCB00 实际
    0xCC30）; ③ gen_doc 依赖段 `RCC_{rcc_register}ENR` 与寄存器名自带 ENR
    重复 → "RCC_APB1ENRENR"。


- **F-001**（Critical）feedback_db 首次落账死锁——button-toggle 建成以来
  反馈零落账（4866fb5 *(legacy, 9-01 历史重写后失效)*）。
- **F-002** config 容错 / **F-003** 采集超时诚实化（部分输出回收+失败
  现场落盘，待真机终判）/ **F-004** 落账三态留痕 / **F-005** hardfault
  默认 map 自动发现（1baeed2 *(legacy, 9-01 历史重写后失效)*、11eb319 *(legacy, 9-01 历史重写后失效)*）。
- **F-014** 校准库损坏容错（.corrupt 隔离 + 空库重建）（afc7265 *(legacy, 9-01 历史重写后失效)*）。
- **F-006/007/008/012** Low 清理组；F-009/010/011/013 记录不修（fa5efb4 *(legacy, 9-01 历史重写后失效)*）。
- 新工具 **release_audit.py**（M-3）: 发布记录事后审计 R1~R6（eb1e4c9 *(legacy, 9-01 历史重写后失效)*）。
- **主干补充**（主控，master，首轮换回后当日——R2 分支未及见的 8 commit）:
  hardfault 三层全修 symbols 0→126 真机坐实（920e187 *(legacy, 9-01 历史重写后失效)*）；F-015 workspace 跟随
  --project / F-016 采集窗进契约 / F-017 load_project_config 段语义双重错误
  （1819e18 *(legacy, 9-01 历史重写后失效)*，106/106）；插板终判四项全绿（d052060 *(legacy, 9-01 历史重写后失效)*）；A-02 哈希举证对账（f4b5d4f *(legacy, 9-01 历史重写后失效)*）。

## Unreleased — 2026-09-08（F-078 生成代码语法烟测：CMSIS 符号契约 + arm-gcc 前置闸）

- **F-078 处置（A 类缺陷前移，test）**: 新增 `tests/test_gen_syntax_smoke.py`
  —— 全部 gen_* 代码路径（18 片段 + 非整除注释分支）输出过
  `arm-none-eabi-gcc -fsyntax-only`。机制：把"AI 抄进工程 → build 炸 →
  烧录迭代白跑"的 A 类缺陷（幻影宏/语法错）前移到提交前就红。
  - stub 头 = "生成器 ↔ CMSIS 接口契约"：枚举生成器可引用的全部结构体
    成员与 RCC/外设宏；两头越界都算失败（生成器引契约外符号红，契约漏
    定义也红），另有反向钉：生成输出中每个 RCC 宏必须能在 stub 找到
    #define，防未来新增外设时漏扩契约。
  - 片段语义处理（如实记账）：生成物是贴进模块 .c 的混合片段（裸语句 +
    static 辅助函数），非完整翻译单元；烟测做机械变换（剥行首 static 后
    包进函数，GNU C 嵌套函数合法）换取语法+符号全量检查——static 存储
    类布局的合法性不在烟测范围，由 review 兜底。
  - 环境：arm-none-eabi-gcc 不在场时整组 skip（CI ubuntu 不装工具链，
    与 coverage-data 测试同款守卫）；变异验证：注入 gen_pwm 幻影时钟宏
    → 烟测 2 例红，还原后全绿。

## Unreleased — 2026-09-08（F-079 生成器数值扫描：点断言升级性质断言）

- **F-079 处置（连续域回归防线，test）**: F-071 的点断言可被"改舍入策略/
  改候选 ARR 表"绕过——孤点之外的整个值域不受保护。新增
  `tests/test_gen_numeric_sweep.py` 扫性质而非扫点:
  - USART BRR: 14 档标准波特率 × 双总线，性质 a) 装箱分频偏差 ≤ 半 LSB
    (1/32，正确舍入的紧上界，与速率无关——F-076 进位缺陷在这条性质下
    无处遁形)；b) 实际波特率误差 ≤ 2% (UART 实用容限)；
  - PWM: 1..2000Hz 全扫 + 高频样本，性质 a) 无旁注即必须精确整除
    (freq×(PSC+1)×(ARR+1) == 72e6 纯整数断言)；b) 旁注 actual 必须与按
    PSC/ARR 重算值一致 (生成器不许声称产不出的频率)；c) PSC/ARR ∈ 16 位。
  - 黑盒契约: 全部解析自生成输出，不 import 生成器内部变量。
  - 变异验证: 舍入 round→int (截断) → 半 LSB 性质红；还原后与
    test_gen_periph/smoke/卫生测试全绿 (59 例)。

## Unreleased — 2026-09-08（F-080 生成代码中断安全模式钉）

- **F-080 处置（C 类最低配置前移到测试，test）**: 钉生成物里中断相关
  的最低安全模式——丢了不报编译错但属 C 类缺陷: ① ISR 共享变量 volatile
  (丢了在 -O2 下 delay_ms 死循环)；② delay 必须 __WFI 睡眠；③ SysTick
  CTRL 必须含 TICKINT (否则 tick 永不走)；④ 定时器 ISR 先查更新标志、
  清标志在 if 体内且先于业务 TODO (清在体外=每次中断都清, 清在业务后=
  慢了丢标志)；⑤ Handler 名必须符合 CMSIS 向量表命名 (名字错=中断
  静默不触发, 链接器不报错)。与 F-071 的 IRQ 编号钉互补不重复。

## Unreleased — 2026-09-08（F-081 hardfault 解析层补测 + 新缺陷发现登记）

- **F-081 处置（失败归因主体补测，test）**: hardfault.py 300 语句 27%
  (2026-09-08 实测)，它是闭环 Step 4b 失败归因的主体且核心全是纯函数。
  新增 `tests/test_hardfault_parse.py` 20 例: parse_reg_value（含 sp/msp
  整词匹配防误吸）、parse_mdw_value、parse_registers 全 dump、
  classify_fault 六分支（no_fault 语义=2026-08-12 修复钉 / FORCED 下
  BFSR>UFSR>MFSR 优先级 / 未知位原样落 raw 不装懂）、parse_map_symbols
  （GCC ld 版式 + 伪行过滤 + ARMCC 版式 + 缺文件）、_map_degradation_note、
  resolve_address（区间匹配 + F-005 无 size 最近前导兜底 + 低于一切返回
  None）、classify_address_range（F103 地址空间 7 分区）。
  **新缺陷发现登记**: resolve_address 注释"优先匹配小函数（更精确）"与
  实现 `size > best_size`（选最大）矛盾——嵌套场景 PC 落在大函数内的
  小 helper 时会误报外层函数，误导归因。按 xfail 纪律以 expectedFailure
  登记（断言按注释意图写），修复另立 commit (F-082)。既有
  test_hardfault_map.py 的单符号场景与新语义不冲突（零修改全绿）。

## Unreleased — 2026-09-08（F-082 修复 resolve_address 符号匹配优先级）

- **F-082 处置（归因准确性修复，fix）**: F-081 登记的注释/实现矛盾——
  resolve_address 的 `size > best_size` 实际选**最大**包含符号。危害场景:
  生成代码把多个函数内联进同一 region 时（或符号表含大小函数嵌套），
  PC 落在大函数内的小 helper 会误报成外层函数，HardFault 归因直接指错
  修改位置。修复 = `best is None or sym["size"] < best_size`（真正选最小
  包含符号，同尺寸保持先到优先）；无 size 的 GCC 符号区间匹配恒空，
  F-005 最近前导兜底路径不受影响（既有测试钉住）。F-081 的
  expectedFailure 翻转为常规断言。

## Unreleased — 2026-09-08（F-083 知识库数据一致性校验）

- **F-083 处置（上游数据防线，test）**: stm32f103-ref.json (55 外设) 是
  rm_lookup/gen_periph/gen_doc/phase_minus_one 的共同上游，此前无一致性
  防线——RCC 位错一位 = 生成代码使能错外设，IRQ 号错 = 中断静默不触发。
  新增 `tests/test_kb_hygiene.py` 8 例结构不变量校验: _meta 计数与实际
  一致（漂移即红）、base 地址空间合法性（外设区 + CM3 私有区 + FSMC
  0xA0000000，GPIO 多基地址版式特判）、clock rcc_register ∈ 实测合法集
  且 bit<32、引脚端口/编号物理合法（mode 可选——通道类引脚本无 mode）、
  IRQ 编号 ≤67 且符合 CMSIS *_IRQn 命名、寄存器 offset 十六进制可解析、
  known_issues 登记簿非空。
  规则演进如实记账: 初版两条规则过严是规则错不是数据错——NVIC/SysTick
  base 在 CM3 私有区、FSMC base 0xA0000000 是 RM0008 规定区域、通道类
  引脚本就无 mode，均已按数据手册修正校验范围。

## Unreleased — 2026-09-08（F-084 CI 覆盖率棘轮门禁）

- **F-084 处置（防静默侵蚀，ci）**: ci.yml 新增 coverage-gate job——
  coverage run 全量套件 + `coverage report --fail-under=38`（棘轮下限：
  2026-09-08 实测 TOTAL 40%，留 2pt 平台差异余量；纪律只升不降，
  提升后须同步上调并入账）。与 unittest 金丝雀 job 分离：金丝雀刻意
  不装 coverage（陌生人 clone 语义），本 job 装 coverage 后
  coverage-data 模式的 5 例测试在 CI 也激活。38 这个数字的动机：
  F-071 前的真实覆盖率曾从无人知晓的低位静默漂移，度量修好（F-072）
  之后的下一步就是让"掉下去"变成 CI 红。
## Unreleased — 2026-09-05（F-070 陈旧分支清理：仓库卫生）

- **F-070 处置（5 个陈旧 worktree 分支 + PR #6 worktree 留尾清理，chore）**:
  2026-09-05 末次核验发现 8 个 GitHub 分支里 5 个是 9-03 R3 期间
  F-046~F-050 5 个 PR 的 worktree 留尾（PR 全部已合并到 master，
  但 worktree 远端分支未删）；按 9-03 拍板"5 worktree 全部清理"
  原则（见 memory `embedded-toolkit-2026-09-03-reorg-complete.md`），
  本应随 PR merge 立即 `git push origin --delete` 清远端，
  留尾至 9-05 = 2 天陈旧债。

  5 个陈旧分支（PR #1~5，已合并到 master）:
  - `embedded-hil-origin-guard` (PR #1, F-046) @ c4f3a2a3
  - `embedded-checkpoint-ledger` (PR #2, F-047) @ f850154a
  - `embedded-fixture-doctor` (PR #3, F-048) @ 1231bb67
  - `embedded-coverage-lint` (PR #4, F-049) @ c7e2a483
  - `embedded-duration-profile` (PR #5, F-050) @ 23103b37

  PR #6 worktree 留尾（`embedded-keil-archive-cleanup-20260905`
  远端分支 + 本地 worktree `.claude/worktrees/keil-archive-cleanup`):
  PR #6 2026-09-05 已合并，按 9-03 拍板本应 PR 合并后立即
  `git worktree remove` + `git branch -D`；同样留尾至 9-05。

  处置（`git push origin --delete` 一次性 5 远端分支 +
  本地 worktree remove + branch -D）:

  | 操作 | 前 | 后 |
  |---|---|---|
  | GitHub 远端分支 | 8 | 3 (master + PR #6 + PR #7) |
  | 本地 worktree | 3 (master + PR #6 + PR #7) | 2 (master + PR #7) |
  | 本地分支 (worktree 之外) | 0 | 0 |
  | 陈旧分支数 | 6 (5 R3 + 1 PR #6) | 0 |

  删前 sanity (5/5 远端分支 tip 验证):
  - `git merge-base --is-ancestor <sha> master` 全部 YES
  - 5 分支 tip 全在 master 历史里，删后无 commit 失达 (git commit
    object 与 master 引用链独立，删分支名仅删引用不删对象)
  - 0 未提交改动 / 0 未推 commit

  GitHub 分支终态: `master` (3a253e4) + `embedded-keil-archive-
  cleanup-20260905` (7f55d62) + `freshcheck-fixes-20260905`
  (8895e24) — 3 个全在用，0 个陈旧。

  教训: 9-03 拍板"worktree 清理"只清本地 worktree，未联动
  `git push origin --delete` 远端分支，形成 2 天陈旧债。流程
  改进建议: worktree 清理 checklist 加"远端分支删除"一项，
  待办登记 (不在本 commit 范围)。

  零行为变化，纯仓库卫生 commit。CHANGELOG 增 1 段，0 文件
  代码改动。

## Unreleased — 2026-09-05（F-069 补: fresh-checker 二审 2 新债整改）

- **F-069 补 处置（fresh-checker 二审 2 新债，docs+process）**: 二审报 2 条新债:
  - **H-1 (新债, 必修)**: PR 模板含 `<user-home>\...` 绝对路径, 违反 F-2
    敏感信息扫描纪律。处置=`.github/PULL_REQUEST_TEMPLATE.md` line 31/51
    两处路径中性化: `~/.claude/skills/fresh-checker/SKILL.md` +
    `~/.claude/projects/<workspace>/memory/push-user-identity-rule.md`。
    验真: `grep "<user-home>" .github/` 0 命中。
  - **H-2 (新债, 必修)**: CONTRIBUTING.md §"F-035 流程例外条款" 失守处置
    段自相矛盾 (一面说"失守 = 立即 revert", 一面又用 PR #6 特例"不
    revert")。处置=显式二分:
    - A. 未来失守 (master 仍可回滚): 立即 revert → 重开 → CHANGELOG 账目
      → 复盘 (4 步不变, 明示"revert 是默认, 不是评估后再决定")
    - B. 历史失守 (PR 已合 master, hash 有效 + 测试绿 + 无安全/数据
      丢失): 不 revert (强 revert 断引用链) → 走 fresh-checker 二审 →
      整改作为新 PR → CHANGELOG 账目 (本仓 F-069 模式)
    - 明示"历史失守特例不构成失守处置常态"防"等发现再补"借口
  - **M-1 (顺手, 仓外)**: archive README `<d-claude-root>\archive\embedded-toolkit-
    keil-legacy-20260905\README.md` §"⚠ 唤起本 archive 前必读" 段示例
    仍示范 `<d-claude-root>` 替换值, 自打耳光。改示例为 `<你的工作区根>`
    (例: `D:/projects/embedded-toolkit`), PowerShell + sed 两段同步。
    archive 在仓外 (<d-claude-root>\archive\), 不入 git 索引, 仓内账目仅记录
    改动事实。

  零行为变化, 纯 docs/process 整改。325/325 全绿, skipped=1 不变。证据
  commit `1241be3`。

## Unreleased — 2026-09-05（F-069a~e 事后审计整改：fresh-checker 报 5 必修全清）

- **F-069a 处置（C-1 archive README 复活路径坏，docs+fix）**: fresh-checker 报
  archive README §"已知限制" 写"uv4 路径仍由 `machine.json:uv4_exe` +
  `keil_build.py` 自身解析"——但 F-067a 已删 `wb_runtime.resolve_param` 里
  `name=="uv4"` 特判, 实测拷回 archive 跑 `keil_build.py build --json` 必报
  `缺少必要参数: uv4` (C-1)。处置=archive README 改写:
    - §"已知限制" 第一条明确: `wb_runtime` 已无 uv4 特判; uv4 需命令行
      `--uv4` 或工程级 `keil.uv4_exe` 段或 KEIL_ROOT env 三选一显式提供;
      `machine.json:uv4_exe` **不再被 wb_runtime 消费** (F-067a 后)
    - 新增 §"⚠ 唤起本 archive 前必读" 段: 引导用户把 `<d-claude-root>`
      占位符替换为本机用户主目录盘符 (默认 D 盘, 但不假设), 配 sed/PowerShell
      全局替换示例
  顺手 L-2: `scripts/verify.py` `_keil_bridge_paths` 错误信息分多行, 同样
  引导替换占位符。先红 (errors=11) → 改 → 325/325 全绿。证据 commit `ed197de`。
  archive README 在仓外 (<d-claude-root>\archive\), 不入 git 索引, 仓内账目仅
  记录改动事实。

- **F-069b 处置（H-1 _keil_bridge_paths 零测试，test+fix）**: fresh-checker 报
  `verify._keil_bridge_paths` (F-067b 新增 54 行) 仓内零直接测试,
  F-054 import 卫生测试通过 ≠ 该函数行为正确。处置=新增
  `tests/test_keil_bridge_paths.py` 4 例 (KeilBridgePathsTests):
    - (a) env=set + 路径在 + 脚本在 → 返 (build_path, analyze_path)
    - (b) env=set + 路径不在 → FileNotFoundError 指向 archive (验错误信息含
      "占位符" 引导, 跨 F-069a 验证)
    - (c) env=unset + 默认路径不在 → FileNotFoundError
    - (d) 路径在但脚本缺失 → FileNotFoundError "脚本缺失"
  全部纯 mock (env-var / temp dir), 不触 archive 物理副本。
  **先红后绿 (F-035 纪律)**: 临时把 `_keil_bridge_paths` 改 `return None, None`
  → 4 tests, 2 failed (b/c 抛错测试红) → 还原 → 4 tests OK, 证明钉子在
  回归时真能拦截。基线 321 → 325, skipped=1 不变。证据 commit `82ce8fd`。

- **F-069c 处置（C-2 F-035 流程门禁无代码卡，docs+process）**: fresh-checker 报
  F-035 贡献流程被绕过 (PR #6 在 fresh-checker 前被 merge, reviews=[]
  comments=[]), 流程门禁只靠人守、无代码卡是结构性缺陷。处置=三件套:
    - `.github/PULL_REQUEST_TEMPLATE.md` 新增 "fresh-checker 复审门禁" 段
      (4 必填项: 已派审计 / Critical-High-Medium-Low 数量 / 已修完或接受
      风险 / 维护者直合豁免需勾选 + 例外理由 ≤200 字) + "commit 署名 9-02
      拍板" 勾选项 + Co-Authored-By trailer 警示
    - `.github/CONTRIBUTING.md` 新增 "F-035 流程例外条款 (F-069c 成文)" 段:
      主体 + 4 类例外清单 (hotfix / 纯 chore-deps bump / 上游 mirror /
      流程债重置) + 4 类例外禁止清单 (删文件 / 改共享层 / 改公共契约 /
      合并不属本仓代码) + 失守处置 4 步 (revert → 重开 → CHANGELOG → 复盘)
      + 历史失守段 (PR #6 不再 revert 原因: 6 commit hash 有效 + 全绿,
      走 F-069f fresh-checker 二审闭环)
    - CHANGELOG 本段 (即 F-069c 段) 账目
  零行为变化, 纯 docs+process。证据 commit `4e652f7`。

- **F-069d 处置（H-2 红钉 + H-3 文档谎言，test+docs）**: fresh-checker 报
    - H-2: F-067a "先红后绿"在 `test_special_tiers` 上不成立 (resolve_param
      'uv4' 永远 (None, ""), 旧 `assertIn(("", "machine:uv4_exe",
      "auto:uv4"))` 接受空串恒绿), 违反 CONTRIBUTING.md §26 "没见过红的
      测试不算测试"。处置=同测试方法加反向钉 `assertNotIn(s_wb,
      ("machine:uv4_exe", "auto:uv4"))` 固化 F-067a "删 uv4 特判" 行为
      不可逆。先红后绿: 加回 uv4 特判 → 1 test FAILED "unexpectedly found" →
      还原 → 1 test OK, 反向钉真能拦截 (commit `a8193df`)。
    - H-3: `tests/test_writeback_guards.py:85` 注释 "wb_runtime 签名多一个
      skill 段名参数 (默认 "keil")" 与 `wb_runtime.SKILL_NAME` 实际值 "wb"
      (F-067a 改) 不符——文档谎言。处置=改注释为 "(默认 "wb" 是历史延续,
      原 "keil" 2026-08-28 中性化、2026-09-05 F-067a 退役区拆 archive 后
      改 "wb"; 默认值仅兼容)"。H-3 还指出 7f55d62 / 8c087b9 commit message
      数字错 ("5 例" 实际只删 3 例) —— 已推 master, 改历史需
      force-with-lease + 用户另批, 本 commit 不动, 见本段末尾脚注。
  全量 325/325 全绿, skipped=1 不变。

  > H-3 commit message 数字修正脚注: 7f55d62 / 8c087b9 message 写的 "5 例"
  > 实指 5 例 error_db_grow 用例 (F-067b 段), 但其中 2 例 (test_healthy_session
  > _cache_appends_no_dup / test_corrupt_error_db_refused_not_wiped) 在 8c087b9
  > 内删除, 实际净删 3 例, 净减 7 例来自 4+3=7 (token_stats 4 + error_db_grow
  > 3) 与 CHANGELOG 账目 "净减 7 例 (-4 token_stats F-066 / -3 error_db_grow
  > F-067b)" 一致。commit message 措辞 "5 例" 是粗算错误, 真实数为 3, 数字
  > 修正在 F-069e 段, 历史不动。

- **F-069e 处置（M-3 CHANGELOG 22 旧 hash 失效声明，docs）**: fresh-checker 报
  22 个旧 hash (920e187 / d052060 / cc54e45 / 1819e18 等 8-26~8-31 handoff
  时期) 全部 `git rev-parse --verify` MISS, F-051 教训未根治——F-051 仅处理
  `6e3ebbc` 一个, 其余 21 个 hash 仍散落 8-30/8-31 Unreleased 段。处置=
  批量给 21 个 hash 加 `*(legacy, 9-01 历史重写后失效)*` 后缀
  (F-051 已显式处理 6e3ebbc, 不动)。实测 `grep` + `git rev-parse --verify`
  再核: 22/22 hash 失效已显式声明, 外部审计 grep 到 hash 不会再
  "看似可点但点开 404"。批改 23 处 (21 hash + 2 个重复出现)。本段同行
  处理 (M-3 + F-069c 账目合并, 因都属 docs-only 整改)。


## Unreleased — 2026-09-05（F-066~068 仓内清洁：删 token_stats + Keil 退役区拆 archive + 关联清理）

- **F-066 处置（删 scripts/token_stats.py，chore+test）**: 维护者本人 Claude Code
  会话成本计费工具（扫 `~/.claude/projects/<workspace>/*.jsonl` 按 verify/build/
  design/docs/discussion 5 桶分类算月成本），默认路径与开源用户场景完全不对齐，
  与 STM32/verify/闭环/真机无任何关系。处置=删 `scripts/token_stats.py` + 删
  `tests/test_zero_coverage_pure.py::TokenStatsTests` 4 例（class 整体随被测
  对象退役，文件继续覆盖 phase_minus_one / rm_lookup / svd_to_json）。
  先红后绿：临时移走 `token_stats.py` → test_zero_coverage_pure import 阶段崩
  （ImportError, 328 → 303）→ 还原 → 实际删 + 改 → 324/324 绿。证据 commit
  `f23d639`。

- **F-067a 处置（去 wb_runtime keil 专属死代码，refactor+test）**:
  `scripts/wb_runtime.py`（原 `keil_runtime.py` 2026-08-28 中性化）含 3 个
  Keil 专属死分支：`_machine_uv4_exe()` / `_auto_detect_uv4()` +
  `resolve_param` 里 `name=="uv4"` 两段特判。Keil 退役区拆 archive 前置清
  理。处置=删 3 个分支 + 删 `shutil.which` import + `SKILL_NAME` 默认值
  `'keil' → 'wb'`（与中性化命名对齐；实际所有调用方均显式传 `skill="gcc"/
  "openocd"/"serial"`，默认 "wb" 仅为兼容值，实测从未触发）+ 头图改写 +
  docstring 同步。测试 fixture 同步中性化：`test_gcc_build.py` GccSectionLoadTests
  注释 `默认段名是 keil 遗留 → wb 历史延续`；`test_writeback_guards.py` /
  `test_runtime_contract.py` fixture 路径 `keil.json → wb.json`（机制测本与
  keil 无关）。先红后绿路径：尝试构造红钉（改 `_machine_uv4_exe` 返空 / 删
  uv4 特判）→ 测试仍绿，因 `_machine_uv4_exe`/`_auto_detect_uv4` 当前**零
  测试直接调用**，`test_special_tiers_are_machine_name_coupled` 写得过宽
  （接受空串），不能用红钉——这是 "**死代码删了行为不变**" 的天然先绿，改
  后全量 52/52（runtime_contract + gcc_build + writeback_guards）+ 全量
  324/324 验证零回归。证据 commit `0c86d6e`。

- **F-067b 处置（Keil 退役区完整拆 archive，refactor+test）**:
  2026-08-28 Keil 从 AI 工作台退役定案后沉到 `scripts/legacy/keil/`，自述
  "不主动维护、不进任何默认路径，但随时可以原样唤起"。9-05 完整拆出到
  `<d-claude-root>\archive\embedded-toolkit-keil-legacy-20260905\`：

  | 源路径 | 大小 | 用途 |
  |---|---|---|
  | scripts/legacy/keil/{README.md, keil_build.py, keil_analyze.py, keil_project.py} | 39+678+380+119 行 | AI↔Keil 自动化桥（UV4 驱动/ARMCC 诊断/.uvprojx 扫描） |
  | scripts/error_db_grow.py | 345 行 | 知识库自增长（五重门控） |
  | data/keil-error-db.json | 786 行 / 28KB | ARMCC V5 错误码知识库（30 条） |
  | config/keil.json | 3 行 | 占位 `{"operation_mode": 1}` |

  处置流程：`git rm` 删仓内 tracked（git 历史保留被删 blob，可由
  `git log -- <path>` 查）→ `git show HEAD:<path>` 从当前 commit 取
  字节级一致副本到 archive 目录。仓内 7 个 tracked 文件删除，物理副本
  71KB（脚本 + JSON + README）落地 archive。

  `scripts/verify.py` 改写：常量 `KEIL_BUILD` / `KEIL_ANALYZE` 替换为
  `DEFAULT_KEIL_ARCHIVE` + `KEIL_BRIDGE_DIR`（env=`EMBEDDED_TOOLKIT_KEIL_ARCHIVE`，
  未设时回退到 archive 默认路径）；新增 `_keil_bridge_paths()` 启动时检测 +
  `FileNotFoundError` 指向 archive README；`step_build` / `step_analyze` 在
  `builder="keil"` 分支调 `_keil_bridge_paths()` 拿脚本路径；头图 docstring
  加注 F-067b 拆 archive 路径（raw 字符串，F-053 钉防 `\c` 非法转义）；
  路径中 `<d-claude-root>` 全部中性化为 `<d-claude-root>` 占位符（F-2 敏感信息
  扫描纪律：9-01 历史重写后不允许新 commit 再回写机器路径）。

  `tests/test_writeback_guards.py` 同步：删 `import error_db_grow` + 删
  `ErrorDbGrowGuardTests` 3 例（`_cache_entry` 损坏/健康 + `grow` 拒写）+
  删静态判据 `test_no_bare_json_writes_in_standalone_scripts` 里
  `error_db_grow.py` 名字（留 `release.py` 一份盯防 F-022） + 头图加注
  error_db_grow 自身回归留 archive 副本，主仓零 Keil 引用 = 验证目标。

  先红后绿：`git rm` 删 4 项后 test_writeback_guards import 阶段崩
  （ImportError, 324 → 303, errors=1）→ 改 verify.py + 删 error_db_grow
  测试 → 321/321 全绿，skipped=1 不变。净减 7 例（-4 token_stats F-066 /
  -3 error_db_grow 测试 F-067b）；coverage_lint 14 不变（token_stats /
  keil_* 本来就在测试覆盖中，不在未覆盖清单；14 个未覆盖是别的脚本，
  本次未触动）。证据 commit `8c087b9`。

- **F-067c 处置（文档同步 + coverage_lint 豁免改空 + test_legacy_subdir
  语义更新，docs+test）**:
  README.md 目录树注释 `legacy/keil/ 为退役留门区 → legacy/ 空目录占位,
  Keil 退役区已拆 archive, F-067b`；data/ 注释删 `错误库`（keil-error-db
  已拆）；config/ 注释加 `keil.json 退役后已拆 archive`；文档索引删指向
  `scripts/legacy/keil/README.md` 链接，改为指向 archive README
  （路径中性化）。
  `machine.example.json` `_help` 注释：`uv4_exe 仅供 scripts/legacy/keil/
  退役桥使用 → 仅供 archive 退役桥使用 (F-067b 后仓内零 Keil 引用,
  uv4_exe 可留空字符串)`。
  `SENSITIVE_FINDINGS.md` 通过项段：删 `config/keil.json` 引用；新增
  "移除项"段，记录 F-067b 拆出的 4 个文件 + 物理副本路径 + git log 查
  历史 + F-1/F-2 处置对 archive 副本仍生效（无 PII / 机器路径残留）。
  `scripts/coverage_lint.py` `DIR_EXEMPT` 由 `{"legacy"}` 改为 `set()`
  + 注释说明：Keil 退役区拆 archive 后 legacy/ 目录保留为空，未来再有
  工具置入时按需重新加入。`tests/test_coverage_lint.py` `test_legacy_subdir_excluded`
  语义更新：原 "legacy/ 不强制覆盖" → "DIR_EXEMPT 清空, legacy/ 子树下
  的 .py 文件**会**被报告（与其他未覆盖脚本同等）"。
  新建 `scripts/legacy/README.md`（仓内 38 行）：历史 + 现状 + 唤起方法
  + 未来退役工具置入规范。
  全量 321/321 绿，skipped=1 不变；coverage_lint 14 不变。证据 commit
  `7bbe4ba`。

- **F-068 处置（基线账目，docs）**: 本次清理的基线账目 (CHANGELOG 末次
  账目是 F-059 的 321 例, 9-04 末态, 经实测**仍是 321**——9-04 后无
  新 commit 改变测试数):
    - F-066 删 `TokenStatsTests` 4 例: 328 (实测 9-05 当前基线) → 324
    - F-067b 删 `ErrorDbGrowGuardTests` 3 例: 324 → 321
    - **本 PR 终态: 321/321 全绿, skipped=1 不变**
    - coverage_lint: 14 → 14 (14 个未覆盖本就是其他脚本, 本次未触动;
      F-049 实测"基线 14"清单里没有 token_stats / keil_*, 它们本就
      有测试覆盖)
    - 仓内 Keil 引用: 0 (F-066 + F-067a/b/c 联合消除; 仅剩 verify.py
      docstring 里 `<d-claude-root>\\archive\\...` 中性化路径指向
      archive 物理副本)
    - 触发链: F-046 `--require-schedule-origin` 门禁不受影响
      (Keil 工程 builder="keil" 是离线动作, 不进 release.py G0~G3 门禁
      默认路径)

## Unreleased — 2026-09-05（0.4 复核收口：账目 hash / 索引兜底 / 语法卫生，F-051~053）

- **F-051 处置（0.4 账目证据 hash 断链，docs）**: 0.4 节 F-047 引用的 `6e3ebbc` 是
  署名重写前短 hash（重写后现行历史为 `eef1851`）——0.3 重写曾声明"重写前短 hash
  全部失效"，本次重写漏做等效声明。外部复核逐 hash 验证 0.4 节 16 个引用：15 OK
  / 1 MISS，本条即该 MISS。处置=账目改指现行 hash。教训=历史重写后必须重跑
  CHANGELOG 引用 hash 全量可解析性检查（`git rev-parse --verify <hash>^{commit}`）。
- **F-052 处置（.workbench 运行时产物无索引兜底，chore）**: F-047 新增
  checkpoints.jsonl 与既有 state.json / *.corrupt 均写入固件工程 `.workbench/`，
  而本仓 .gitignore 无该条目——F-015 伪工程事故路径若在仓内复现，台账产物将进入
  git status 并有误提交风险（实测 check-ignore 未命中）。处置=.gitignore 增
  `.workbench/`；固件工程侧"config/expectations/releases 入库、state 忽略"的建议
  不变（见 README）。
- **F-053 处置（tests docstring 非法转义 SyntaxWarning，fix+test）**:
  test_failure_hints.py:3 非原始 docstring 含 `\.`——Python 3.12+ 升格为
  SyntaxWarning，coverage_lint 的 AST 全扫每轮都向 stderr 吐警告。处置=docstring
  改 raw；新增 test_source_hygiene 钉：scripts/ + tests/ 全量逐文件 compile，
  SyntaxWarning 与 DeprecationWarning（3.10/3.11 上同类告警的旧名）均升格 error
  防回潮。外部复核时扫描全仓仅此 1 处。
- **F-054 处置（verify/hardfault 模块级副作用惰性化，refactor，防腐方案 §3.3 步骤 1）**:
  两脚本曾有模块级 `OPENOCD_EXE = load_machine()[...]`——import 即文件 IO，
  machine.json 缺失时向 stderr 吐回退警告，6 个测试文件被迫注释豁免，CONTRIBUTING
  禁令 #2 亦以此为存在理由之一。处置=verify 改 `_openocd_exe()` 惰性函数（4 个使用点
  同步替换），hardfault 在 run_openocd_diag() 内惰性解析；新增 test_import_hygiene
  钉（fresh-import 式绕过 sys.modules 缓存：load_machine spy 断言 import 期零调用 +
  stderr 零输出 + 常量不再绑定）；6 例测试豁免注释收编；CONTRIBUTING 禁令 #2 /
  AGENTS.md 速查同步改写——禁令保留，理由从"副作用"升级为"分层"，防回潮机制不变。
  先红后绿：钉在修前 3/3 红（spy 命中），修后 3/3 绿。这是 verify.py 拆解
  （防腐方案 §3.3）的前置步骤——此后拆出的模块不再背负 import 期 IO。
  全量 **306 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-055 处置（expectations.py 拆分件——verify.py 拆解步骤 2，refactor，防腐方案 §3.3）**:
  期望契约层自 verify.py 摘出成 `scripts/expectations.py`（166 行）：ExpectationError /
  load_expectations / evaluate_expectations / _expect_matched / contract_hashes（含仅其
  使用的 _sha256_file）五符号整体搬迁，全部本就带 workspace 参数、零全局依赖，纯函数
  可单测。wire 兼容=verify 再导出五符号（`verify.X is expectations.X` 同一对象实测），
  35 处 `verify.X` 测试引用零修改；`import math` 随唯一使用点迁出。新模块仅标准库、
  不 import verify（分层禁令 #2）、无 machine 读取（test_import_hygiene 经 import 链
  继续覆盖）。钉=既有 24 例判定 + fixture 三关 + 35 处调用面，钉全程保持全绿；
  verify.py 1832 行（F-050 时长画像显示 capture 占 67%，下一步步骤 3 摘 capture_rtt）。
  本条纯搬迁零新增用例，全量 **306 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-056 处置（capture_rtt.py 拆分件——verify.py 拆解步骤 3，refactor+test，防腐方案 §3.3）**:
  RTT 采集后端整体摘出成 scripts/capture_rtt.py（204 行）：_step_capture_rtt（更名公开
  step_capture_rtt）+ _rtt_telnet / _rtt_read_until_prompt / _rtt_cleanup + 两个 _RTT_*
  常量。行为逐字节不变的两组差异：① WORKSPACE 全局改 workspace 参数（verify 调度点
  传参，OpenOCD 子进程 cwd 语义不变）；② openocd 路径经 load_machine 惰性解析
  （F-054 惯例）。wire 兼容 = verify `from capture_rtt import step_capture_rtt as
  _step_capture_rtt` 再导出旧私有名——3 处测试钉零修改：2 处
  mock.patch.object(verify, "_step_capture_rtt")（return_value 型 mock 任意签名兼容，
  调度点加传 workspace 不破）+ F-031 运行时钉（patch 的是 sys/subprocess/time 共享
  模块对象，对本模块同样生效）。verify.py 1646 行（-187），socket/threading import
  随唯一使用点迁出。**红利**：新增 test_capture_rtt 七例——RTT 时序（reset halt →
  resume → 宽限 → rtt setup → rtt start → server start 逐条断言，F-003 级防假 PASS
  知识）拆分前从未被真断言，现为真单测；另钉控制块未找到不重试、3 次竞态重试、
  存活会话 halt+shutdown 礼貌清理、_rtt_read_until_prompt 三态、2 参旧调用形态兼容。
  全量 **313 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-057 处置（physical_gate.py 拆分件——verify.py 拆解步骤 4，refactor+test，防腐方案 §3.3）**:
  物理层门控整体摘出成 scripts/physical_gate.py（188 行）：step_physical_gate 同名搬迁
  （TCL 运行时生成 + PHYS_GATE_RESULT 解析 + 判定数学 + 各 probe_error 分支）。
  差异三点（逐字节搬迁前提下）：WORKSPACE 全局改 workspace 参数（TCL 落盘与子进程
  cwd 均用之）；openocd 路径经 load_machine 惰性解析（F-054 惯例）；函数内
  `import re as _re` 原样保留。wire 兼容 = verify 同名再导出，调度点加传 workspace；
  无测试直接引用该符号，签名扩展零破绽。verify.py 1482 行（-164），datetime 等
  其余 import 仍被 verify 其余部分使用故保留。**红利**：新增 test_physical_gate
  八例——TCL 生成逐片段钉（预热节奏注释/初始化边沿告警/read_memory/mask 插值/
  结果行格式）、判定数学（4.0/s ok、4.8/s timing_fail+时钟树回滚文案）、
  insufficient_samples、三类 probe_error、禁用态零开销守卫。修前这些逻辑
  需要真机才能走到，从未被断言过。全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-058 处置（doctor.py 拆分件——verify.py 拆解步骤 5a，refactor，防腐方案 §3.3）**:
  环境预检家族整体摘出成 scripts/doctor.py（279 行）：doctor_report / _print_doctor /
  _check_tool / _first_version_line / _detect_default_branch / _fixture_main_sha /
  fixture_health / _DOCTOR_KEYS 整块逐字搬迁（F-041 引入的原块）。差异仅 import
  收归本模块（os/subprocess/sys/hashlib + openocd_runtime.swd_probe + wb_common 四件），
  抽取脚本断言块内零 WORKSPACE 引用（F-041 的 workspace 无关设计在此兑现）。
  wire 兼容 = verify 再导出五符号（doctor_report/fixture_health/_print_doctor/
  _detect_default_branch/_fixture_main_sha），调度分支与 CLI 零改动。测试 patch 目标
  随迁（F-029 先例）：test_doctor 三处 load_machine、test_fixture_doctor 一处
  _fixture_main_sha 改钉 doctor 模块；subprocess.run 为共享模块对象原钉不动。
  经验入账：逐字搬迁块必须跑 AST 未定义名扫描——首轮漏 TOOLKIT_ROOT/hashlib/sys/
  swd_probe 四个 import，靠 import 报错逐个补不如一次性静态扫。
  verify.py 1482 → **1225 行**。全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-059 处置（checkpoint_ledger.py 拆分件——verify.py 拆解步骤 5b，refactor，防腐方案 §3.3）**:
  F-047 台账家族摘出成 scripts/checkpoint_ledger.py（120 行）：CHECKPOINT_STATUSES /
  _git_head / record_checkpoint（双写逻辑）逐字搬迁；**_record_checkpoint_early_exit
  留守 verify**——它是读 WORKSPACE 全局与 result/args 的编排胶水，留守使其对
  record_checkpoint 的调用仍走 verify 再导出面，test_build_failed_records_checkpoint
  的 patch 零修改。wire 兼容 = verify 再导出三符号，main() 调度、早退 5 调用点、
  10 处测试调用零修改。测试 patch 目标随迁：test_checkpoint_ledger 10 处
  `_git_head` 改钉 checkpoint_ledger 模块（record_checkpoint 内部解析已随迁，
  verify 层 patch 不再可拦截——F-029 先例）。`atomic_write_json` 随唯一使用点
  迁出 verify 的 import。已知语义微调（记账）：ts 由 verify 本地 now_iso（固定
  +08:00）改为 runtime_common.now_iso 规范版（本地时区）——时刻不变，本机
  +08:00 输出逐字节一致。verify.py 1225 → **1129 行**。
  全量 **321 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-060 处置（failure_context.py 拆分件——verify.py 拆解步骤 5c，refactor，防腐方案 §3.3）**:
  失败现场家族摘出成 scripts/failure_context.py（156 行）：_save_failure_context
  （agent_hint 五分支派发）/ _filter_capture_lines（F-003 行过滤口径）+ 两常量 /
  resolve_capture_timeout（F-016）。**_finish_capture_timeout 留守 verify**——内嵌
  sys.exit(1) 与 _output 调用，是派发胶水而非逻辑；经再导出面调用本模块。
  差异三点（记账）：WORKSPACE 全局改 workspace 参数（verify 7 处调用点同步传参）；
  TOOLKIT_ROOT 自 wb_common 导入（agent_hint 随其推导，test_failure_hints 钉改指
  failure_context 模块）；ts 走 runtime_common.now_iso（同 F-059 记账）。
  静态守卫跟进：test_failure_hints 的维护者路径扫描增加 failure_context.py——
  提示串搬去哪，守卫跟到哪。经验复用：抽取后立即 AST 未定义名扫描（F-058 教训
  兑现，本次零缺失）。verify.py 1129 → **993 行**（跌破千行）。
  全量 **322 全绿**（+1=守卫新增 failure_context.py 扫描例；skipped=1 仍 F-026）。
- **F-061 处置（capture_semihosting.py 拆分件——verify.py 拆解步骤 5d 收官，refactor+test，防腐方案 §3.3）**:
  main 内联 semihosting 会话摘出成 scripts/capture_semihosting.py（64 行）：
  run_semihosting_session（cmd 构建/Popen/communicate）+ SemihostingTimeout 载体异常。
  **控制流契约（关键设计）**：超时 → 抛 SemihostingTimeout(proc) 且**模块不 kill
  不收尸**——F-003 的回收/归因/exit(1) 全在留守的 _finish_capture_timeout（携带
  proc 完成），归因链逐字节不变；非超时异常原样抛出由调用方 capture_failed 分支
  处理（与原行为一致）。调度点注释（reset halt 确定性起点/2026-08-16 教训/F-028
  留门）原位保留。verify.py 993 → **977 行**。**红利**：test_capture_semihosting
  三例——cmd 逐条钉（含 sleep ms 换算与 cwd）、超时载体不抢先 kill（防二次回收
  拿不到部分输出的回归）、非超时异常透传。逻辑全部外置达成：verify.py 剩余 =
  编排调度 + 报告输出（纯胶水，F-049 行数哲学：不再为凑 300 行而碎片化）。
  全量 **325 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-062 登记+处置（推送权限纪律缺位，docs，维护者拍板）**: 维护者 2026-09-05
  明确要求：Agent 不得直接 push 远端，推送须先经维护者审核——此前 Agent 具备
  push 能力且无成文约束（当前 15+ 提交未推送即为待审状态）。处置=CONTRIBUTING
  增「推送纪律」节 + AGENTS.md 速查补行：本地 commit → 维护者审核 → 维护者推送
  或明确授权；推送前检查清单（全量测试绿 / 工作区干净 / CHANGELOG 引用 hash
  可解析——历史重写后尤甚，见 F-051）；force-push 仅限维护者执行。纯文档零代码。

## Unreleased — 2026-09-05（防腐方案 §3.3 拆解 7 模块收官 + 推送纪律成文 + 仓边界清理 + 修复收口）

15 commit 累计，含 14 commit 已推 GitHub master（`96796ed..60d9bc0`）+ 1 commit
本地领先（`dc94b12` 仓边界清理，待推）：

  - **F-054 处置**（拆解前置：OPENOCD_EXE 模块级惰性化）——本条与上方
    「0.4 复核收口」段重复记账（双堆时期产物），**以彼段为准**（内容更全:
    306 全绿/收口链/AGENTS 速查同步），本行留指针防断链（F-092）。
- **F-055 处置（拆解步骤 2：expectations.py 拆分件，refactor）**: 期望契约层
  5 符号摘出（166 行，零全局依赖、纯函数可单测）；verify 再导出 5 符号，35
  处测试零修改（F-029 同款手法）；分层禁令 #2 兑现（新模块不 import verify /
  无 machine 读取）。verify.py -154 行。全量 306 全绿。
- **F-056 处置（拆解步骤 3：capture_rtt.py 拆分件，refactor）**: RTT 采集后端
  4 符号摘出（204 行，行为逐字节不变）；`WORKSPACE` 全局改 `workspace` 参数，
  OpenOCD 子进程 cwd 语义不变；2 参旧调用形态经缺省值 None 保持兼容
  （`test_capture_rtt` 钉）。verify.py -187 行。新增 7 例真单测——RTT 时序
  钉死 F-003 级防假 PASS（reset halt → resume → 宽限 → rtt setup → rtt start
  → server start 逐条断言）、控制块未找到不重试、3 次竞态重试、存活会话
  halt+shutdown 礼貌清理、2 参旧调用形态兼容。verify.py 1646 行。全量 313 全绿。
- **F-057 处置（拆解步骤 4：physical_gate.py 拆分件，refactor）**: 物理层门控
  整体摘出（188 行，WORKSPACE 全局改 workspace 参数 + openocd 路径惰性解析）；
  新增 8 例真单测——TCL 生成逐片段钉（预热节奏注释 / 初始化边沿告警 /
  read_memory / mask 十进制插值 / 结果行格式）、判定数学（4.0/s ok、4.8/s
  timing_fail + 时钟树回滚文案）、三类 probe_error 路径（无稳态闪烁 / 读失败
  率超限 / 无结果行 3 重试）、禁用态零开销守卫。verify.py -164 行。
  全量 321 全绿。
- **F-058 处置（拆解步骤 5a：doctor.py 拆分件，refactor）**: 环境预检家族整体
  摘出（279 行，零 WORKSPACE 引用——F-041 的 workspace 无关设计兑现）；verify
  再导出 5 符号，调度分支与 CLI 零改动；经验入账：首轮漏 4 个 import（hashlib/
  os/subprocess/sys + swd_probe + wb_common），靠 import 报错逐个补；教训
  复用：抽离后立即 AST 未定义名扫描。verify.py -261 行。全量 321 全绿。
- **F-059 处置（拆解步骤 5b：checkpoint_ledger.py 拆分件，refactor）**: F-047
  台账家族 4 符号摘出（120 行）；`_record_checkpoint_early_exit` 留守 verify
  （读 WORKSPACE 全局与 result/args 的编排胶水）；wire 兼容 = verify 再导出
  3 符号，10 处测试 patch 目标随迁（F-029 先例）；ts 走 `runtime_common.now_iso`
  规范版（时刻不变）。verify.py -96 行。全量 321 全绿。
- **F-060 处置（拆解步骤 5c：failure_context.py 拆分件，refactor）**: 失败现场
  家族 4 符号摘出（156 行）；`_finish_capture_timeout` 留守 verify（嵌入
  sys.exit(1) 与 _output 调用——派发胶水而非逻辑）；WORKSPACE 全局改
  workspace 参数（7 处同步）；TOOLKIT_ROOT 自 wb_common 导入——agent_hint
  指引随其推导；ts 走 runtime_common.now_iso。verify.py -136 行。
  全量 322 全绿。
- **F-061 处置（拆解步骤 5d 收官：capture_semihosting.py 拆分件，refactor）**:
  semihosting 会话 2 符号摘出（64 行）；控制流契约（成功 → 返回 tuple；
  超时 → raise `SemihostingTimeout` 携带 proc，模块不 kill 不收尸——F-003 的
  回收/归因/exit(1) 全在 `_finish_capture_timeout` 留守）；非超时异常原样
  抛出。verify.py -16 行（终点 977 行）。新增 3 例真单测（cmd 逐条钉、超时
  载体不抢先 kill、非超时异常透传）。全量 325 全绿。**防腐方案 §3.3 拆解
  收官**——verify.py 剩余 = 编排调度 + 报告输出（纯胶水）。
  - **F-062 处置**（推送权限纪律成文）——与上方「F-062 登记+处置」
    同一事件重复记账（双堆时期产物），**以彼段为准**，本行留指针
    防断链（F-092）。
- **F-051~053 修复收口（fresh-checker 复核 High 处置 9-05 上午）**:
  - **F-063（H3 修复，code）**: `physical_gate.py` `fail_reads` 解析改
    默认 -1 + ValueError 异常 + 负值 raise `probe_error`——
    修前非法值（`abc` / 负号 / 缺失）静默默认 0 绕开"读失败率超限"分支；
    修后探针实测 `fail_reads=abc` → status=probe_error。3 例新 test 钉
    （缺失/负值/字母三路径）。全量 327 全绿。`71fb20a`。
  - **F-064（H2 修复，docs）**: CHANGELOG 0.4 节标题下补"本账目与 docs 中
    引用的'重写前短 hash 全部失效'——同 0.3 节 9-01 公开准备的声明"等效
    段，覆盖两轮重写（0.3 filter-repo 脱敏 + 9-02 推送署名 filter-branch
    user-identity）；引用本节 hash 前请用
    `git rev-parse --verify <hash>^{commit}` 验证现行可解析。`c3bcb6d`。
  - **F-065（H1 标注，docs）**: F-062 推送纪律节末尾 + AGENTS.md 速查同位
    追加"本节性质"段，显式标"道德约束非技术卡"——本仓无任何 git hook /
    pre-push / CI 阻断逻辑会拦截 Agent 推送，技术兜底在（1）GitHub 远端
    分支保护 master 需 PR + ≥1 审 +（2）维护者人工审核；防"以为已卡死"
    误读。`60d9bc0`。
- **`19c9521 chore(setup-matt-pocock-skills)` 处置（agent 协作 skill 落地,
  docs）**: 19 个 PR 待审期间按 Matt Pocock skills 框架注册工程——docs/agents/
  三件套（issue-tracker / triage-labels / domain）+ AGENTS.md ## Agent skills
  段指向上述文件；本次"AI 协作私约"迁出后该 commit 的 docs/agents/ 实际
  已不在仓内（`dc94b12` 边界清理合并删除），但其本意"工作流登记"以新仓
  `<d-claude-root>\embedded-handoff\docs\agents\` 形式继续存在——按维护者
  拍板，登记本节作为完整性记账。
- **`dc94b12` 仓边界清理（refactor 0.4 边界）**: 维护者拍板公开工具库
  embedded-toolkit 不应含维护者 ↔ Agent 协作私约——迁出 17 文件（AGENTS.md
  / HANDOFF-AGENT.md / docs/agents/×3 / docs/handoff/×5 / docs/superpowers/×6
  / skills/fresh-checker/×1）到新私有仓 `<d-claude-root>\embedded-handoff\`
  （独立 git 仓，commit `0845ea6 *(legacy, 9-01 历史重写后失效)*` *(legacy, 9-01 历史重写后失效)*，不推 GitHub 远端）；本仓改写 3 文件
  （CONTRIBUTING 删"推送纪律"段 + README 结构图/文档索引/末段去私约引用 +
  handoff_guard.py docstring 引用改外链 + raw string 修正 SyntaxWarning
  复用 F-053 教训）；**本仓净减 3511 行**。scripts/handoff_guard.py
  保留——沙盒禁线机器判据是工具库本职而非私约，spec 文档迁出后由维护者
  人工外链引用。

## 0.5 — 2026-09-09（静默失败清零 + 生成器修复 + 治理基建）

> 发布内容 = 2026-09-08~09 的 F-071~F-093 全部账目（上方 Unreleased 堆，
> 时间新段在上）。要点导览:
> - **生成缺陷修复 ×9**（F-074~077/F-082/F-086/F-087: ENR 双写/usart 低引脚/
>   BRR 进位/TIM1 总线/resolve_address/TIM1 向量名+ARR 溢出/gpio 上拉/
>   systick 挂死/adc 分频）——生成器数值与寄存器选择全部有性质级测试钉
> - **静默失败面清零**（F-090: telnet halt/reg/read-mem 失败语义 + 烧录判据
>   只信 returncode）
> - **主链补漏**（F-085 成功路径台账漏参 + F-088 失败/重试分支集成测试）
> - **治理基建**（F-084 覆盖率棘轮 38%/F-089 路径扫描钉/F-091 同源收敛/
>   F-093 hooks 探针）+ **已知缺陷白纸黑字**（F-096 hook 漏报/build_has_errors
>   死分支——登记待拍板，不藏）
> - 测试规模: 325 → **478**（+153）; 全量绿（skipped=6 属设计）

## 0.4 — 2026-09-04（质量守门 + 契约统一）

> **本账目与 docs 中引用的"重写前短 hash 全部失效"**——同 0.3 节"开源准备"
> （line 472~480）的声明。本节内容经两轮重写：① 0.3 公开准备 filter-repo
> （脱敏 Windows 用户名+工作区盘符），重写前 commit 图封存于
> `../archive/embedded-toolkit-prehistory-20260901.bundle`；② 0.4 复核前
> 9-02 推送署名 filter-branch（xujiujiu0628 user-identity filter-branch），
> 详见 [[push-user-identity-rule]]。引用本节 hash 前请用
> `git rev-parse --verify <hash>^{commit}` 验证现行可解析；现行 0.4 节
> 16 hash 引用经 F-051 复核 16/16 可解析。

本版主题：**五条守门工具齐备 + runtime_common 共享层抽取 + HIL 入口可追溯**。
50+ commit 兑现路线图 F-035~050 全链 + F-029 整车收口；F-号账目分散于下方
6 段 Unreleased 按发现日期归档（回放粒度优先于合并重排），本节只做导览。

### 五条守门工具

- **HIL 入口可追溯（F-046）**：`release.py gate1` 启用 schedule origin 守卫
  （`--require-schedule-origin`），flash / capture 必经台账。`6561e31`
- **verify 进度台账（F-047）**：checkpoints.jsonl + state.json 双写，早退
  路径不落账 + 落盘扩 step_durations + atomic_write_json 防撕裂。
  `eef1851 / e5852e3 / f850154`
- **fixture doctor（F-048）**：doctor 体检新增 fixture_health 三态判定
  （在场 / 漂移 / 正常），git show main 对比不污染工作树。
  `1231bb6 / 4dad1b2`
- **scripts/ 覆盖缺口 lint（F-049）**：AST 扫 test_*.py import 找未被引用
  scripts 文件，取代行数红线。`c7e2a48 / 7da9b27`
- **分层前时长画像（F-050）**：verify step-level timing 埋点（build /
  flash / capture / rtt 都有 duration_sec） + duration_profile 工具出
  min/p50/p95/max/占比。`35bef57 / c4487b7 / 23103b3`

### 契约统一

- **F-029 runtime_common 共享层**：wb / openocd / serial 三 runtime 22
  个同名符号抽取到 Layer 0.5 共享层（25 规范符号防环），AST 同形重复
  浪费 **195→4 行**；17 工具消费方零迁移，特征钉先按现实绿（`serialize`
  hook 注入保三家分叉、`normalize_path` serial 留份、`save_local_config`
  守卫撤销——整写天然免损）。`17b58f3 / 7b81786 / 98a36f9 / 6d9a898 / 3c2dba6`

### 防腐纪律 + 文档统一

- **F-035** CONTRIBUTING 增「分层与复用 / 先钉后拆 / 契约三件套 / 文档单一
  事实源」四节 + AGENTS.md 工程纪律速查
- **F-036** .gitattributes = `* text=auto eol=lf`（R8 修正：仓本全 LF，
  renormalize 恒 no-op；autocrlf 检出假象定性）
- **F-037** PR 模板补契约三件套自查行
- **F-038** 契约 fixture 入库 `.workbench 最小合法样例进 tests/fixtures/`
- **F-039 / F-040** 真实 fixture 即时抓到 README 示例单数 pattern 非法
- **F-034** README 账目同步：路线图撤下已收口 F-021~F-024 改列 F-031 / F-032
  实况；特性条去写死用例数；效果预览 JSON 加注 0.2 时期实录
- **66ca43f** README 新增 Windows 首次跑测试告警说明（GBK 乱码是 F-020 诚实
  化设计被 Windows 终端解码失败，工具本身 OK）

### 用户署名 + 仓配置

- 用户署名重写 14 commit（`filter-branch` 用户身份统一，详 release notes
  账本说明节）`xujiujiu0628(noreply)`
- 仓内 git config 配上用户身份
- 公开仓元数据：关 is_template / Projects；开 secret_scanning /
  push_protection / dependabot_security_updates（9-04 同期）

### 已知遗留（已登记）

- **F-031** Linux 真机路径整体未验证
- **F-032** serial_mux socat 限制按实情声明
- ESP32 接入立项暂缓（无目标板，路线图决策 esptool + probe-rs 仍有效）

---

## Unreleased — 2026-09-03（分层前时长画像，F-050）

- **F-050（分层前时长画像 / verify step-level timing，feat+test）**: 9-02
  方案四-4。"分层"前**先做时长画像**——不拍脑袋切层，用数据驱动。
  处置=双轨：① verify.py 每个 step 入口加 `t0 = time.time()` 出口写
  `step_info["duration_sec"]`（F-046 旧测试同步兼容——只追加字段）；
  ② 新工具 `scripts/duration_profile.py` 读 `.workbench/state/
  checkpoints.jsonl`（F-047 落盘）+ `result.steps.*.duration_sec` 聚
  合每个 step 的 min/p50/p95/max/sum/占比。`--demo` 跑 mock 数据自检；
  无真机场景下报告**透明标注**"非真机表现"——真机一跑数据自动真实化。
  mock 示意（典型单次真 verify）：**capture 67% 主导、build 21%、flash
  7%、physical_gate 3%、analyze 1%**——给"分层"决策的数据信号：捕获
  独立（占 67%）最大收益，analyze 单独跑不划算（启动开销比它大）。
  `tests/test_duration_profile.py` 14/14 绿（读 jsonl 3 + 聚合 1 + 百
  分位 4 + summarize 2 + CLI 4），全量 **258/258 绿**（skipped=1 仍
  F-026 opt-in）。对你 verify 的影响：每次跑 verify 多记 4 个
  `duration_sec` 字段（追加，向后兼容）；release audit 后续可按
  `checkpoints.jsonl` 看趋势（"最近 N 次 capture p95 涨了 30%"）。

## Unreleased — 2026-09-03（覆盖缺口 lint 取代行数红线，F-049）

- **F-049（scripts/ 覆盖缺口 lint 取代行数红线，feat+test）**: 9-02 方案
  四-3。**仓内此前根本没有"行数红线"——只在 memory 里有方案意图，本
  次按意图真做出工具**。行数是假命题：一个 200 行 const array 和一个
  200 行状态机风险天差地别；工程师为过红线拆文件反而劣化可读性。覆盖
  缺口才是真问题：工程师加新模块忘了给测试加 hook，PC 测试编译过但
  路径没测到，要等真机复现才发现。新工具 `scripts/coverage_lint.py`
  用 AST 扫 `tests/test_*.py` 的 import / from-import，收集所有引用
  的模块名；列 `scripts/` 下"未被任何 test 引用"的 .py 文件：
  ① 默认模式仅报告 (exit 0)；② `--strict` 发现未覆盖 exit 1 (CI 门
  禁用)；③ `--json` 机器可读；④ `legacy/` 目录豁免（F-029 退役 keil
  桥不强制覆盖）；⑤ `coverage_lint.py` 自身豁免（工具自检）。真仓
  实测发现 **13 个未覆盖文件**（cube_to_keil / gen_periph / openocd
  系列 5 个 / serial 系列 6 个）——CI 门禁开了就能早期抓。`test_
  coverage_lint.py` 13/13 绿（AST 解析 6 + 文件配对 4 + CLI 3），
  全量 **257/257 绿**（skipped=1 仍 F-026 opt-in）。对你 review /
  release 流程的影响：新增"覆盖缺口"作为可选门禁（默认不开启），
  行数从此**不再**作为任何 release 判据。

## Unreleased — 2026-09-03（doctor 体检扩 fixture 维度，F-048）

- **F-048（doctor 体检接入 fixture 状态检查，feat+test）**: 9-02 方案四-5
  （P0 余 2 单之一）。当前 doctor 只查工具链（gcc/openocd/make/SWD），
  不查 fixture；fixture 漂移是嵌入式测试最隐蔽的雷（PC 测试 PASS 真
  机挂）。处置=把 `tests/fixtures/contract/` 体检接到 `doctor_report`：
  ① **在场性**：config.json / expectations.json 缺失 → status="fail"；
  ② **漂移检测**：用 sha256 对比本地 vs 仓库 main 版（`git show main:...`
  不污染工作树），漂移 → status="warn" + 列出 mismatches 字段名；
  ③ 状态聚合进 `summary["fixture"]`（与 tools/swd 平级）。`_print_doctor`
  新增 fixtures 行（带 drift / missing 备注）。`fixture_health()` 接
  `skip_drift_check` 参数（测试场景：占位时显式跳过 git 调用，不破
  "占位不跑子进程" 守卫）。`test_doctor.py` 旧 `test_structure_and_
  summary_consistency` 同步加 fixture 计数（向后兼容：fixtures 缺失时
  行为不变）。9/9 新测（`test_fixture_doctor.py`）+ 全量 **253/253
  绿**（skipped=1 仍 F-026 opt-in）。对你 doctor 命令的影响：`--doctor`
  默认开启漂移检测（轻量 git show，秒级），`--doctor --json` 多了
  `fixtures` 字段 + `summary.fixture` 子项。

## Unreleased — 2026-09-03（进度台账，F-047）

- **F-047（verify 进度台账可重放证据，feat+test）**: 9-02 方案四-2。当前
  verify.py 跑出结果只落 feedback_db（校准用），不存 commit 锚点；事后
  无法回答"v1.1.0 tag 之前最后一次 PASS 是哪天哪个 commit"。处置=双写：
  ① `.workbench/state/checkpoints.jsonl` 追加台账（8 字段：ts/git_head/
  git_branch/status/duration_sec/origin/step_keys/contract_hashes，给审计
  链）；② `state.json["last_checkpoint"]` 覆盖（与 jsonl 末行同步，给消费
  方读"上次状态"）。`_git_head()` 隔离 git 调用，失败回空字符串而非抛
  （非 git 工程 / git 不可用）。主流程在 `_log_feedback_event` 之后
  `_output` 之前调一次 `record_checkpoint`；落盘失败不阻断（审计非门禁，
  stderr 告警即可）。**注意：当前 main() 只在正常出口落台账，早退路径
  （build_failed/flash_failed/capture_failed）不落——这是已知覆盖缺口，
  下次按需要补**。`record_checkpoint` / `_git_head` 单元 7 + main 集
  成 1，共 8/8 绿；全量 **252/252 绿**（skipped=1 仍 F-026 opt-in）。
  对 release audit：以后查"某 tag 之前最后一次 PASS"= `grep checkpoints.jsonl`
  + 按 ts/commit 过滤，零人工翻 git log。

## Unreleased — 2026-09-03（HIL 入口可追溯，F-046）

- **F-046（HIL 任务入口可追溯到 schedule/dispatch，feat+test）**: 9-02
  方案四-1。用户拍板 HIL 范围=flash+capture（build 是 PC 端不算，整流水线过
  宽）；默认 `task_origin=manual` 兼容现有 VS Code 直接调子工具（build/flash/
  debug 不走 verify.py，零影响），新增 `--task-origin {manual,schedule,dispatch}`
  与 `--require-schedule-origin` 旗标；开启硬卡时 manual 拒绝并 exit 2（区别
  于 0=成功/1=失败）；每次执行把 origin 写入 `result.steps.{flash,capture}.origin`
  并追加 `.workbench/state/audit.jsonl` 一行 JSON（ts/origin/step/status/command）
  ——台账是审计而非门禁，落盘失败不阻断主流程。`enforce_hil_origin()` + 
  `append_audit_entry()` 单元测试 10 + main 集成测试 3（mock step_flash / 
  _step_capture_rtt 验证守卫真的在 flash 前生效）；全量 **244 全绿**
  （skipped=1 仍 F-026 opt-in 活跳）。对你 VS Code 工作的影响清单：手动
  build/flash/debug 零影响；手动 verify 放行并打 `origin: "manual"` 标记，
  release audit 一眼可辨手动 vs CI 攒的 PASS；CI/release 门禁脚本加
  `--require-schedule-origin` 即可拦截手动跑。

## Unreleased — 2026-09-02（防腐纪律成文 + 换行符策略固化 + 契约 fixture，F-035~040）

- **F-035 登记+处置（成熟纪律仅靠惯例维持，docs only）**: 长期防腐方案三轮源码分析
  判定——本仓不缺防腐机制，缺机制覆盖面与成文化："先钉后拆"（F-029 六 Task 全程
  演练）、"先红后绿"（建仓 fix 一贯执行）、"复用不复制"（runtime_common 已建但
  "脚本自含"惯例未退役，22 同名符号三份存留的根因由其 docstring 自述）、文档单一
  事实源（F-034 亲踩）——全部只靠惯例与 commit message 传承，下一双手（含代管
  智能体）未必接得住。处置=把已兑现实践成文，不引入新流程：
  ① CONTRIBUTING 新增四节「分层与复用」（五层图+三条可机检 import 禁令+脚本自含
  退役+落层决策表）、「行为保持型重构：先钉后拆」、「契约变更三件套」、
  「文档同步（单一事实源）」，「测试与 PR 纪律」补先红后绿与注释 F 编号可追溯条；
  ② AGENTS.md 加「工程纪律速查」（执行侧摘要八行；明令与 CONTRIBUTING 分歧以
  后者为准——成文纪律的同时不制造新的双权威）。无代码改动；全量 **215 全绿**（skipped=1 仍 F-026 opt-in 活跳）。
- **F-036 登记+处置（R8 换行符策略固化，chore，含方案判据修正）**: 方案基线判
  「三态并存、需一次 renormalize」定性有误——`git ls-files --eol` 实证索引区
  94/94 blob 本就统一 LF，三态只是本机 `core.autocrlf=true` 的检出态假象，
  `git add --renormalize` 实为恒零 diff 的 no-op。处置=新增 `.gitattributes`
  （`* text=auto eol=lf`，仓库自身固化"检出恒 LF、入库自动归一"，不再依赖各机
  autocrlf 个人设置；当前零二进制，不预写 binary 规则，未来误判按
  `*.<ext> binary` 逐条补），本地工作树强制重检出收敛 95/95 全 LF。无代码改动；
  换行翻转行为零影响，全量 **215 全绿** 两跑实证（skipped=1 仍 F-026）。
- **F-037 处置（契约三件套进 PR 必经表单，chore）**: F-035 成文的「契约变更
  三件套」只活在 CONTRIBUTING 正文，靠"记得去读"生效；`.github/
  PULL_REQUEST_TEMPLATE.md` 检查清单补一条自查项（同 commit 契约钉 /
  CHANGELOG 契约变更段 / toolkit_min_version 评估，不适用须注明），使规则
  进入每次提 PR 的必经表单——单人项目里"清单即评审"。纯模板文字，零代码；
  全量 **215 全绿**（skipped=1 仍 F-026）。

- **F-038 登记+处置（契约 fixture 入库，test+docs）**: `tests/fixtures/contract/`
  收录 .workbench 契约最小合法样例（config.json + expectations.json），期望条目
  覆盖全部九字段（id/desc/texts/patterns/capture_group/min/max/xfail/xfail_reason），
  test_contract_fixtures 三关验证 —— lint 全绿（唯一 warning=xfail 提示，F-026 口径）/
  loader 能吃（verify.load_config + wb_runtime.load_project_config + load_expectations）/
  四态判定语义（全信号 pass+pass+xpass 且 xpass 强制判红、缺 TODO xfail、低于下限
  fail 带 min 细节）；config 字段另钉与 README 公示值逐键一致。咬合验证：fixture
  min/max 对调 → E9+语义两例红 → 还原 → 绿。schema 演化时 fixture 同步改，diff 即评审点。
- **F-040 登记+处置（README 示例契约非法，docs，fixture 即发现）**: 「5 分钟上手」
  第 2 步示例 FR-ADC-02 用单数 "pattern" 键，而 loader 与 lint 均只认复数 "patterns"
  非空数组（load_expectations "texts 与 patterns 须二选一" 拦截）——照抄示例的用户在
  verify 首步即收到 "期望清单非法"。红证=按示例原样构造实测 loader 拒绝；处置=README
  示例改复数（与 fixture 同形，修后示例块实测 loader 3 条 + lint 零错）+
  test_singular_pattern_key_rejected 钉死单复数差异防回潮。教训归因：契约样例此前
  只在文档里"展示"，从未过 loader/lint 回路 —— F-038 入库回路后当轮即抓到本例。
- **F-041 登记+处置（--doctor 环境预检 + swd_probe 下沉共享层，feat）**: 长期防腐
  方案 §6.1 建议的工具链环境矩阵自检落地——`verify.py --doctor` 打印 toolkit/Python/
  machine.json 四键/gcc/openocd/make/SWD 连通性后退出，报障随 issue 附
  `--doctor --json` 输出，把"环境不同"类无效往返消灭在入口。关键设计：
  ① **swd_probe 从 release.py 私有实现下沉至 openocd_runtime**——发布门禁 G0.5 与
  doctor 共用同一命令与判据，防两处口径再漂移；对象同一性
  （`openocd_runtime.swd_probe is release.swd_probe is verify.swd_probe`）由
  test_doctor 钉死；② **占位路径永不执行**——machine.example.json 的 `<...>` 占位值
  绝不触发子进程（mock 守卫钉死，触发即 AssertionError）；空/占位 → skipped 如实标注；
  ③ doctor 分支先于工程发现，不依赖 .workbench 工程；machine.json 缺失走 load_machine
  回退链并如实标 mode=fallback；④ 退出码恒 0——诊断报告，不是门禁；
  ⑤ 版本行 stdout/stderr 合并取首行（OpenOCD 版本打印在 stderr 的实情）。
  伴随微调：swd_probe attempts 参数化，末次失败不再空转 sleep；doctor 传 1 做单次
  快探、门禁 G0.5 保持 3 次重试（语义不变，test_doctor 双向钉死）。
  实测：本机真 machine.json 三工具 ok、无板时 swd=fail 如实报（非伪装）；全量
  **231 全绿**（skipped=1 仍 F-026 opt-in 活跳）。

## Unreleased — 2026-09-01~02（代管 R3：跨平台回收 + 外围模块补齐入账；次日 F-029 整车收口）

- **F-027 登记+修复（P0，TDD 先红后绿）**: `verify.py::_step_capture_rtt()` 裸用
  `subprocess.CREATE_NEW_PROCESS_GROUP`——该常量仅在 CPython `if _mswindows:` 分支内
  绑定（subprocess.py:80-82 实证），Linux/macOS 上属性访问即 AttributeError；且 README
  「5 分钟上手」第 1 步示例正是 `"backend": "rtt"`，照抄的 Linux 用户首次真机运行必崩。
  默认 semihosting 走内联路径不经过该行，故长期未暴露。仓库其余 4 处同类常量
  （openocd_gdb/itm/semihosting/telnet）全部带守卫——属遗漏，非设计选择。修复=搬既有
  惯用法 `... if sys.platform == "win32" else 0`（提出重试循环外，单次计算）。
  回归钉 `test_platform_guards.py` 静态判据：裸用 Windows-only subprocess 常量须与守卫
  同行（`getattr(subprocess, …, 0)` 形态构造性安全豁免；legacy/ 不入扫描）——修前
  红证仅命中 verify.py:134 单点，修后绿；全量 **183 全绿**（skipped=1 仍为 F-026）。
- **F-028 登记（孤儿代码，待拍板，未动刀）**: `verify.py::step_capture_semihosting()`
  全仓零调用（仅命中定义处），其唯一下游为 `OPENOCD_SEMIHOSTING` 常量（verify.py:46），
  该常量唯一使用点即此死函数（:363）——死链完整终止于 `openocd_semihosting.py`
  （544 行，自带 `__main__` 独立 CLI 形态，未入 README 工具表，零测试覆盖）。实际生效的
  semihosting 是 verify.py 内联实现（:1145 注释自述"不走复杂脚本"）；verify.py:16 头图
  仍写 Capture→openocd_semihosting.py，同属陈旧。
- **F-028 处置（同日拍板，整链删除）**: 维护者选定删除方案——`git rm
  openocd_semihosting.py`（544 行）+ 死函数 `step_capture_semihosting()` + 死常量
  `OPENOCD_SEMIHOSTING`，头图第 4 步改写为"verify.py 内置双路: semihosting 内联 |
  rtt"；RTT 段首两处与内联 semihosting 分支内共三处悬空注释同步收口（末处保留
  "曾有其物，git 史可回放"记号）。删除前后全仓 grep 零代码引用；183 全绿不变。
- **F-030 登记（头图陈旧，维护者拍板下轮顺手修）**: verify.py 头图流程第 1/2 步仍写
  Build→keil_build.py / Analyze→keil_analyze.py——Keil 已于 2026-08-28 退役入 legacy
  （:42-45 实证：默认后端 `builder=gcc`，Keil 桥仅显式配置时按需唤起）。修法=两行
  改写为 GCC 默认 + legacy 桥注记，与 :43 口径一致；随下轮（F-029 契约统一或 F-026
  tempfile 化）顺手刷掉。
- **F-030 处置（同轮提前带走）**: 头图 1/2 步已刷——Build→gcc_build.py（默认，
  builder=keil 显式配置时唤起 legacy 桥）；Analyze→gcc 路径直传 build metrics，
  keil 路径走 legacy 知识库（口径对照 step_analyze 实现）。
- **F-033 处置（收口完成）**: 三分支 `git branch -d` 删除（-d 自带"仅认可已合并"
  保险；删除输出留 8afd8dd/9cadade/0104dcb 三 SHA 供 reflog 回放）。
- **F-029 登记（重复度量化，附限定条件）**: 三份 runtime（wb 379 / openocd 354 /
  serial 515 行）共有 22 个同名符号、三份合计 633 行、相对最大单份冗余 406 行
  （≈430-450 区间下沿，判据=同名符号行数并集）。**非纯复制，是同源分叉**：
  `make_result` serial 侧为 `success: bool` 位置参，wb/ocd 为 keyword-only `status: str`；
  `parameter_context` 三处签名各不相同——机械去重必破坏调用方。且
  test_writeback_guards.py:28 以 `RUNTIMES=[wb, ocd, serial]` 参数化把三形态钉进测试，
  合并时测试须同步改。路线：先统一契约，后谈提取公共模块。
  **计划已交**（`docs/superpowers/plans/2026-09-01-f029-runtime-dedup.md`）：
  AST 两两比对实测重定分桶——5 字节同 / 7 仅 docstring 差 / 4 真分叉含同名异物 /
  4 路径策略 / 2 机制分叉；登记期"serial make_result 契约分叉"经实测修正为
  **入参签名分叉、输出本就 status 同族**（可适配器并轨），`make_timing`/
  `parameter_context` 才是同名异物；另撞出 Windows pre-epoch 时间戳 OSError 边界。
  施工按 6 Task TDD 推进，特征钉先行冻结 wire。
- **F-029 处置（2026-09-02 整车完成，6 Task TDD 全绿）**: 新建共享层
  `scripts/runtime_common.py`（295 行 / 25 规范符号，仅 stdlib、不 import 三 runtime 防环；
  与"路径解析"定位的 `wb_common` 互不渗透），三 runtime 以再导出/薄壳维持 `mod.X`
  调用面，17 个工具消费方零迁移。**AST 净账**（docstring 无关判据）：同名同形重复行
  浪费 **195 → 4**（余 4 行为 wb/serial 序列化钩子薄壳，同形系设计使然）、同名异形
  12 → 6 组全部显式留份 + docstring 钉；runtime 本体规模 wb 391→187、ocd 354→158、
  serial 515→404。**三处订正**（对登记期分桶表）: ① `save_workspace_state`/
  `update_state_entry` 非"纯 docstring 差"——**wb==serial 落盘序列化**（绝对路径→
  workspace 相对 POSIX）、ocd 原样存，是真 wire 语义分叉，以 `serialize` hook 注入保
  三家形态；② serial `normalize_path` 非 wb 版超集（相对输入不 resolve），裁决留本地；
  ③ 计划"ocd/serial save_local_config 补守卫"项**撤销**——环境级配置一 skill 一文件、
  整写不读旧档，天然无损坏丢键风险，守卫缺位系正当设计（裁决钉锁形）。
  **留份判定**: `make_result` 双契约（serial `success:bool` 位置参冻结 + 空 details
  省略/原样透传，薄适配器转调规范版，六 serial 工具输出字节兼容）；`resolve_param`
  三家源标签/层级/normalize 锚定/异常策略不可调和，**整组留三份**——F-029 系契约
  统一而非为去重率强并。配套: `tests/test_runtime_contract.py` 23 例特征钉+裁决钉
  先按现实绿再施工（T1 前置），F-023 pid 用例 patch 目标按计划预案改 `runtime_common.os`
  并记因；随实现搬出收口 STATE/PROJECT 死常量与两处 sys 死导入。全量 **215 全绿**
  （skipped=1 仍 F-026 opt-in 活跳）。
- **F-021/F-022/F-023 处置（原子写收口包，TDD 六签先红后绿）**: 三件同族打包。
  F-021=`wb_runtime.save_local_config` 补 F-020 同款损坏拒写守卫（读改写族；
  openocd/serial 侧同名函数为整写语义不在族内，维持不动）；F-022=新增共享工具
  `wb_common.atomic_write_json`（pid tmp + 强制 LF + 自动建父目录），
  `error_db_grow` 两处与 `release.py` 记录写三处裸 `open('w')+json.dump` 全部并入，
  并落静态防回潮钉（两脚本内 open-w 后 3 行内 json.dump 即违例）；
  F-023=三份 runtime `save_json_file` tmp 名改 `<file>.<pid>.tmp` 杜绝双进程互顶
  （按脚本自含惯例保留三份拷贝，契约统一留 F-029）。新增 5 例，
  全量 **188 全绿**（skipped=1 仍 F-026）。
- **F-024 处置（R7 双布局认路，先红后绿）**: release_audit R7 比对路径由硬编码
  `.workbench/*` 改为 `.workbench`→`.embeddedskills` 顺序双认（首中即停，优先序与
  verify.contract_hashes 的 marker 序一致，杜绝"哈希取 A 路、比对找 B 路"假错位）；
  两布局均未命中才 warn 且消息改为"两布局均不可得"。红证=新例
  `test_embeddedskills_layout_contract_matched` 修前 warn 修后 pass；
  篡改/搬移负例 15/15 无波损。
- **F-031 登记（本轮施工）**: Linux 真机路径整体未验证——F-027 修掉的是"已知崩溃点"
  而非完成验证；README 自述"真机构建路径未验证、欢迎报告"，CI（ubuntu）只跑 mock 套件，
  进程终止/信号/创建标志类平台差异仍属盲区。本轮补 `_step_capture_rtt()` 的
  mock-Popen 平台派发单元钉（Linux 模拟必传 creationflags=0——即 P0 崩溃类），
  真机 Linux 冒烟清单仍留社区/后续。
- **F-031 处置（派发钉落地，咬合验证）**: `RttSpawnFlagsPlatformTests` 两例——
  Linux 模拟断言三试全传 0、win32 模拟断言传真实常量（本机无常量则 skip），
  顺带钉住 3 重试骨架与"进程即死必如实 error"。咬合验证：临时回退 F-027 修法
  → 钉转红 → 还原 → 转绿，verify.py 字节回滚（diff 仅测试文件）。与 F-027
  静态钉成对：属性级 + kwargs 级双层防线。
- **F-032 登记+处置（限制声明，含登记语订正）**: `serial_mux.py` PTY 虚拟串口层硬
  依赖 socat——施工时核实比登记更严重：`which("socat")` 检查在 `start_mux()` 最前
  无条件执行，**无 socat 则整个 mux 起不来**（并非登记初稿所写"另两层不受影响"，
  该不实表述已随本条订正）。错误消息与模块头图同步改为实情：PTY 层 Linux/macOS-only、
  Windows 不支持；"与 PTY 解耦（--no-pty）"列为后续增强，未实现前不按部分功能规划。
- **F-026 处置（冒烟 tempfile 化，同轮提前带走）**: 删除硬编码维护者路径占位符
  （历史重写后已死）；改双段——合成全字段清单（texts/patterns+capture_group+
  min-max/xfail+reason 三条目，钉"xfail 提示是唯一合法 warning"）任何机器任何
  检出恒跑；真档冒烟能力保留为 `ETK_SMOKE_EXPECTATIONS` 环境变量 opt-in（本机
  实测指向 adc-oled 真清单通过，2/2 无跳）。全量 **192 全绿**；skipped=1 语义
  变更：不再是占位符死跳，改为 opt-in 主动跳过。
- **F-033 登记（本轮处置）**: handoff 三分支（zcode-20260830 / zcode-r2-20260830 /
  r2-reconcile-20260831）`git branch --merged master` 全部命中——R2/R3 换回流程遗留，
  去留自 R2 挂账至今。本轮 `git branch -d` 收口删除（-d 自带已并入保险）。
- **F-034 登记+处置（README 账目漂移，docs only）**: README「路线图」仍列
  F-021~F-024 为已知遗留，但四者已分别经 `bd37564`（原子写收口包）与 `66ef73f`
  （R7 双布局认路）处置完毕——该节自述"登记在册，不藏"，却把已修项继续登记为未修，
  且未反映新处置的 F-025~F-033，外部审查者会照单去查已不存在的项。
  处置=撤下已收口四项，改列 **F-031**（部分闭合：Linux 真机路径整体未验证——
  F-027 只修了"已知崩溃点"，进程终止/信号/创建标志类平台差异仍属盲区，已补
  mock-Popen 平台派发钉）与 **F-032**（限制声明：serial_mux PTY 层硬依赖 socat、
  Linux/macOS-only，`--no-pty` 解耦未实现前不按部分功能规划）；多 MCU 方向补前置项
  （interface/target cfg 硬编码 `verify.py` 7 / `release.py` 2 / `hardfault.py` 2 处）。
  另处置两处表述：① 特性条原写"170+ 例"——**违反本仓 CONTRIBUTING「例数以实跑为准，
  勿在文档写死数字」**，且与实际（215）的差距随修复持续拉大，改为不写死数字、
  指向实跑命令；②「效果预览」JSON 的 `"toolkit_version": "0.2"` **保留不改并加注**
  ——该段标注"全文真实可回放"，是 0.2 时期真机实录，改写版本号等于篡改可回放记录，
  与 F-003 归因诚实原则相悖；要反映当前版本须真机重跑整段替换（待有板时进行）。
  全量 **215 全绿**（skipped=1 仍 F-026 opt-in 活跳）。

## Unreleased — 2026-09-01（开源准备：社区门面补全 + 历史脱敏重写）

- **社区门面补全**: 新增 `CODE_OF_CONDUCT.md`（Contributor Covenant 2.1 中译）/
  `SECURITY.md`（私下报告渠道 + 响应时限 + 硬件免责）/
  `.github/PULL_REQUEST_TEMPLATE.md`（对齐 CONTRIBUTING 测试纪律）；
  `.gitignore` 补全标准清单（虚拟环境/依赖/日志/DB/系统/IDE）；README 加
  License/Python/Platform 徽章与「贡献」入口。
- **敏感信息扫描建档**: `SENSITIVE_FINDINGS.md`（15 类凭证模式全零）与
  `OPENSOURCE_READY.md`。
- **历史脱敏重写（git filter-repo × 两轮，决策反转）**: 对 0.3 节
  "不重写 git 历史"的反转——公开前洗清个人 Windows 用户名（27 处，全部
  Users 路径形态，定长 lookbehind 零误伤）与工作区盘符路径（三形态统一
  映射 `<工作区根>`）。**坑（登记）**: `--replace-text` 不作用于 commit/tag
  message，首轮漏 1 处，二轮 `--message-callback`/`--tag-callback` 补齐；
  终验（log -p + 全部 %B + tag contents）零残留。**本账目与 docs 中引用的
  重写前短 hash 全部失效**——重写前完整 commit 图封存于
  `../archive/embedded-toolkit-prehistory-20260901.bundle`，clone 该 bundle
  可按旧 hash 回放全部证据链（0.3 节括号内 hash 均指旧图）。
- **守卫判据适配（重写伴随，本次唯一代码改动）**: `test_failure_hints.py`
  静态守卫的断言目标被重写洗成占位符→恒真失效，改通用盘符判据
  `[A-Za-z]:[\\/]{1,2}(Users|claude)` 恢复"防硬编码回潮"原语义。
- **F-025 存量缺陷登记**: `test_cli_exit_codes_and_json` 在 Windows 非 UTF-8
  控制台失败（子进程 GBK 撞 utf-8 解码）；bundle 基线对照复现 → 与本轮操作
  无关，CI（ubuntu）恒绿。（登记原文留档，修复见下条。）
- **F-025 修复（同日，TDD 先红后绿）**: `expectations_lint.main()` 起手强制
  stdout/stderr UTF-8（惯用法对齐 `verify._output`，stderr 一并——人类模式
  错误报告同为中文）；新增回归钉 `test_json_output_utf8_regardless_of_console`
  将子进程环境强制 `PYTHONIOENCODING=gbk` 仍断言 --json 输出为合法 UTF-8 JSON
  ——修前以同款 0xce 崩溃证红、修后证"随脚本不随环境"；全量套件 **182 全绿**
  （skipped=1 为 F-026）。
- **F-026 联动现状**: `test_expectations_lint.py` 真档冒烟路径字面量随重写
  变占位符，本机亦恒跳过（skipped+1）；tempfile 化已无历史包袱，列下轮。
- **F-5 时间线登记**: Events API 显示仓库曾于 2026-08-26 公开一次（转私时点
  不可考），9/1 复转 Public 与脱敏推送最坏重叠约 20 分钟——低危残留仅入账，
  不向 GitHub support 提 purge（推理见 SENSITIVE_FINDINGS F-5）。
- **v0.3 Release 追加账本说明节**: 维护者 08-31 手写正文保留原文（含已被
  反转的"历史不重写"策略句，不删），文末拼接追加节声明反转、旧 hash 回放
  指引与已知事项索引；description + 10 topics 经 gh 落地。

## 0.3 — 2026-08-31（开源门面，master）

- **machine.json 出库+回退链**: 新克隆无 machine.json 时 `load_machine` 回退
  入库模板 `machine.example.json` 并一次性警告（测试/离线工具直接可跑；占位
  路径被真机用到以自解释 FileNotFoundError 报错，F-011 显式原则）；gcc_build
  局部副本改委托单一实现；machine.json 转本机维护不再入库（1605e92 *(legacy, 9-01 历史重写后失效)*、4e953c4 *(legacy, 9-01 历史重写后失效)*、
  6c32584 *(legacy, 9-01 历史重写后失效)*）。
- **个人路径中性化**: 历史文档 11 处 `C:\Users\<用户名>` 形态清洗为
  `%USERPROFILE%`/`<用户名>` 写法；不重写 git 历史（约 30 个 git show 证据链
  与 v0.2 tag 指向依赖现有 commit 图，理由见 commit body）（399657b *(legacy, 9-01 历史重写后失效)*）。
- **提示去硬编码**: verify 失败现场 agent_hint 随 TOOLKIT_ROOT 推导、gen_periph
  生成物注释改仓相对命令，含 4 例回归与源码静态守卫（23d288f *(legacy, 9-01 历史重写后失效)*）。
- **门面套**: LICENSE(MIT) / requirements.txt(仅串口族 pyserial) /
  GitHub Actions CI(ubuntu × py3.10/3.12，刻意不建 machine.json=陌生人路径
  金丝雀) / CONTRIBUTING + ISSUE_TEMPLATE / README 全文重写。
- Python 下限如实定 **3.10**（verify/hardfault/feedback_db 等使用 PEP 604
  联合类型且无 future import）。套件随门面工作增长，例数以实跑为准。

## 0.2 — 2026-08-30（代管 R2，分支 handoff/zcode-r2-20260830）

- **F-018**（原报告编号 F-015，换回对账重排，见
  `docs/handoff/2026-08-31-r2-reconcile-notes.md`）发布记录绑定契约哈希: verify 输出 `contract_hashes`
  （config/expectations 字节级 sha256），release 写入发布记录，
  release_audit 新增 **R7**（对照 `git show <git_head>:` 重算比对，
  错位=fail，R7 之前旧记录=warn）——关闭"G1 期间改契约再还原"的取证盲区
  （34a96e5 *(legacy, 9-01 历史重写后失效)*）。
- **F-019/F-020**（原报告编号 F-016/F-017，换回对账重排）写回型工具损坏清空家族修复（三份 runtime 拷贝同修）:
  `save_project_config` 损坏**拒绝写回**；`update_state_entry` /
  serial_mux 读改写损坏**隔离 .corrupt 后重建**；`save_json_file` 改
  **原子写**（.tmp + os.replace，杜绝并发撕裂读）；error_db_grow 知识库
  损坏明确拒绝写入；gcc_build config 写回抽 `merge_gcc_config`
  （351e021 *(legacy, 9-01 历史重写后失效)*）。
- 新工具 **expectations_lint.py**（D 项）: verify.load_expectations 规则
  离线化 E1~E9，含 verify 不查的 E9 `min>max` 结构矛盾；两现役工程真档
  冒烟 CLEAN（10507bd *(legacy, 9-01 历史重写后失效)*）。
- **C 项** 零覆盖模块补测 21 例: phase_minus_one / rm_lookup /
  token_stats / svd_to_json（cc54e45 *(legacy, 9-01 历史重写后失效)*）。
- 文档对齐: 本 CHANGELOG 新建；AGENTS.md / HANDOFF-AGENT.md 过期计数
  （47 测试/28 脚本）改为动态表述；HANDOFF-AGENT.md §2 补 #10/#11
  防重报条目。

### 换回对账增补（主控，2026-08-31）

- **外部核查**: fresh-check 无上下文对抗审计判"通过但有保留"（C0/H1/M1/L2，
  落账 fc_20260831_122115+0800）；修复与回归独立复现成立，纪律无违例。
- **High-1 处置**: R2 分支起点偏移确认（父链起点 9997ac2 *(legacy, 9-01 历史重写后失效)* ≠ 宣告基线链）→
  编号重排 F-018/019/020（原编号与 1819e18 *(legacy, 9-01 历史重写后失效)* 冲突）、findings-r2 归因更正、
  §2 勿重做清单合并为 13 行、新工具 hash 重放对照，详见
  `docs/handoff/2026-08-31-r2-reconcile-notes.md`。
- **遗留登记**: F-021 save_local_config 同族漏网 / F-022 三处非原子写 /
  F-023 固定 .tmp 并发尾洞 / F-024 R7 路径盲区（对账记录 §3，第三轮排期）。
- **换回协议升级**: 第 3 步纳入 expectations_lint 两工程秒检（采纳 R2 §六-3
  建议）；§5 上岗规矩新增"先核分支起点"（R2 教训回写）。
- 合入后套件基线 **172**（155∪106，master 净增 17 零丢失）；未跟踪
  .mcp.json（用户确认非本人添加）移出至 archive/mcp-from-toolkit-20260831/。

## 0.1.x — 2026-08-30（代管 R1，分支 handoff/zcode-20260830）
