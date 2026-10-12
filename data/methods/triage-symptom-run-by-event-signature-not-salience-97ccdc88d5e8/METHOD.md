---
method_id: triage-symptom-run-by-event-signature-not-salience-97ccdc88d5e8
name: triage-symptom-run-by-event-signature-not-salience
description: 用户以行为症状（打转/重复/卡住）投诉一个多 session 并发运行的系统、且存在多个候选 event log / active run lock 时，不要按显著性（日志最大、最新写入、持锁）选定排查对象。先对每个持锁候选做一次机械症状签名普查（最近事件类型计数 + 同工具/同归一化参数的重复调用计数）：签名命中者为目标，签名缺席即排除，不为其构建叙事。本集先按显著性押注 2dced6b3 并展开'慢速打转'叙事，第5步才用'零次 tool.execute'自我纠正，实际打转者是 9a7c8ffd。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:547:f023388059d4d53f0172
evidence_refs: learning:learn:90409ca9bc02
created_at: 2026-10-11T18:26:12.386952+08:00
updated_at: 2026-10-11T18:26:12.386952+08:00
---
## Trigger
用户报告某运行中系统的行为症状（如'被截断后在打转重复'），同时存在多个候选 session/run（多个 event log 或 run lock），且投诉中无显式 session 指针。

## Discriminator
症状的机械签名是可计数的日志事实：'打转/重复'必然表现为同工具+同归一化参数的重复调用事件。本集第2-3步输出已显示 2dced6b3 在 16:40 后仅 4 次 provider 调用、零次 tool.execute——工具重复叙事所需事件缺席即排除该候选；而 9a7c8ffd 存在同一 toutiao URL 的连续重复 web_fetch。该排除事实当时已可见，却在第5步才被当作纠正依据。

## Short path
- 列出候选 event log 与 run lock（未知量：哪个 run 在打转）
- 对每个持锁候选一次性统计最近事件类型分布与同参重复调用数（未知量：谁携带症状签名）→ 签名缺席者直接排除，不投入叙事
- 在命中者上读 provider 请求字符走势、conversation_id 连续性、rollover 原因（未知量：为何重复）→ 99.8k 平台期后塌回 46,303 + 67 segments/72 exchanges = 每轮新会话、截断切掉失败回执与纪律文本，重复源于失忆
- 读 run.end/outcome 事件（未知量：还在转吗）→ cancel_reason=user_stop，先修正'仍在转'的旧说法再给结论
- 产出带证据链的修正诊断与护栏建议，停止

## Stop conditions
- 已定位带重复签名 的候选，且其根因（截断点/滚动策略）有日志直接证据（chars 悬崖、每轮新 conversation_id）
- run 终态已由权威事件（run.end + cancel_reason）确认，无需再处置运行中的进程

## Verification
- 每个被排除的候选必须引用其日志中的排除事实（如 16:40 后零次 tool.execute），而非'应该不是它'式叙事
- 最终机制的每条断言（截断、无跨轮记忆、用户已停止）都有对应事件/数字支撑
- 与上一轮叙述冲突处显式自我纠正并说明依据，不做 silent 修补

## Counterexamples
- 用户投诉中已含显式指针（session id / run ref / URL）——指针本身就是判别器，直接去该 session，跳过签名普查
- 只有一个候选 run——无需选靶，直接读它的日志
- 多个候选同时呈现重复签名（批量任务集体退化）——签名失去区分力，需回到用户给的时间窗或显式标识
- 症状是内容性抱怨（'文章正文没抓到'）而非行为循环——重复计数与症状无关，应走 provenance/内容核验路径
