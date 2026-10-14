---
method_id: resolve-ordinal-phase-reference-via-predecessor-delivery-report-3a4d8ce61ed0
name: resolve-ordinal-phase-reference-via-predecessor-delivery-report
description: 用户以序号/版本名（PhaseN、vN）引用上一工作流计划，而 docs 搜索未命中、无活动 Goal/Evidence 时，不做全库内容宽搜或事件流考古：沿该工作流自身的文档命名序列，直接读最新前序阶段交付报告的『下一阶段候选/遗留评审』小节——它是后继阶段范围的权威定义。裸子编号（P2-x）按评审批次局部作用、跨子系统重载，只有带评审上下文的命中才可判别。可省去超时宽搜、archive 空查与跨项目同序号 false lead 的排除成本。与 resume-continuation 的区别：本方法适用于回执点名文档不含目标工件、需由命名约定推导指针的场景。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:71c7ba15-0442-4198-ba4d-d82f40d7de25:1:c559dbd7eac9d990504b
evidence_refs: learning:learn:60db79b2cc78
created_at: 2026-10-13T21:30:46.228690+08:00
updated_at: 2026-10-13T21:30:46.228690+08:00
---
## Trigger
用户指令引用带序号/版本号的历史计划工件（如『启动 Phase5（流式打断、P2-4 混合场景）』），而 search_docs 未命中、无活动 Goal/Evidence；或对短编号（P2-x/SN-x）宽搜命中多个互不相干子系统的结果。

## Discriminator
docs/ 中存在同系列命名的前序交付报告（phase3-/phase4-…），且最新一份的命中行已把用户提到的子编号与其评审上下文配对（如『终局评审 P2-4（混合路径戳记时序）』），而同一回执里其余 P2-4 命中来自无关子系统（连接泄漏、feishu 公式检测、审计报告等）——证明子编号跨评审批次重载，只有上下文匹配的那一条才是本任务的定义来源。

## Short path
- 廉价探针：按用户原词 search_docs + 查 Goal/Evidence 状态，确认会话内与 docs/ 无现成该阶段定义。
- 枚举该工作流文档命名序列（phase*-delivery-report/design），读最新前序（phase4）交付报告；未知量：所引阶段与子项的权威定义。
- 报告的『下一阶段候选/遗留评审』小节应逐词覆盖用户提到的项（llm_stream 流式打断、终局评审 P2-4 混合路径）；再读其点名的『设计真值』文档取约束。
- 用报告中点名的精确标记（如 interrupt_receipt/last_receipt_interrupted）做定向代码检索，建 Goal 与任务图，停止发现。
- 仅当用户某词未被前序报告覆盖时，才带该词单点扩大（archive/event_stream），并把跨工作流同序号命中当嫌疑逐一排除。

## Stop conditions
- 前序交付报告的下一阶段/遗留小节已逐词覆盖用户提到的每一项（流式打断与 P2-4 混合场景均有具名条目），且设计约束文档已读 → 停止发现，进入建 Goal 与实现。
- 任一用户词在前序报告中无对应条目 → 仅对该词单点扩大一次；不得对同一库换措辞重复宽搜。

## Verification
- 用户每个词都能映射到前序报告的具名行/小节（『流式打断』↔llm_stream 桶/流内检查点；『P2-4 混合』↔终局评审 P2-4 混合路径戳记时序）。
- 跨工作流同序号工件（如 MAINLINE-RECONCILIATION-PHASE5-*、test_memory_phase5_*）以文档系列/日期/子系统不符显式排除，而非默认并入。
- 来自其他子系统的裸 P2-x 命中未被当作本任务的 P2-x 采纳。

## Counterexamples
- 用户引用无序号、库中也不存在阶段文档命名序列（临时任务名）→ 无法由约定推导，应走回执点名文档/wakeup 备忘/git delta（resume-continuation 方法的边）。
- 最新前序报告的遗留小节未覆盖用户提到的子编号（它属于另一子系统的评审批次，如 feishu P2-4）→ 约定边被证伪，须转到该子系统自己的评审文档。
- search_docs 直接命中该阶段的现成计划文档 → 直接读它，无需前序推导。
- 前序报告可能与当前 HEAD 代码状态脱节 → 报告只提供范围定义，动手设计前仍须核对代码现状。
