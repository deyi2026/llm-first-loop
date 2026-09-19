---
method_id: verify-mutation-via-receipt-diff-not-stale-refs-9ef7f363fc03
name: verify-mutation-via-receipt-diff-not-stale-refs
description: 对可变世界执行 mutate 类动作后，不要拿动作前的对象 ref 去轮询验证。回执本身已携带最权威的下一跳：observed_effects.diff_ref（前后世界差分）与 completeness.reasons 中的 identity_unstable_objects 警告。正确闭环是：读回执 -> 沿 diff_ref 读差分 -> 对 diff.created 的新对象做断言。旧 ref 上的谓词只会得到诚实的 indeterminate（property_unobserved / target_not_observed），白白消耗两次无信息调用。该方法把验证从『猜哪个对象/属性还能用』缩成『按回执指向读一个权威差分』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:456:b1d095d98e1c12030103
evidence_refs: learning:learn:74f9a4698250
created_at: 2026-09-18T03:21:24.023102+00:00
updated_at: 2026-09-18T03:21:24.023102+00:00
---
## Trigger
在对象身份随 DOM 变更而不稳定的可变世界里，一次 mutate 动作（click/fill 等）返回 ok 回执，且回执带有 diff/效果 provenance 或 identity_unstable_objects 标记，需要验证动作真实效果时。

## Discriminator
回执当时已包含两个可直接使用的事实：(1) completeness.reasons 含 identity_unstable_objects——旧对象 id 在变更后可能失效；(2) observed_effects.diff_ref 给出 before→after 的权威差分引用。另外初始快照中已可见段落对象只投影 state.exists、文本内容在子 StaticText 对象的 name 里（段落不投影 value_text）。这三个事实在第一次失败等待之前就已全部在场。

## Short path
- 派发动作，读回执；未知量：动作是否产生预期效果。status:ok 只是机械事实，不进入验证。
- 检查回执标志：发现 identity_unstable_objects + diff_ref -> 判定旧 ref 不可作为验证目标，diff_ref 是第一验证跳。
- 读 diff_ref 对应差分；未知量：世界具体怎么变？得到 created/removed 列表（旧文本对象被删、新对象被建）。
- 对 diff.created 中的新文本对象做 hydrate/谓词，断言期望值（如 name contains clicks=1）。
- 断言 satisfied 且目标 id 属于 after_version 世界 -> 验证闭环，停止，不回访任何旧 ref。

## Stop conditions
- 期望效果已在新对象/新快照上断言 satisfied，且目标 id 出现在 diff.created（或属于回执 after_version）。
- 回执无任何不稳定标记且目标属性为原地更新（如稳定投影的 value_text）：直接谓词原 ref 即可，无需 diff。
- diff 不可比或不完整（scope 变化、boundary_detector_non_exhaustive）：改为重新 snapshot 重建 grounding 后再断言。

## Verification
- 谓词目标的 id 必须属于动作后的世界（∈ diff.created 或 after_version 快照），不得是 before_version 的旧 id。
- 断言使用的 observed_version 与回执 after_version 一致。
- 断言值与用户预期的效果语义一致（不只是回执 status:ok）。
- 若收到 rejected: duplicate_action_id，重新 snapshot 取新 ref 再派发，而不是重试旧 ref。

## Counterexamples
- 对象原地更新且投影完整（如 fill 后 textbox 的 value_text 稳定存在）：直接对原 ref 谓词更省，先读 diff 反而绕远。
- 非 mutate 动作（纯 wait/navigate 跨 scope）：前后快照 scope_relation 不同、diff 不可比，应走新 snapshot + 谓词。
- 静态页面或动作未引起 DOM 变更：diff 为空，谓词原 ref 即为正确路径，本方法不适用。
- 回执不含任何效果 provenance 字段的系统：无 diff_ref 可沿，只能 snapshot 后断言，本方法的判别事实不存在。
