# D13（2026-10-13）事实出处台账

稿件：`docs/promotion/20261013-lfl-daily-13.md`
配图：`img/fig39-heartbeat-protocol.png`、`img/fig40-heartbeat-cost.png`

规则：每条关键论断 → 确切文件 + 行号。所有数据均为单仓库同环境实测，不外推。

| # | 稿件论断 | 出处 |
|---|---|---|
| 1 | 「只输出纯文本、不带任何工具调用的子代理，运行时立刻判定它已完成」 | `docs/poc/POC-20261011-v2a-room-protocol.md` C2「原方案证伪」；对照组实测：child 声称进入等待循环后运行时立即结算 completed（rounds=3, tools=5） |
| 2 | 「56,405 input / 5,930 output tokens」 | 同上 C6 + 实测 1 时间线（child_6d59611d9806） |
| 3 | 「8 轮，140,891 in / 4,339 out，全程 running」 | 同上 C6（child#2 心跳型，8 rounds） |
| 4 | 「结算后发消息是确定性拒绝，不是排队」 | 同上 C4（相邻边存活校验）；实测 1 复测记录 |
| 5 | 心跳协议措辞「每轮以工具调用结束，纯文本结束=违规结算」 | `docs/poc/POC-20261012-v2-gate.md` §二 D-HB-1（抽象指令不被内化，#4 失败→#5 成功） |
| 6 | 「event_stream 是最便宜的只读心跳工具」 | 同上 `docs/poc/POC-20261011-v2a-room-protocol.md` 修正建议 3 |
| 7 | 「父代理按 25–30 秒节奏轮询」 | 同上 C7 |
| 8 | 端到端时延 10–40s | `docs/poc/POC-20261012-v2-gate.md` §三「注入时延：实测 10–40s」 |
| 9 | 心跳空转 ≈130K input/分钟 | 同上 §三「心跳空转 ≈130K in/min 坐实（#5 房 2.5min/323K）」 |
| 10 | 心跳每轮 ≈17.6K input（全上下文重放） | `docs/poc/POC-20261011-v2a-room-protocol.md` C6 |
| 11 | 3-bot×3 轮房间 bot 侧 ≈30 万级 input | 同上 C6 |
| 12 | requires.tools 不是排他白名单 | 同上 C5（child 上下文可见全量工具，含 spawn_subagent/service_control/send_feishu/execute_command/escalation） |
| 13 | followup 配额：每 bot 2 次 / 父会话 15min 窗口 4 次 | 工具 schema `agent_followup` 描述；实测耗尽见 `docs/poc/POC-20261012-v2-gate.md` §二 D-FU-1「父会话配额 19/4 已耗尽」 |
| 14 | 子代理 output 16,000 tokens 硬顶 | 同上 §二 D-OUT-1 |
| 15 | 补遗发言 = 同成员轮内第 2 次 spawn | 同上 §二 D-OUT-1 |
| 16 | 语义检索同族卡互相挤压（0/3 精确命中、错卡 3/3 置顶） | 同上 §二 D-V5-1 |
| 17 | 心跳房实测：18 次心跳 + 双注入，2.5min 收尾，出口正常 | 同上 §一 Gate 7「Mode-L 心跳房 PASS（第 2 次尝试）」+ §二 D-HB-1 |
| 18 | 回合制单轮 0.5–1.5min（轻）～8.5min（重） | 同上 §三「Mode-B 单 turn 0.5–1.5min（轻任务）～8.5min（修订类重任务）」 |
| 19 | 版本 v0.6.32 | `CHANGELOG.md` v0.6.32 条目 |
| 20 | 「证伪条目比成立还多」的四项 | C2 / C4 / C5 证伪 + D-HB-1 抽象禁令证伪 |

## 明确未外推/边界声明
- 成本与时延为 llm-first-loop 单仓库、3 bot 规模、2026-10-11~12 实测，非通用基准。
- 「任务型房间默认回合制」是本系统内部决策，不是普适结论。
- 稿件未声称心跳协议已上生产：v2 设计文档状态为「阶段 1 实施基线」，E4/E5 演进提案仍 pending_review。
