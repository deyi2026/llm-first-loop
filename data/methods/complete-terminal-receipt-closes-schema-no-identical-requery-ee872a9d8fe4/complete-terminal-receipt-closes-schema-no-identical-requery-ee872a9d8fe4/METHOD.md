---
method_id: complete-terminal-receipt-closes-schema-no-identical-requery-ee872a9d8fe4
name: complete-terminal-receipt-closes-schema-no-identical-requery
description: 确定性只读状态查询返回的终态回执若结构完整（无截断、无错误码、SHA 与受理一致），其字段集就是该终态的全部 schema：同参重发不可能带出首次没有的字段。当下游验收义务点名回执缺失的字段（如 P0/P1 计数）时，用闸的签发合同推解义务（PASS 仅在核过精确 SHA 与计数后才签发，故 PASS 蕴含计数为 0），并在报告中如实标注『回执未显式枚举、按合同推解』，不虚构数字、不陷入重复查询。只有出现截断、两次回执 SHA 漂移、或存在能携带该字段的不同查询端点时才再次查询；pending 阶段的有界轮询不适用本方法。
aliases: 终审PASS回执没给P0P1计数还要再查一次吗, 审查通过回执缺字段重复查询有没有用, 要不要再发一次确认请求核对计数, 同参重查能补出回执里没有的数字吗
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:ee328bb6-1c1e-4afb-ba31-eccb43c23960:1:c93cb70eb6c70a8d7c59
evidence_refs: learning:learn:5653a14761b4
created_at: 2026-11-20T14:28:40.956309+08:00
updated_at: 2026-11-20T14:28:40.956309+08:00
---
## Trigger
准入/审查类确定性只读查询已返回完整终态回执（判定终态、artifact_reviewed、candidate_sha256、consumable_scope 齐全，无截断与错误码），但回执缺少任务验收义务点名的字段（本集为 P0/P1 计数），模型考虑同参重发一次以『再确认』。

## Discriminator
重发之前即可知的三件事：① 首份终态回执已枚举该终态携带的全部字段且完整未截断；② 对已终态的审查子代理，同参状态查询是确定性幂等的，不可能返回首次缺失的字段；③ 验收义务可由闸的签发合同推解（PASS 签发前提即含该判定）。三者共同把『再查能否补出计数』这一未知量在动作前判死。

## Short path
- 终态回执到达，先机械核对四项：判定为终态、artifact_reviewed=true、candidate_sha256 与受理回执逐字一致、scope 路径覆盖任务声明清单。
- 对照验收义务清单逐项检查回执字段；缺失字段直接标记为『回执未枚举』，不因缺失而触发同参重发。
- 用签发合同推解缺失义务（PASS 签发前提含 P0/P1 核对 ⇒ 计数为 0），在最终报告如实注明这是推解而非实测。
- 写终态账本，输出报告，停止。仅当出现截断、SHA 漂移或存在可携带该字段的不同查询时才回到查询分支。

## Stop conditions
- 判定终态 + artifact_reviewed=true + 受理/终态 SHA 一致 + scope 路径与声明一致，四项齐即报告并停止。
- 缺失字段已按签发合同推解并在报告中如实标注推解依据。

## Verification
- 受理回执与终态回执的 candidate_sha256 逐字相同。
- consumable_scope.paths 覆盖任务声明的全部路径，无遗漏。
- 终态回执无截断标记与错误码；报告中所有回执缺失的字段均标注为『按合同推解』，未虚构实测数字。

## Counterexamples
- 回执被截断或尾行不完整（JSON 断在半截、带 truncated 标记）：完整性判别失效，重查或取回完整报告是正当动作。
- 终态回执与受理回执 SHA 漂移或字段相互矛盾：说明状态不稳定或判定侧异常，必须再核而非直接报告。
- 同一闸在其它终态（如 REVISE）回执中确实携带 findings/计数字段而本终态独缺：先怀疑本次回执异常，核对一次仍缺才按合同推解。
- 状态仍为 pending/review_still_running：有界轮询正是协议要求，本方法不适用。
