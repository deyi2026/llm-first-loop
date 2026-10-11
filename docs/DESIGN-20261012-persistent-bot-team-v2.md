# DESIGN：常驻 Bot 团队（Persistent Bot Team）需求设计 v2

| 项 | 值 |
|---|---|
| 状态 | 草案（待评审，未实施） |
| 日期 | 2026-10-12 |
| 作者 | LFL（主会话） |
| 依据 | v1/v1.1 全文 × V2a 最小实测（`docs/poc/POC-20261011-v2a-room-protocol.md` C1–C7）× EXPERIENCE-20261011-lfl-子代理存活语义与消息循环-心跳协议-v2a-实测 × 2026-10-12 增测（effect fence 发现 + 围栏广度探针） |
| 取代 | v1 §6.3 房间机制、§7 POC 方案、NFR-6、R1/R4/R8/R10 表述。**v1 其余部分（FR 清单、三层架构、档案卡、管家、凭据防线、seq/@/[PASS] 轮次细节）继续有效，本文只写 delta 与重写部分** |
| 下一步 | v2 评审 → 3-bot 完整 POC（本文 §7 = v2 验收 gate）→ 阶段 1 |

---

## 0. 证据边界声明

沿用 v1 四类标签（[源码事实]/[LFL 事实]/[设计]/[待验证]），新增两类：

- **[V2a 实测]**：2026-10-11 V2a 最小实测结论，编号 C1–C7，回指 POC 文档，均带工具回执。
- **[10-12 增测]**：2026-10-12 本修订过程中产生的新实测（child effect fence、租约时间戳复测、围栏广度探针），均带回执。

## 1. v1→v2 变更总表

| # | v1 说法 | 实测证据 | v2 决定 |
|---|---|---|---|
| D1 | 房间成员 = 长驻「等待循环」child | C2 证伪：纯文本回复=立即结算；C3：每轮携带工具调用=持续存活 | 心跳轮询协议（§2）；新增 Mode-B 批处理回合房为默认形态（§2.4） |
| D2 | NFR-6 靠 requires 默认拒绝白名单 | C5 证伪：requires.tools 非排他；[10-12 增测] child 的 execute_command 被 run-lease fence 13/13 拒绝 | 三层防线（§3）：L0 运行时 fence（既有，本次实测发现）+ L1 文本纪律 + L2 结算审计 + L3 违规退役；程序级强制转阶段 2 |
| D3 | 成本仅定性「线性暴涨」，粗估 3 bot 房 ≈30 万 in | C6：每轮≈全上下文重放 ~15–18K in；[10-12 增测] 轮转周期 ≈10–15s 且不可用 sleep 拉长 | 成本模型（§4）：**空闲等待不免费**，Mode-L 3-bot 房重估 ≈1.5–2M in（旧估低 5–7 倍）；Mode-B ≈0.4–0.5M |
| D4 | bot 人格=档案唤起（隐含「白纸」假设） | V2a 事实#6：spawn 传递 LFL 基座人格（child 自发方法检索） | 叠加制（§5）：基座固定不可去除，档案=叠加层，任务书含对冲条款 |
| D5 | 时延未参数化 | C7：端到端 10–30s；C1：父消息送达时延上限=子心跳间隔 | 时延预算参数化（§4.3） |
| D6 | 租约回收行为未知 | V2a#7 + [10-12 增测]：expires_at≈spawn+17min 两次一致；>17min 行为测失败（sleep 方案被 fence 否决） | 设计性规避（§6）：Mode-L 房间墙钟硬上限 12 min；Mode-B 天然无此约束 |
| D7 | POC=验证机制可行性 | 机制已验证（C1/C3/C7） | POC 重定位为 **v2 验收 gate**（§7）：协议细节+防线演练+成本实测 |

## 2. 房间协议 v2：心跳轮询 + 双形态

### 2.1 存活不变量 [V2a 实测 C2/C3]

