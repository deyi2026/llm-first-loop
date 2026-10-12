---
method_id: consume-miss-receipt-index-before-broad-enumeration-2956cfd5c488
name: consume-miss-receipt-index-before-broad-enumeration
description: 当定向检索未命中、但回执本身附带权威索引（如 docs 最近文档引导、命名的阶段 Result/Audit 列表）时，把该索引当作导航答案：按角色选读 spec 状态头、最新阶段 Result、最新 Audit 的 done/not-done 清单，再决定是否需要源码或宽枚举；不要先退回全目录/全记录枚举，也不要换关键词重搜索引中已命名的文档。适用于『内部项目当前水平/进展/优劣评估』类问题。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:943:8e50e30369c784d97364
evidence_refs: learning:learn:23e9000546c0
created_at: 2026-09-19T12:23:35.091774+00:00
updated_at: 2026-09-19T12:23:35.091774+00:00
---
## Trigger
用户询问某内部项目/能力的当前水平、阶段进展或优劣并要求建议；首轮定向检索（docs/records/术语）未命中，但回执附带命名相关文档的索引或引导列表。

## Discriminator
回执索引中是否存在与查询主题语义相关、带日期的阶段规格/结果/审计文档名（如 spec v0.1 + 最新 P-stage Result + Audit）。该事实在首轮回执中即已出现，足以把『权威状态证据在哪』从全仓枚举缩到 3-5 个命名文件，无需任何后续信息。

## Short path
- 用目标术语做一次定向 docs/records 检索；若未命中，先检查回执是否附带文档索引引导，而不是立刻转入宽枚举。
- 索引命中相关文档时，先读规格/总览文档头部状态声明（status/authority/scope），确定架构与权威边界。
- 按阶段新近度读最新 Result 与 Audit，提取 PASS 结论与显式『未做/断点』清单，形成成熟度链与缺口。
- 仅当结论需要模型面/生产面事实时，做一次定向文件搜索（如注册工具名）并读权威树对应源码。
- 同类对比做一次外部检索，无关则明确标注基于训练知识；汇总时按『文档证据 vs 未核验知识』分层标注来源。

## Stop conditions
- spec 状态头 + 最新阶段 Result 结论 + Audit 未完成清单已同时覆盖『当前水平、缺口、后续建议』三个未知量。
- 索引中语义相关文档已读完或已判定与查询主题无关。
- 不再用改写关键词重搜索引中已命名的文档，也不为『再确认』重复宽枚举。

## Verification
- 最终每条状态断言可指向一篇已读阶段文档（含日期/锚点/哈希）。
- 文档声明的事实与训练知识/未核验部分在回答中被显式分层标注。
- 未读的枚举命中（实验变体目录、runtime 镜像快照）未被引用为当前状态证据。

## Counterexamples
- 索引只是通用『最近文档』列表且与查询主题仅有关键词巧合、无语义关联——索引低信号，应退回定向枚举或 records 检索。
- 用户问的是运行时实际行为而文档可能落后于代码——必须以权威树源码或实测为准，不能只读结果文档。
- 查询针对尚未成文的新改动——最新文档反而陈旧，沿索引走会得到过时状态。
