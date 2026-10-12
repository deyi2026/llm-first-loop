---
method_id: spec-first-recompute-from-provenance-note-9943b53776a7
name: spec-first-recompute-from-provenance-note
description: 独立重算派生指标（如 sidecar 恢复值、对账数据）前，先读取产生该值的 artifact 中写明的推导口径（recovered_from/事件类型/字段/公式）作为提取规格，并抽样一条真实记录确认 schema，再写聚合脚本；对非空数据源得出全零聚合应判为解析失败而非数值不符。这把『猜日志 schema』缩成『确认一个已写明的 schema』，并避免假性 MISMATCH 触发整条『恢复值不可信』的错误分支。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:1040:be6999a15fe0d26ce3e1
evidence_refs: learning:learn:e410aaeb81dc
created_at: 2026-09-22T15:52:43.679905+00:00
updated_at: 2026-09-22T15:52:43.679905+00:00
---
## Trigger
需要独立验证或复现一个由原始日志/记录派生出的数值是否可信（审计恢复值、对账、复核统计口径、复算聚合结果）

## Discriminator
派生 artifact 是否已写明提取口径——本例 sidecar 的 recovered_from 字段明确写着『request.usage 聚合』，在写重算脚本之前就已读到；且源 jsonl 非空（数十~数百 KB）而聚合结果全零，二者组合是 schema 解析失败的强信号，而不是数值差异

## Short path
- 读派生 artifact，提取其注明的来源与聚合口径（事件类型/字段/公式）作为提取规格
- 按该口径抽样 1 条真实记录，确认实际字段结构（如 type==request.usage 且 payload 含 round/tokens_in/tokens_out）
- 用确认后的 schema 写聚合脚本，一次性重算全部目标值
- 重算值与声明值全部对上后，再用独立绑定证据（如首条用户消息 marker）交叉核验
- 若仍有差异，先怀疑口径版本差异并逐字段对比，而非直接判定派生值不可信

## Stop conditions
- 全部目标重算值与派生 artifact 声明值一致，且独立绑定证据成立，即停止扩展取证
- 源数据确认为空（0 字节）时全零即真值，立即停止 schema 追查

## Verification
- 抽样记录的事件类型/字段与 artifact 注明口径一致
- 每个目标值重算逐一 MATCH，不存在把全零结果当作数值差异上报
- 任何全零聚合必须先与『源文件非空』事实对质，确属解析失败后才修正脚本重跑

## Counterexamples
- 派生 artifact 未记录任何推导口径：方法退化为『先抽样 schema 再聚合』，无从读规格
- 源日志本身为空或 0 字节：全零聚合就是真值，判为提取失败会误导结论
- artifact 注明的口径已过时（schema 变更后未同步）：说明与实测数据冲突时必须以数据为准，不能盲信说明
- 只需确认派生值存在或被引用、不需要数值复算时，不必走完整重算路径