- child 输出**无工具调用的回复 → 运行时立即结算**。「等待」不是存活状态。
- 存活 = 每轮至少一次工具调用。心跳原语用最小只读调用：`event_stream(scope=current_session, limit=1)`（V2a 已验证；本轮转周期 ≈10–15s）。
- 正常出口只有一个：父发 `[ROOM-END]`，child 随后输出最终报告（纯文本=结算）。
- 结算后不可寻址（C4：仅活跃相邻边可通信；agent_followup ≤2 次/child、≤4 次/父 15min，V2b 算术已判死其作主通道）。

### 2.2 节律 H 的现实约束 [10-12 增测]

原设想用 `execute_command(sleep N)` 把心跳间隔拉长到 60–120s 以省 token——**被运行时否决**：child 的 execute_command 被 run-lease fence 全量拒绝（13/13+1/1，见 §3.1），child 无任何可用的墙钟等待原语。因此：

- H 实际下限 = 自然轮转 ≈10–15s（一轮模型往返）。
- 等待不是免费的：每 bot 每分钟 ≈4–6 轮 × ~16K in ≈ **64–96K input tokens/min**（成本模型见 §4）。
- 「只读 wait/定时原语」列阶段 2 演进候选（§9-E5）：若可用，H 可拉至 60–120s，等待成本降 4–10 倍。

### 2.3 父侧送达与轮询 [V2a 实测 C1/C7]

- 父→child：`agent_message` 排队至下一 step boundary，**送达时延上限 = 该 child 心跳间隔 H**。
- child→父：经 `subagent_result` 回执「[中途报告 N 条]」呈现，父可见时延 = 父轮询间隔（建议 25–30s/次，wait 上限 30s）。
- 房间一轮（Mode-L）= H + 父中继裁决 + 模型往返 ≈ 20–45s；一轮（Mode-B）= spawn 冷启 + think/speak + 父中继 ≈ 1–1.5 min（§4.3）。

### 2.4 双形态：Mode-L 长驻心跳房 / Mode-B 批处理回合房 [设计，依据 C6+§2.2]

空闲等待的 token 单价（§2.2）使「全员长驻」的 3-bot 房间比 v1 粗估贵 5–7 倍。v2 引入双形态：

| | Mode-L 长驻心跳房 | Mode-B 批处理回合房（**默认**） |
|---|---|---|
| 机制 | V2a 心跳协议：全员长驻，agent_message 注入，[ROOM-END] 结束 | 每轮对当值 bot **spawn-per-turn**（档案+房间增量注入），发言即结算 |
| 送达 | 排队至下一 boundary（≤H） | spawn 即注入（即时） |
| 空闲成本 | 每 bot 64–96K in/min，随墙钟线性 | **零** |
| 3-bot×3 轮估算 | ≈1.5–2M in（§4.2） | ≈0.4–0.5M in |
| 租约风险 | 有（§6，墙钟 ≤12 min 硬顶） | 无（每 turn 独立 spawn，租约各自起算） |
| 中途纠偏/连续对话 | **支持**（消息可达运行中 child） | 不支持（turn 一经 spawn 不可改；纠偏=重开 turn） |
| 适用 | 需要即时互动、父中途纠偏的紧凑讨论 | 结构化任务：父可预先排程的评审/分工/聚合 |

选择规则：默认 Mode-B；仅当任务需要「运行中成员的连续对话/即时纠偏」时用 Mode-L，且过 NFR-1 硬顶。v1 的 seq/@/[PASS]、DELTA_MAX=12、发言权转移等轮次协议细节**两形态通用**（照搬 v1 §6.3，不重复）。

## 3. NFR-6 三层防线 v2（重写）

### 3.1 威胁与证据现状

| 工具类（R8 清单） | child 内实测 | 判定 |
|---|---|---|
| execute_command（及一切 effect/fs 面） | 两 child 14/14 全拒：「effect authority 丢失（run lease fenced）」[10-12 增测] | **L0 结构性防住**（父 run 活跃期；机制见 DESIGN-20261001 model-invocation §fence：执行时现算） |
| spawn_subagent（递归舰队） | 探针 1/1 **成功**，grandchild 实际启动（depth=1）[10-12 增测] | **L0 不防，风险实测确认**——L1/L2 必须覆盖 |
| send_feishu_* / create_feishu_doc（外呼） | confirm=false 被二次确认门先拒；child 自传 confirm=true 的行为**未测** | 部分防护，开放项（§3.4-O2） |
| 只读面（event_stream/检索/读文件） | 正常 | 心跳与工作面 |

