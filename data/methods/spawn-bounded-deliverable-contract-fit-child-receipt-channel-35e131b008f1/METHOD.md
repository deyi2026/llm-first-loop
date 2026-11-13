---
method_id: spawn-bounded-deliverable-contract-fit-child-receipt-channel-35e131b008f1
name: spawn-bounded-deliverable-contract-fit-child-receipt-channel
description: 委派调研/审计类子代理后，若其最终报告超过回执通道边界，父侧会被迫补读全文（本集三份回执截断、补读成重复调用，且逐轮累计 tokens_in 烧到 2M）。在 spawn 任务书里预先写明交付契约：最终报告限长、只含结构化承重结论（结论+精确路径/符号+反例+未核项）、禁止原文/代码转储，使 subagent_result 一次回执完整送达；父侧读后立即提炼入上下文，不再重复回读。只读 child（write_scope.paths=[]）无法落盘产物时尤其如此。
aliases: 子代理总结超长怎么办, spawn 时限制 child 回复长度, 审计报告塞不进回执, 读完子代理结果马上提炼, 并行子任务回执截断要补读, 任务书加交付格式约束
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b2854c0-2f52-4792-b2b6-7757cc5f60b5:0:da55aa2bbb05ce42c4c4
evidence_refs: learning:learn:bceb33d37e32
created_at: 2026-11-12T23:46:53.472733+08:00
updated_at: 2026-11-12T23:46:53.472733+08:00
---
## Trigger
向子代理委派产出长报告的调研/审计/复核任务，且父级计划用 subagent_result 回执直接接收其最终结果时

## Discriminator
协调平面工具 schema 已暴露硬字符边界（本集 get_tool_schema 显示 agent_message maxLength=4000），而拟发出的任务书未含任何输出长度/结构契约——可预判多页报告会溢出回执通道

## Short path
- spawn 前已取协调工具 schema，读出通道硬边界（消息字符上限、单次等待上限、requires.tools 白名单语义）
- 把交付契约写进任务书：最终报告 ≤ 通道安全长度，只含结论表+精确路径/符号+反例+未核项，禁止转储原文/代码
- 回执到达后一次读完并立即提炼承重结论（父侧再按符号交叉核验），不把全文留在待重读状态
- 若回执仍标截断，仅对缺失 range 定点补读一次，不整篇重读

## Stop conditions
- 回执完整（无截断标记）且承重结论已提炼并经父侧独立复核
- child 终态为运行级失败时转分段重派处理，不再等待长报告

## Verification
- subagent_result 回执无截断、无需补读；父侧复核能直接引用回执内路径与符号
- 对照 spawn 任务书确认存在限长+结构契约条款

## Counterexamples
- child 产物本身是代码/补丁/长制品，无法压进文本→应授权落盘并回 stable ref，而非压缩长度
- 单个简单 child、报告天然短于通道边界→契约是纯开销
- 回执通道无上限或自动完整分页→无需契约
