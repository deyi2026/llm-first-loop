---
title: Tool Discovery→Callability 断链：schema 查得到、工具调不着，breaker 盲拦三次后 terminate
scenario: 模型 reasoning 已明确决定调用目标工具（如 spawn_subagent），按协议先 get_tool_schema(X) 并取得 SUCCESS+完整 schema；但下一轮 tool.eligibility projection 未将 X 纳入 callable（candidate 仍为 CORE 白名单 9 个），模型唯一相关的 escape hatch 是重复 get_tool_schema，被 duplicate breaker 依 x3→x4→x5 连续拦截后 terminate。两个不同目标工具（save_experience、spawn_subagent）先后复现同一模式，证明是通用 Tool Discovery → Callability 断链而非工具特例。
root_cause: "discovery 结果只写进对话历史（模型知道 schema），未写回 projection 状态（系统不给 callable）；eligibility 重建只做静态 CORE 白名单过滤，不消费上一轮 discovery SUCCESS 事实。断链在层间（schema 层↔projection 层），不在层内；breaker 只见\"重复调用\"表象，将 capability 故障误判为模型停滞。"
solution: L1 根因修复 One-Hop Promotion：get_tool_schema(X) SUCCESS 且 X∉当前 callable → 下一轮 projection 注入 X（本质：把 discovery 结果从对话历史提升为系统状态）。L2 护栏：同参重复 + schema 已 SUCCESS 取得 → 首次即注入结构化 capability-recovery 状态（target/schema_known/target_callable/reason=projection_missing）并停止 discovery 循环，不经历 x3/x4/x5；模型据此立即转策略（如主代理直接执行子任务）。L3 breaker 回执事实化：任何拦截必须携带重复原因+替代路径+能力状态，使第一次拦截即终结信息。L4 可观测性：breaker 拦截+capability 缺失事件结构化落盘 episode/audit 可检索通道。
evidence: "call_900b930c8c0542919f366360 轨迹（operator 侧核验）：get_tool_schema(\"spawn_subagent\") SUCCESS 后 x3/x4/x5 BLOCK + terminate；tool.eligibility original=61/candidate=9；get_tool_schema∈CORE、spawn_subagent∉CORE；模型 reasoning 多次明确\"直接 spawn_subagent\"。AI 主体侧 search_records 三轮检索（call_id 原文、save_experience+breaker、One-Hop promotion+断链）均返回未命中，未伪造结果。"
tags: [tool-capability, breaker, schema-discovery, projection, one-hop-promotion, root-cause, observability]
source: {}
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-03T08:10:15.934114+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "runtime:stable-tool-surface-p1b"
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

故障模式（两例不同目标工具同型复现）：模型 reasoning 已明确"下一步直接调 X"，按协议先 get_tool_schema(X) 得 SUCCESS+完整 schema；下一轮 tool.eligibility 重建后 X 仍不在 callable（candidate 停留在 CORE 白名单 9 个），模型唯一相关 escape hatch 是重复 discovery，被 duplicate breaker x3→x4→x5 连拦后 terminate。期间无新用户指令、无参数变化。

判定两分：单次拦截（x5）正确——同参重复 discovery 无新信息；发展路径（x3→x5→terminate）是设计缺陷——拦截回执不携带事实语义（target callable 状态/reason），模型收不到"重试注定失败"的信息，局部最优策略仍是重试，breaker 的"否决"没有变成"告知"。

修复分层：L1 One-Hop Promotion（根治）：discovery SUCCESS → 写回 projection 状态而非仅对话历史；L2 capability-recovery 状态（护栏）：同参重复+schema_known → 首次即注入结构化状态并停止循环，模型立即降级（主代理直接执行）；L3 breaker 回执事实化（保险的保险）：任何拦截必须携带重复原因+替代路径+能力状态，首次拦截即终结信息；L4 可观测性：此类事件结构化落盘可检索通道（本次 call_id 级轨迹在 episode 索引三轮检索均未命中，复盘依赖人工原始日志即为反例）。