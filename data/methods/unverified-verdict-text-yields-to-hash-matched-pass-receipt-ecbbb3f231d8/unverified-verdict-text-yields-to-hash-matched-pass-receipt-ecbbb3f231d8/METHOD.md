---
method_id: unverified-verdict-text-yields-to-hash-matched-pass-receipt-ecbbb3f231d8
name: unverified-verdict-text-yields-to-hash-matched-pass-receipt
description: 受管一次性动作（如受管 git push）的回执里，机械闸注记/审计行可能引用未核验的裁决词（REVISE/DENIED）。当该注记自述『仅工具文本、未核验真实子会话、非审查凭据』，且场内已持有与 start 回执哈希一致、artifact_reviewed=true 的验证 PASS 回执并覆盖同一 kind+产物时，验证回执是唯一裁决依据：继续合同允许的剩余核验/报告步骤，不冻结任务、不重启审查、不重复 start。注记行只是观测线索，既不是停止信号也不是放行许可。
aliases: 推送回执冒出拦截字样要不要停, 闸行未核验文本和审查回执矛盾听谁的, 审查已经通过又有提示说没过, 机械注记里的红字算不算真裁决, 消费资格时回执里出现否决词
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:209:5be7be9f689f9c03cdcf
evidence_refs: learning:learn:c6f0baa64566
created_at: 2026-11-19T18:18:15.633830+08:00
updated_at: 2026-11-19T18:18:15.633830+08:00
---
## Trigger
消费一次性审查资格的动作回执中，出现与已验证 PASS 相冲突的未核验裁决文本（如注记里 unverified_verdict_text=REVISE），需要裁决停止还是继续

## Discriminator
两条同时在场的事实：①注记自我声明为未核验观测（『仅工具文本…本行不是审查通过凭据』）；②更早的 status 回执已给出 qualification=PASS、artifact_reviewed=true，且 candidate_sha256 与 start 回执逐字一致、目标产物（推送类 src/remote SHA）与当前动作一致

## Short path
- 读注记原文，确认其自我标记（未核验/仅文本/非凭据）
- 取已持有的审查回执，机械比对 candidate_sha256（start vs status）以及 kind 与产物是否覆盖当前动作
- 覆盖一致 ⇒ 以验证回执裁决：继续合同中仅剩的一次终态核验/报告，不重启审查、不重复 start、不重发动作
- 报告中如实并列注记文本与验证回执两个事实，并写明裁决依据

## Stop conditions
- 本地不存在验证 PASS 回执，或其哈希/child/kind 与当前动作不匹配——本方法不适用，须查询真实审查通道
- REVISE/DENIED 出自真实 review_admission(status) 上下文（带 artifact_reviewed/review_budget 等字段）——按任务合同立即停止

## Verification
- start 与 status 回执的 candidate_sha256 逐字一致且 qualification=PASS、artifact_reviewed=true
- 注记与验证回执指向同一 kind 与同一产物（推送类：src/remote SHA 一致）
- 消费动作恰好执行一次，终态核验独立完成且与凭据目标一致

## Counterexamples
- 裁决词出自真实审查 status 回执（含 artifact_reviewed 上下文）——这是真裁决，必须停止，不得套用『注记让位』
- 尚未取得任何验证 PASS、只有未核验文本——两个方向都不可信，先走权威审查通道，不得据此推进或叫停
- 注记引用的 child/candidate 哈希与本地回执不同——可能指向别的产物，不得拿本回执去覆盖它