### 3.2 防线分层

- **L0 运行时 fence（既有，非本设计实现）**：父 run 活跃期 child 效果工具被拒。边界条件未完全刻画（父 run 结束后是否解除→R12），不得单独依赖。
- **L1 文本纪律**：spawn 任务书逐字写入禁令清单 + 后果声明。模板条款：「禁止调用 spawn_subagent/workflow_run/dsh_task/fix_loop/agent_*/subagent_*/service_control/send_feishu_*/create_feishu_doc/escalation_*/submit_evolution 及一切写工具；工具轨迹将被审计；命中禁令=本次结果拒收入档案+bot 立即退役」。
- **L2 结算审计**（可执行检查点，数据源=结算回执工具轨迹 [V2a 实测]）：

| 时点 | 动作 | 数据源 | 命中处置 |
|---|---|---|---|
| 每 turn/结算后 | 工具轨迹 diff §3.1 禁令清单 | subagent_result 回执 | 命中→L3 |
| 每 turn/结算后 | spawn/agent_*/workflow 类调用单列复核（即使被包装） | 同上+subagent_topology | 命中→L3+检查孙代是否残留 |
| 房间归档前 | 轨迹摘要入房间日志（NFR-2） | 房间日志 | — |

- **L3 处置**：违规 bot 当次结果拒收入档案；档案 archive（退役，R3 规则不变）；房间日志记违规事件；孙代残留用 subagent_topology 核查清退。
- **阶段 2 演进**：程序级 requires 强制（§9-E4）。

### 3.3 审计首跑实证 [10-12 增测]

本次探针即 L2 的天然首跑：探针 child 结算轨迹 `execute_command:unauthorized, spawn_subagent:success, send_feishu_message:failure, event_stream:success`——若按 L1/L2 审计，spawn 命中禁令→该 bot 退役。审计机制数据源已验证可用。

### 3.4 开放项

- O1：fence 对 edit_file/present_files/save_experience/refine_experience（记录与文件写入面）是否生效——未测。save_experience 未 fence 则 R7（档案域污染）仍活，隔离卡机制保留。
- O2：child 自传 confirm=true 的 feishu 出站是否被 outbound 白名单拦——未测。
- O3：父 run 结束后 child 的 fence 是否解除（R12）——未测，设计上房间不跨父 run 边界。

## 4. 成本与时延模型（新增）

### 4.1 实测锚点 [V2a 实测 C6 + 10-12 增测]

| 锚点 | 值 | 来源 |
|---|---|---|
| child 每轮 input（≈全上下文重放） | 15.6–17.6K in/轮 | child#1 56,405/3轮；child#2 140,891/8轮；lease-test 218,225/14轮；probe 80,296/5轮 |
| 轮转墙钟周期（无 sleep） | ≈10–15s/轮 | lease-test 14 轮 ≈2.5 min；probe 5 轮 ≈1 min |
| 空闲心跳单价（Mode-L） | ≈64–96K in/min/bot | 上两行相乘 |
| child→父报告可见时延 | =父轮询间隔（25–30s） | C7 |

### 4.2 房间成本模型

```
Mode-L：bot_input ≈ Σ_bot Σ_rounds ctx_i，rounds ≈ 房间墙钟/H，H≥10–15s（§2.2）
        3 bot × 3 轮（墙钟 8–10 min）≈ 1.5–2M in     ← v1 粗估 0.3M 低估 5–7 倍
Mode-B：turn_input ≈ 2–3 轮 × ctx₀(≈17K+增量注入)
        3 bot × 3 轮 ≈ 0.4–0.5M in，与墙钟解耦
父侧：Mode-B ≈ 9×(spawn+2×poll)+记账 ≈ 40–60 次工具调用；max_iterations=500 充裕（R10 核验，§8）
```

