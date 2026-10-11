# POC 实测记录：V2a 房间消息循环机制（2026-10-11）

分支：`poc/v2a-room-protocol` ｜ 对应设计：`docs/DESIGN-20261011-persistent-bot-team-v1.md` §6.3 [待验证] V2a/V2b、§7 POC、R4/R8/R10
状态：**V2a 最小实测完成，结论=机制成立（需心跳修正）**

## 结论速览

| # | 判定 | 结论 |
|---|---|---|
| C1 | V2a 消息机制 | ✅ **成立（修正版）**：parent→child 中途送达（排队至下一 step boundary）；child→parent 经 `subagent_result` 中途报告通道可见 |
| C2 | V2a 长驻等待 | ❌ **原方案证伪**：child 输出无工具调用的回复=立即结算；「空手等待」不是存活状态 |
| C3 | 心跳修正协议 | ✅ **实测通过**：每轮必带只读工具调用（event_stream 心跳）→ child 发 ECHO 后保持 running，直至 [ROOM-END] 才结算 |
| C4 | 结算后寻址 | ❌ 确定性拒绝：「仅允许与直接、仍活跃的 parent/child 相邻边通信」→ 结算后唯一续命=agent_followup（V2b 算术已判死其作主通道） |
| C5 | R4 requires 白名单 | ❌ **证伪**：requires.tools 非排他白名单，child 上下文可见几乎全量工具（含 spawn_subagent/service_control/send_feishu/execute_command/escalation）。NFR-6 在 spawn 层**不可强制**，当前只是 task 文本纪律 |
| C6 | V4 成本锚点 | 实测：child#1（3 rounds 无心跳）56,405 in / 5,930 out；child#2（8 rounds 心跳）140,891 in / 4,339 out。心跳每轮≈全上下文重放（~17.6K/轮）。3 bot × 3 轮房间仅 bot 侧粗估 ≈30 万级 input tokens（不含父代理编排侧） |
| C7 | 时延 | 端到端 ≈10–30s 量级，由父轮询节奏（subagent_result wait 25–30s）与 child 心跳间隔共同决定 |

## 实测 1：等待型 child（对照组，预期证伪）

- child：`subagent_6d59611d9806`，inherit=false，requires.tools=[agent_message]（事实证明不排他）
- 时间线：spawn ~23:53 → ROOM-READY 浮出（经中途报告）→ PING-1 排队 23:55:14 → `ECHO seq=1` 回传 → child 声称「进入等待循环，不再调用工具」→ **运行时立即结算 completed**（rounds=3, tools=5, 56,405/5,930 tok）
- 结算后 agent_message 复测：确定性拒绝（C4 证据）

## 实测 2：心跳型 child（修正协议）

- child：`subagent_6b09babbda99`，task 要求「每条回复必须携带下一次心跳工具调用，纯文本回复=死亡」
- 完整消息循环：ROOM-READY heartbeat → PING-2 → `ECHO seq=1`（child 保持 running ✅）→ `[ROOM-END]` → `ECHO seq=2` → 正常结算
- 结算：rounds=8, tools=8, 140,891/4,339 tok；心跳 event_stream×3（23:57:41/47/50）；全程 21s 活跃，未触发 180s 兜底
- child 结算报告含：父消息清单、心跳次数、可用工具清单、时间顺序——acceptance 四条全满足

## 机制事实清单（均带工具回执）

1. `agent_message` → running child：回执「已排队到直接 child 的下一 step boundary」（非即时中断）
2. child → parent：非会话注入；经 `subagent_result` 回执 `[中途报告 N 条]` 呈现
3. 无工具调用的 child 回复 = 结算完成（child#1 亲证）
4. 结算后 agent_message 拒绝（C4 原文如上）
5. child 可自行经 event_stream 发现自身/父 session id；child#2 报告「直接 parent: 179b3184-…」
6. child 会自发执行 search_records 方法检索（LFL 系统人格随 spawn 传递给 child，bot 非白纸——档案「人格唤起」实为叠加人格）
7. 租约：spawn 后 subagent_lease 显示 active、expires_at ≈ 启动+约 17 分钟；等待期未观察到回收（本实测时长不足，长测未做）
8. 父预算：39 轮/ratio 0.188/max_iterations=500，最小实测无需 adjust_strategy 提额

## 对设计 v2 的修订要求

1. §6.3 房间协议：「等待循环」全部改写为「心跳轮询」；心跳工具选型（event_stream 最便宜只读）+ 心跳频率=父→child 送达时延上限；[ROOM-END] 前 child 不得输出无工具回复
2. NFR-6：白名单不可由 requires 强制 → 改为「task 文本纪律 + 房间日志审计 child 工具轨迹（结算回执已含）+ 违规即退役」；阶段 2 提交 submit_evolution 请求程序级 requires 强制
3. FR-4/R2：心跳每轮全上下文重放的成本（C6）使「长房间」昂贵——轮次上限 NFR-1 从缓解变硬约束；成本模型进 v2
4. bot 人格：承认 spawn= LFL 基座人格+任务叠加，档案隔离卡设计需评估叠加效应
5. 时延预算：房间一轮 = 父 poll 间隔 + child 心跳间隔 + 模型往返，v2 需给出实测参数

## 未测项（阶段 0 剩余）

- V1（档案全链路）、V3（child context_usage 父可查性）、V5（tags 过滤）未测
- V2b 附带：心跳 child 超过租约 expires_at（~17 分钟）是否被回收——需 >17min 长测
- 多 child 并发房间（3 bot × 3 轮）与 [PASS]/@/seq 协议细节、凭据防线三检查点——属完整 POC gate 2/3，本轮仅机制验证

## 2026-10-12 增补：租约长测尝试失败 + effect fence 发现（均带工具回执）

- **目的与方法**：测心跳 child 跨 expires_at(≈spawn+17min) 的回收行为，计划用 `execute_command(sleep 95)` 拉长心跳节律。**方法被运行时否决**，原问题未取得证据。
- **新事实1 [实测]**：child 的 execute_command 全量被拒，原文「effect authority 丢失（run lease fenced），命令拒绝执行」——lease-test child（subagent_d8257ebc4cc3）13/13，probe child（subagent_45a7fc9a569e）1/1。父 run 活跃期间 child 无效果面。机制出处：`DESIGN-20261001-model-invocation-history-replay-safety.md`（effect-authority fence 执行时现算）。
- **新事实2 [实测·围栏广度探针]**：execute_command=fenced；**spawn_subagent=成功**（grandchild subagent_a06862b57716 实际启动 depth=1，任务为即输出即结算；祖父级无 handle 读权「仅直接 parent 可以读取该 child handle」，topology active_children=none 无残留）；send_feishu_message=被 confirm=false 二次确认门先拒（child 自传 confirm=true 的行为**未测**，开放项）；event_stream=正常。
- **新事实3 [实测]**：租约时间戳复测：spawn 00:05:47 → lease expires_at 00:23:07（≈+17.3 min），与 V2a 事实#7 一致；child 正常结算后 lease state=settled、expired=false。
- **新事实4 [实测]**：child 无墙钟等待原语 → 心跳自然轮转 ≈10–15s/轮（lease-test 14 轮 218,225 in；probe 5 轮 80,296 in），等待成本 ≈64–96K in/min/bot。
- **处置**：>17min 行为改为设计性规避（Mode-L 房间墙钟 ≤12 min 硬顶），结论与双形态设计见 `DESIGN-20261012-persistent-bot-team-v2.md` §2/§4/§6。
