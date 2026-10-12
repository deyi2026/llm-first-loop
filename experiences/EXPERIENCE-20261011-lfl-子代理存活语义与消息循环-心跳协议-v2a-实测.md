---
title: LFL 子代理存活语义与消息循环：心跳协议（V2a 实测）
scenario: 需要子代理在多轮交互中保持存活可寻址的场景：多 bot 房间协作、父代理中途纠偏、需要 child 等待后续指令的长任务
root_cause: ""
solution: "spawn 时 task 明文写「每条回复必须携带下一次心跳工具调用，纯文本回复=结算死亡；收到终止信号前不得输出无工具回复」；心跳用最便宜只读工具；父侧用 subagent_result(wait 20-30s) 轮询中途报告获取 child 消息；终止信号（如 [ROOM-END]）经 agent_message 排队送达"
evidence: 本轮工具回执：spawn 回执×2、agent_message 回执×4（含结算后拒绝原文）、subagent_result 回执×8（含中途报告与结算记录）、subagent_lease 回执、两 child 结算报告（工具轨迹+token 计数）；提交 bf3566b45
tags: [subagent-lifecycle, agent-message, room-protocol, heartbeat, poc-verified, LFL-runtime]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T23:59:06.572950+08:00"
updated_at: "2026-10-11T23:59:06.572950+08:00"
---

LFL 子代理存活与消息机制（2026-10-11 实测，glm-5.3 会话）：
1. child 输出无工具调用的回复 → 运行时立即结算 completed；「纯文本等待」不是存活状态。要长驻必须每轮携带工具调用（心跳轮询，event_stream(scope=current_session, limit=1) 是最便宜只读心跳）。
2. parent→running child 的 agent_message 回执「已排队到下一 step boundary」——非即时中断，送达时延上限=child 心跳间隔。
3. child→parent 消息不经会话注入，经 subagent_result 回执「[中途报告 N 条]」呈现；父可见时延=父轮询间隔。
4. 结算后 agent_message 确定性拒绝（仅活跃相邻边可通信）；结算后续命只有 agent_followup（父 ≤4 次/15min）。
5. spawn requires.tools 非排他白名单：child 可见几乎全量工具（含 spawn/service_control/feishu/escalation），NFR 类工具禁令在 spawn 层不可强制，只能 task 文本纪律+工具轨迹审计。
6. 成本：心跳 child 每轮≈全上下文重放（8 rounds ≈140K input tok）；spawn 会传递 LFL 基座人格（child 自发 search_records 方法检索）。