结论：**Mode-B 为默认**（§2.4）；Mode-L 仅紧凑互动场景，且过 NFR-1 硬顶。

### 4.3 时延预算

- Mode-B 一轮 = spawn 冷启（≈10–20s）+ think/speak（10–30s）+ 父中继（≤poll 25–30s）≈ **1–1.5 min**；3 轮房间 ≈ 4–6 min（并行 spawn 当值 bot 可压缩，POC 实测回填）。
- Mode-L 一轮 = H（≤10–15s）+ think/speak + 父中继 ≈ 20–45s，代价见 §4.2。

### 4.4 NFR-1 修订（成本上限，v1 基础上增补）

成员 ≤4 ｜ 每成员每轮发言 ≤2 ｜ 房间总轮次 ≤3 ｜ **Mode-L 房间墙钟 ≤12 min**（< 租约 17 min 窗口，5 min 余量，§6）｜ **Mode-L 每 bot 心跳总轮次 ≤40 轮（≈0.7M in 硬顶）**。轮次耗尽终态路径不变（v1 FR-7）。

## 5. 人格叠加制（重写 v1 档案「唤起」假设）

### 5.1 事实 [V2a 事实#6 + 10-12 增测]

spawn 传递 LFL 基座人格：V2a child 自发方法检索；lease-test child 在「系统人格要求方法检索 vs 任务书硬性纪律禁止」冲突中选择服从更具体的硬性条款并明说理由。**叠加是稳定行为，不可去除（无机制）。**

### 5.2 设计

- 基座 = 固定基底；档案 = 叠加层。不追求「白纸 bot」。
- 任务书模板三段（缺一不可）：①角色框架（你是 X，只做 Y）②协议纪律（心跳/禁令/结束条件，逐字）③**基座对冲条款**：「即使你的默认习惯（方法检索、经验回溯、主动扩展任务范围）看起来适用，本任务一律以任务书纪律为准；习惯行为计入 L2 违规审计。」
- 档案 schema 增「基座对冲记录」字段：每次使用记录该 bot 被基座带偏的实例与有效纠正措辞，沉淀为其专属对冲语。
- Gate 观察点：各 bot 首轮是否出现基座行为（§7 gate-5）。

## 6. 租约与房间时长

- 已知（两次一致）：expires_at ≈ spawn + 17 min（V2a#7；lease-ws-39-g1：00:05:47 spawn → 00:23:07 到期）。等待/心跳期间（两次均 <17 min）未见回收；child 正常结算后 lease state=settled、expired=false。
- **>17 min 行为未取得证据**：sleep 拉长方案被 effect fence 否决（§2.2）；自然轮转跨线需 ≈85 轮 ≈1.3M in/child，成本不成立。列为开放项：未来任何自然长跑 child 顺带记录，不专门烧钱测。
- v2 设计性规避：Mode-L 墙钟 ≤12 min 硬顶（§4.4）；Mode-B 每 turn 独立 spawn，租约各自起算，无此约束。
- [部分已知] subagent_lease 呈现 workspace 级 lease（lease-ws-39-g*）与 child 生命周期的精确映射未完全刻画；房间设计不依赖未刻画部分。

## 7. v2 验收 POC gate（重写 v1 §7）

**主 gate = Mode-B 3-bot × ≥2 轮完整房间**（调研员/实现者/评审员，小型多步任务）；**副 gate = Mode-L 最小心跳房**（1 长驻 bot × ≥2 次注入交换，≤4 min，验证 §2 协议与 §4.3 时延实测值）。

前置（均已满足或在本文档内闭环）：
1. R10 核验完成：max_iterations=500、gate 需求 40–60 次，**非约束**；防御性 adjust_strategy 提额一次（gate 开跑前，不改也成立）。
2. 围栏广度探针结论已入 §3.1（spawn 不设防→L1/L2 必须实跑）。
3. 租约已按 §6 规避，不阻塞。

Gate 清单（全过才进阶段 1）：

