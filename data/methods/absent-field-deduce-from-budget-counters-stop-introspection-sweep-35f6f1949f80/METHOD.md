---
method_id: absent-field-deduce-from-budget-counters-stop-introspection-sweep-35f6f1949f80
name: absent-field-deduce-from-budget-counters-stop-introspection-sweep
description: 任务要求回报一个权威回执从不显式回传的事实（如异步子审查的'实际执行模型'）时，不要连续枚举 subagent_lease/subagent_topology/event_stream 等只读内省面去找字段：先检查回执中已有的有序备选列表与生命周期计数器——start 的 models=[主选,备用]+async_retry_max，以及 pending 期 review_budget.attempts 恒 0。备用只能经 async retry 介入，计数为零即演绎出主选实际执行、无降级。subagent_result（为取 VERDICT/P0/P1/P2 必查）回执同样无模型字段后，至多再做一次有界探查确认字段缺席即停；报告把演绎结论与'Host 无显式字段'的证据边界分开陈述。本集可省去 topology 与两次 event_stream 等同未知量枚举。
aliases: 实际模型查不到别再翻租约和拓扑, attempts为零就是没走备用模型, 回执里没有的字段换工具也找不到, 审查收口时模型身份证据边界, 用重试计数反推真实子代理模型
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8a18daae-e0d0-4da0-8849-7b437471cb36:0:865ccf744ba50afb69a9
evidence_refs: learning:learn:74b836ecbf15
created_at: 2026-11-12T17:45:05.823492+08:00
updated_at: 2026-11-12T17:45:05.823492+08:00
---
## Trigger
任务书要求回报某事实字段（如异步子审查的实际执行模型/真实 reviewer 身份），而 start/status/result 等权威回执均未以字段形式回传该事实，但回执内已含可演绎它的有序备选列表与生命周期计数器（models 列表、async_retry_max、attempts）。

## Discriminator
pending 期 status 回执里 review_budget.attempts 恒为 0 且 models=[主选,备用]、async_retry_max=1：备用模型只能通过 async retry 介入，计数为零即证明备用从未被调用，实际执行者就是主选。该事实在轮询阶段已可见，无需任何额外内省调用即可闭环；同时这些回执均无'实际模型'字段，说明该 Host 只以预算面暴露模型。

## Short path
- start 回执：核对 candidate_sha256 回显与 review_budget（models 有序表、async_retry_max、deadline），确认模型只以预算面暴露
- 按 waiting_protocol 轮询 status 至终态，每次顺手记录 review_budget.attempts（全程 0 ⇒ 无备用介入）
- 终态后查 subagent_result 取 VERDICT/P0/P1/P2 与 child 事实；该回执同时证明结算面也不含模型字段
- '实际模型'直接由 attempts=0 + 有序 models 表演绎为主选执行；如需，至多一次有界只读探查（如 lease）确认无显式字段，miss 即停
- 报告把演绎结论与证据边界（Host 不回传该字段）分开陈述后收口，不再枚举 topology/event_stream 等内省面

## Stop conditions
- 所需事实已由回执内计数器演绎闭环，且至多一次探查确认无显式字段
- 首个内省面回执即显示该 Host 不回传此字段（缺席模式确立）
- 任务所需其余字段（qualification/VERDICT/计数/指纹）均已由权威回执验证

## Verification
- 回放全部 pending status 回执，确认 attempts 恒 0 且无 async_retry/降级事件
- 最终报告中'实际模型'一节明确标注：结论为计数器演绎、Host 无显式字段——边界与结论分离
- 确认未因字段缺席而扩大到未授权工具面（保持只读约束）

## Counterexamples
- 回执从不含计数器或有序备选列表（无演绎原料）时，按文档选 1~2 个有界内省面探查是必要的，不适用本卡
- 首次探查回执带部分线索（如事件流含其他 child 的模型路由记录）：字段存在于其他 scope/limit，应沿线索改参一次而非立即停止
- 任务验收硬性要求一等字段而非演绎（如审计要求回执原文）：正确动作是如实报告字段缺席并标记未满足，而非推定主选已执行
- 计数器非零或出现过 retry/降级事件：演绎前提破坏，必须继续取证实际路由
