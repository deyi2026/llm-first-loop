---
method_id: match-search-store-scope-to-record-epoch-228dfa88ba03
name: match-search-store-scope-to-record-epoch
description: 检索前先对齐 store scope 与目标记录的纪元。当回执显式标注被查 store 为“当前会话 Evidence”，而目标记录属于先前轮次（“上轮材料”）时，该 store 的 miss 是可预测空结果，不构成“不存在”的证据；应直接查询 scope 覆盖该纪元的持久档（archive），且单次查询只携带一个未知量。只有 scope 匹配的 store 也 miss，才支持“未落档”结论，并立即转为计划中的补录动作（写死判据/owner）。本集先对会话 evidence 发起可预测 miss 的捆绑式查询、再换措辞补查 archive，多花一跳才得到同一结论；archive 直接单查即可。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1f576ea-8082-441a-9f68-2d1021c05410:39:a05f75a70ed4622c97e3
evidence_refs: learning:learn:19cc856db328
created_at: 2026-10-07T04:33:32.202804+08:00
updated_at: 2026-10-07T04:33:32.202804+08:00
---
## Trigger
需要确认一条属于先前会话/轮次的记录（判据、owner、落档结论）是否存在，且检索面有显式 scope 划分（如 “当前会话 Evidence” vs archive 持久档）。

## Discriminator
回执已显式标注被查 store 的 scope（“未找到匹配…的当前会话 Evidence”），而目标记录按任务上下文属于先前轮次（“上轮材料”）：scope 不覆盖记录纪元的 store，其 miss 是可预测空结果，不携带“不存在”的信息。

## Short path
- 先给未知量标注纪元：目标记录产生于当前会话还是先前轮次（依据任务上下文，如“上轮材料”）
- 只向 scope 覆盖该纪元的 store 发起第一次查询：先前轮次→archive/持久档；当前会话→会话 evidence
- 每次查询只携带一个未知量，不把多个门/主题捆绑进同一查询词
- scope 匹配的 store miss → 结论“未落档”，随即转成计划中的显式补录动作，停止检索

## Stop conditions
- 在 scope 覆盖目标纪元的 store 中命中目标记录：停止检索，转入读取与引用
- scope 匹配 store 也 miss：得出“未落档”并转为补录动作，不再对同一 store 换措辞追查

## Verification
- 任何“无记录/未落档”断言，必须至少有一条 miss 来自 scope 覆盖目标纪元的 store；scope 不匹配的 miss 不得作为“不存在”的证据
- 核对确认记录存在性所花的检索调用数：每个候选 store 至多 1 次单一主题查询（本类问题应 ≤2 次）

## Counterexamples
- 目标记录本就可能产生于当前会话（如本会话早先写入的 evidence）：会话 store 是正确的第一查询点，先查 archive 反而是 scope 错配
- store 无 scope 元数据或为全局统一索引：无法判断覆盖范围，本方法不适用，直接查唯一 store
- 记录纪元不明、可能跨纪元：可先查覆盖面更广的 store，但下“不存在”结论前必须两类 store 都 miss
