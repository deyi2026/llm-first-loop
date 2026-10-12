---
method_id: live-source-verify-pending-external-items-4574e64b5649
name: live-source-verify-pending-external-items
description: 用户询问已闭合目标的"下一步建议/状态"时，决策相关的未知量是外部工件的当前实时状态，而不是记忆中已报告过的历史结论。当目标状态=complete 且记忆中已存在对唯一/少数挂起外部项（PR、CI、后台 job）的明确引用和既往完成报告时，应直接查询该外部项的权威实时源确认现状；在 evidence/archive/event_stream 等记忆存储里反复改写关键词重建旧结论，既无法更新外部状态，也答不了"现在该做什么"。记忆存储只用于识别"哪些项还挂着"，不用于验证其当前状态；实时状态只有权威源能回答，且回答中应注明"刚重新核验，非缓存"。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:1061:bb4d72788862ae197add
evidence_refs: learning:learn:25a89b659318
created_at: 2026-09-18T03:04:41.128204+00:00
updated_at: 2026-09-18T03:04:41.128204+00:00
---
## Trigger
用户请求下一步建议或终态汇报，且 (a) 目标查询显示状态已 complete、(b) 会话记忆/schedule/pending 中已能定位出唯一或少量显式挂起的外部项（如待合并 PR、CI、后台任务），该项有可查询的权威实时源。

## Discriminator
当时已知两条事实：(1) get_goal 返回 complete 且全部 checkpoint 通过——目标层面无剩余未知量；(2) schedule 提醒与 01:48 的完成报告、01:49 的 declaration_check 已明确唯一挂起外部项=该 PR 的推送/CI，且结论已在会话内闭合。这两条把候选空间从"翻全部 487 条 evidence/多轮改写查询词"缩到唯一未知量：该外部项此刻的实时状态——而记忆查询无论怎么换关键词都无法改变或更新外部状态，只有权威源能。

## Short path
- get_goal → 未知量：目标层面是否还有未完成步骤？（complete → 无）
- 查 pending 来源（schedule 提醒 / pending_actions）→ 未知量：当前显式挂起的外部项清单是哪些？（收敛到：某 PR 的合并状态）
- 对每个挂起项直接查其权威实时源（托管平台 API/CLI，如 gh pr view）→ 未知量：此刻 state/mergeable/checks 真实结论
- 若将建议合并，再做一次基线核对（head 是否已含 main tip）→ 未知量：合并建议是否存在基线漂移风险
- 组装带"刚重新核验"标注的按序建议清单并停止；不再用记忆检索复证实时结论，也不为找回旧建议清单而多轮改写查询词

## Stop conditions
- 目标状态与全部显式挂起项的实时状态均已由权威源本次返回确认
- 记忆检索已定位挂起项清单后即止，不再继续在记忆存储中查询这些项的状态
- 用户问题属于历史重建类（问"之前说过什么"）时，以记忆/事件流命中所需内容为停止条件，此时不适用本方法

## Verification
- 回答中的外部状态字段（state/mergeable/各 check 结论）逐条对应权威源本次返回值，而非引用旧 evidence 回执
- 确认 pending_actions/schedule 中显式注册的其他挂起项均已覆盖，无遗漏
- 记忆旧结论与实时源冲突时，以实时源为准并向用户注明核验时间与非缓存性质
- 若建议合并/推送等写操作，确认已声明需要用户授权而非自行执行

## Counterexamples
- 权威实时源不可达（无网络/无凭证/无 CLI）时，记忆中的 evidence 回执是当前最佳可用事实，应读回执而不是反复空查实时源
- 用户问的是历史内容（如"上一轮建议清单第2条是什么"），记忆/事件流才是目标数据源，查实时 API 完全无关
- 目标状态非 complete 时，下一步建议应来自 goal 剩余 checkpoint/计划本身，而非外部 PR 状态
- 挂起项清单尚未识别（无数个未知项、无显式引用）时，先做一轮 pending 枚举/宽发现是必要前置，不构成摩擦
