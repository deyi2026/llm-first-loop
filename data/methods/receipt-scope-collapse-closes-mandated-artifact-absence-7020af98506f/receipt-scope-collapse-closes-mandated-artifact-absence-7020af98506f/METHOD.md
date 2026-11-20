---
method_id: receipt-scope-collapse-closes-mandated-artifact-absence-7020af98506f
name: receipt-scope-collapse-closes-mandated-artifact-absence
description: 当任务书指令从准入/审查闸（如 review_admission）取得一个具名产物（如 split_plan），而 accepted 的 start 回执中根本不含该字段，但回执给出了 effective≠requested 的 scope 协商与机器 reason（如未声明 paths→按整树受理）时，回执本身已在合同层裁决该产物不会产生：只需按 waiting_protocol 轮询到 qualification 终态，再逐项报告实际返回字段、明确声明产物缺席、并引用机器 reason 解释成因。不虚构产物，不修改 start 参数（如补传 paths）强行重叫，不为追不存在的字段反复轮询。缺席结论必须建立在完整回执集（start+终态 status）之上；partial/pending 回执不能裁决缺席。
aliases: 准入回执里没有 split_plan, split_plan 没生成, patch 范围变成整树了, 任务书要的产物回执里没有, 返回的范围和请求的不一致, 预检结果和 Host 说的不一样怎么报告
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:c5af189a-3424-4525-9436-3f706df8e72f:107:ae6a4b3398921d9dee15
evidence_refs: learning:learn:231d371c218d
created_at: 2026-11-19T16:54:52.617196+08:00
updated_at: 2026-11-19T16:54:52.617196+08:00
---
## Trigger
任务书指令从准入闸/审查流程取得具名产物（如 split_plan）；accepted 的 start 回执中不含该字段，且回执给出 scope 协商：effective≠requested 加机器 reason。

## Discriminator
accepted 回执中三事并存：①无目标产物字段；②scope.effective 与 scope.requested 不同；③附机器 reason（如未声明 paths→effective=tree 整树受理）。这组事实在首个回执即已出现，足以裁决'产物不会在后续轮询中出现'，后续 status 只回 qualification 不回产物。

## Short path
- 严格按任务书原参调用 start（不为逼出目标产物而增删参数，如不补传 paths）
- 收到 accepted 回执立即查：schema 中是否有目标产物字段；读 scope 协商块（requested/effective/reason）
- 若无产物字段且 effective≠requested 并附机器 reason：裁决缺席为合同定案，仅按 waiting_protocol 继续轮询 qualification 到终态
- 终态后逐项报告实际返回字段＋明确声明目标产物缺席＋引用机器 reason 解释成因＋记录边界（未执行事项）
- 后续动作（是否重声明 paths 走切批准入等）交用户指示，不自行改参重叫

## Stop conditions
- 已收到终态 qualification 且 start＋终态回执集完整、目标产物字段全程缺席
- 缺席声明、scope 协商证据与执行边界已如实报告，等待用户下一步

## Verification
- 缺席声明基于完整回执集（accepted start＋终态 status），而非任何单个 pending/部分回执（受 partial coverage 纪律约束）
- 逐字引用 scope.requested/effective/reason 与候选 SHA 回显，确认核验的是任务冻结的同一准入实例
- 确认轨迹中无虚构产物、无改参重叫 start

## Counterexamples
- 回执仍 pending/审查未完：缺席未定，按协议继续轮询，不得提前宣称不存在
- accepted=false 且 reason 指名缺失字段：走'按 reason 补字段重发'路径，不是缺席报告
- 产物存在但以另一字段名出现在同一回执中：这是 schema 映射问题，直读 schema 报告真实字段，不判缺席
- 任务确需 patch 切批准入且允许传 paths：应重新推导参数后重叫 start；split_plan 缺席在此语境是参数选择问题而非终局
