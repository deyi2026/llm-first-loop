---
method_id: negative-claims-anchor-to-target-canonical-enumerative-source-e5d5ff7045e1
name: negative-claims-anchor-to-target-canonical-enumerative-source
description: 写跨系统对照内容（对照表、优劣论断、引用式细节）时，凡对外部系统 X 的否定/限定性断言（只支持/缺乏/没有），不能由单一局部页面（博客、教程、单页文档）推出：局部来源不枚举全量能力，'未提及'≠'不存在'。必须锚定 X 的权威枚举式来源（官方 README/docs 能力清单）定位确切原句；任何来源都找不到逐字锚点的引语降级为归属化表述或删除。本集把 LangGraph 记忆误写为'仅短期'（依据只提 short-term memory 的官方博客页），靠独立审查闸对照官方 README（comprehensive memory）才纠正，另删一条无法逐字核到的引语。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:62656ded-4312-49b5-9186-604e30fa43c1:0:bb5bf75e7dcbf0404870
evidence_refs: learning:learn:2b672be9448e
created_at: 2026-10-17T00:48:45.411411+08:00
updated_at: 2026-10-17T00:48:45.411411+08:00
---
## Trigger
撰写或发布包含对外部系统（框架/平台/API）的比较与否定性能力断言的内容，如多框架对照表、'X 缺乏 Y'式论断、或从单一教程/博客页引用的能力细节

## Discriminator
断言范围×来源覆盖度不匹配：断言是对目标系统能力集合的否定/限定（only/lacks/不支持），而当前唯一依据是叙事性局部来源（博客/教程/单页文档）——从未枚举全量能力的页面在逻辑上支撑不了'只有/没有'；此判别在提笔时即可观察，无需等审查纠错

## Short path
- 起草时把陈述分三类：自项目事实（本仓库为 SoT）、外部系统能力断言、观点/定位
- 对每条外部否定/比较断言，取目标系统的权威枚举式来源（官方 README/docs），定位支持或反驳的确切原句；未知量：X 的规范能力清单是否包含 Y
- 权威来源显示能力存在 → 用锚点改写断言（本集：LangGraph README 写明 comprehensive memory，推翻'仅短期'）
- 任何权威来源找不到逐字锚点的引语/细节 → 删除或降级为归属化表述（'该博客强调…'）
- 不可逆发布前保留独立审查闸并复核全部否定断言锚点——本集正是该闸抓出了单源错误

## Stop conditions
- 每条外部否定/比较断言都能回链到目标系统官方文档的确切原句
- 剩余陈述均为归属化观点或仓库内可核验的自项目事实
- 审查闸 PASS 且草稿中无'看似可信但无锚点'的断言残留

## Verification
- 逐格复查对照表：每个含'只/仅/缺乏/不支持'的单元格回链官方文档原句
- 复查删改清单：被降级/删除的引语未以更强措辞回流正文
- 发布前最终稿中不存在仅有单一局部来源支撑的否定性断言

## Counterexamples
- 主观/定位性比较（'X 显得笨重'）：归属化即可，权威文档不约束观点
- 行为性断言且文档已知夸大或漂移（实验特性、文档与 runtime 不一致）：最小可复现实验高于 README；权威文档只背书'声称的能力'，不背书'实际行为'
- 断言本身就是关于那个单一页面内容的（引用该博客原话）：该页面即权威，无需再找枚举源
- 自项目断言：仓库为 SoT，勿抓外部冻结镜像（如 .releases 快照可能过期）
