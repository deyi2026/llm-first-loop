---
method_id: adjudicate-rule-instance-by-counterfactual-not-enforcement-firing-36ae88c1469d
name: adjudicate-rule-instance-by-counterfactual-not-enforcement-firing
description: 判定某 episode 是否构成某方法卡/规则的陷阱实例（cue/temptation/action/stop）时，action 的"必要性"只能按规则的反事实定义裁决（删掉该动作答案是否变错、是否出现规则点名的诱惑形态），不能以"执行层机制是否实际拦截"为判据：回执未绑定命令指纹、Host 未阻断、静默放行，可能恰是规则反事实段覆盖的"绕过校验"路径，属实例而非 related_only。验收子代理此类判定时，机械核查（结构、引文回源）全过仍不够，必须对"未见阻断"的边界判定回读规则反事实定义，并回源逐字比对准入串与实际执行串，发现任何改写即改判并留痕。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:799:caae9cb6082d524b7a22
evidence_refs: learning:learn:af32c26a84f0
created_at: 2026-10-21T09:35:34.758650+08:00
updated_at: 2026-10-21T09:35:34.758650+08:00
---
## Trigger
需要自己或验收他人（子代理）对"某 episode 是否构成某规则/方法卡的实例"做四元组裁定，且遇到边界情形：判定理由是"回执无指纹绑定/Host 未拦截/执行未被阻断"，并据此推出"动作非必要、不算实例"。

## Discriminator
裁决当时已在手的两条事实：①治理文档与卡文本自身写明反事实判据（如"action 是必要步骤＝删掉它答案会变错""若合并后仍放行则绕过命令绑定校验、同样有害"）；②原始记录中"被准入的参数串"与"实际执行的命令串"可分别提取并逐字比对，是否存在改写（合并、去注释、追加管道）是机械可判的。二者都不需要事后答案。

## Short path
- 先做机械验收（字段结构、引文回源 messages[idx]、去源规则）——这只能排除编造，不能证判定正确
- 对每个以"未拦截/无指纹 ⇒ 非必要"为理由的判定，回读卡文与设计文档的反事实段，确认必要性判据是"删动作是否致错"而非"是否被抓"
- 回源该 episode：独立提取 tool_calls 里的准入参数串与 messages 里的实际执行串，逐字比对
- 存在任何改写且动作处于闸保护之下 ⇒ temptation/action 成立，改判 instance；原判定与改判理由一并写入 NOTES 留痕，不删改历史
- 执行串与准入串逐字一致且无改写迹象 ⇒ 维持非实例判定，该条复核完毕

## Stop conditions
- 准入串与实际执行串逐字一致，且无任何合并/改写/追加证据（正常走闸）
- 规则文本明确把适用范围限定为指纹绑定型回执、反事实段不覆盖静默放行——无指纹确属卡范围之外
- 全部边界判定均已按反事实判据复核并留痕

## Verification
- 逐字比对：从 tool_calls 参数提取的准入串 vs messages 中的实际执行串，差异即改写证据
- 改判后重算 instances/独立组/任务族统计并写回 pool_status 与 NOTES
- 原判定、改判及理由同时可回溯（不删除历史判定）

## Counterexamples
- 规则危害只来自"被拦截后多烧一轮"的纯效率路径、反事实段未覆盖静默放行：此时未拦截的改写执行确实不构成实例，以"是否发生阻断"为判据反而是对的
- 执行串与准入串逐字一致、Host 正常放行：这是正常走闸，无诱惑出现，不是实例，不应为凑数改判
- 闸按设计只做动作级绑定（如仅绑"确认发布"动作而非命令指纹）且卡 Trigger 明确限定指纹形态：无指纹回执在卡范围外，维持 related_only