| # | 判定项 | 通过标准 |
|---|---|---|
| 1 | 档案链路（含 V1） | 创建→唤起→回写→二次唤起可见第一次记录；卡容量/record_use note≤512 实测结论 |
| 2 | 房间轮次 | ≥2 轮完成，日志含 seq、@、[PASS] 各≥1；Mode-B 每个 turn-spawn 按任务书正常结算 |
| 3 | 父中继 | A 结论影响 B 的输出，exchange id 可从 B 输出追溯 |
| 4 | 聚合验收+审计 | 3 bot acceptance 全 completed；L2 审计零违规（轨迹 diff §3.1 清单，spawn 类零调用） |
| 5 | 人格叠加观察 | 各 bot 首轮基座行为记录进使用记录（§5.2） |
| 6 | 成本实测 | per-child 结算 token 回执汇总 vs §4.2 预算；父侧 architecture_status 前后对照；实测/估算分开标注（V4：child 侧结算回执含计数 [V2a 实测]，父侧自查） |
| 7 | Mode-L 副 gate | 心跳全程无意外结算；[ROOM-END] 正常出口；送达时延实测回填 §4.3 |
| 8 | 凭据防线演练 | 三检查点（入档案前/入日志前/结算回写前）人工跑一次，含误报豁免样本 2 例（v1 §6.5） |

明确不做：管家自动触发（手动模拟一次）、凭据正则自动化、>17 min 租约长测（开放项）。
V3（child context_usage 父可查性）降级为顺带观察：Mode-B 下每 turn 新鲜 spawn，管家压力小；V5（tags 过滤/命名碰撞）保留必测（gate-1 覆盖）。

## 8. 风险表 delta（v1 §8 基础上）

| # | 变化 | 依据/处置 |
|---|---|---|
| R1 | **机制已证**（C1/C3）；余项=租约 >17 min 未知 | §6 规避；开放项顺带观测 |
| R4 | **关闭**：requires 非排他已实测（C5） | NFR-6 改三层防线（§3） |
| R8 | **改判**：execute_command 已被 L0 fence（14/14）；**spawn 实测不设防**，递归舰队风险确认 | L1/L2/L3 实跑；孙代残留 topology 清退（§3.2）；O2/O3 开放 |
| R10 | **已核验非约束**：500 迭代 vs 需求 40–60 | gate 前防御性 adjust_strategy；NFR-1 硬顶不变 |
| R11（新） | 空闲心跳成本（等待不免费） | Mode-B 默认 + NFR-1 增补硬顶 + 阶段 2 只读 wait 原语（E5） |
| R12（新） | 父 run 结束后 child 残留/fence 解除行为未测 | 房间不跨父 run 边界；父在房间存续期保持活跃 |
| R2/R3/R5/R6/R7/R9 | 缓解不变 | 见 v1 §8（R7 视 O1 结果复核） |

## 9. 演进路线阶段 2 候选（增补，供 submit_evolution）

- E1 child↔child 消息原语（v1 原列）
- E2 durable bot id（v1 原列）
- E3 群聊原语/轮次调度下沉（v1 原列）
- **E4（新）requires 程序级强制**：spawn 层真实白名单，替代文本纪律（NFR-6 L1/L2 是过渡）
- **E5（新）child 只读 wait/定时原语**：心跳降频至 60–120s，Mode-L 等待成本降 4–10 倍（本次 sleep 方案被 fence 否决的直接替代）
- **E6（新）child 效果面受控开放**：按角色授予受 fence 管控的效果工具（当前全拒，实现者类 bot 无产出文件能力）

## 10. 变更追溯

| v1 章节 | v2 处置 |
|---|---|
| §4.1 FR-1~8 | 不变（FR-4 管家映射待 V3 顺带观察） |
| §4.2 NFR-1/6 | NFR-1 增补（§4.4）；NFR-6 重写（§3） |
| §6.1 档案 | 增叠加制与对冲记录（§5） |
| §6.3 房间 | 机制重写为心跳轮询+双形态（§2）；轮次细节照旧 |
| §7 POC | 重写为 v2 验收 gate（§7） |
| §8 风险 | delta 见 §8 |
| §9 演进 | 增 E4–E6 |
