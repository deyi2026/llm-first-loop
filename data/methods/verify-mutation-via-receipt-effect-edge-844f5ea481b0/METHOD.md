---
method_id: verify-mutation-via-receipt-effect-edge-844f5ea481b0
name: verify-mutation-via-receipt-effect-edge
description: 变更型动作回执 status:ok 只是机械事实。验证效果时，先消费回执自带的因果边：observed_effects.diff_ref / after 版本 objects_ref / completeness.reasons。用 diff 定位哪个对象承载了新状态，再水合读取其值；不要先对变更前的旧对象 id 和猜测属性做盲谓词轮询。本 episode 中回执的 identity_unstable_objects 警告与 diff_ref 在第一次失败的 wait 之前就已存在，足以把验证路径从『旧 id × 多属性盲试』缩为『读 diff → 定位 created 对象 → 水合』，省去两次必然 indeterminate 的轮询等待。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:456:b1d095d98e1c12030103
evidence_refs: learning:learn:74f9a4698250
created_at: 2026-09-18T03:21:29.444751+00:00
updated_at: 2026-09-18T03:21:29.444751+00:00
---
## Trigger
动作回执为 ok 且同时携带 observed_effects.diff_ref（或 before/after 版本 grounding_refs）以及 completeness.reasons 警告（如 identity_unstable_objects），此时需要验证动作是否产生了预期效果

## Discriminator
点击回执里当时已经可见三件事：(1) observed_effects.diff_ref 直接指向前后两版的净差异；(2) completeness.reasons 含 identity_unstable_objects，明确预告旧对象 id 可能失效；(3) 动作前快照的对象卡已显示段落类对象不投影 value_text（文本在子 StaticText 的 name 里，输入类才有 value）。这三条把候选验证方式缩到『沿 diff 找 created 对象再水合』这一条

## Short path
- 动作回执 ok 后先读回执字段：未知量=世界从哪一版变到哪一版、哪些对象受影响、身份是否稳定
- 沿回执 diff_ref / after objects_ref 读取 created/removed/changed 列表：未知量=新状态文本由哪个对象承载（旧 id 若在 removed 中即弃用）
- 水合 created/changed 中的对象读取新值：未知量=目标断言的具体内容（如 clicks=1）
- 仅当效果是异步/延迟出现，或回执不提供任何效果边时，才对 after 版本中身份稳定、且快照对象卡证明其确实投影该属性的对象做 wait 谓词轮询

## Stop conditions
- 已从出现在回执 diff 的 created/changed 列表中的对象读到目标效果值，且与动作意图匹配（before→after 版本链一致）
- diff 为空且无异步迹象 → 判定动作未产生预期效果，转入排障，而不是继续换目标/换属性盲试
- wait 谓词返回 satisfied（而非 indeterminate/target_not_observed/property_unobserved）且 target 在 after 版本中存在

## Verification
- 最终读到的对象 id 必须出现在回执 diff 的 created 或 changed 列表中，且其 observed_version 与回执 after_version 一致
- 若必须用谓词等待：确认 target 存在于 after 版本快照、该属性在此类对象的对象卡中被投影过、predicate_result.result 为 satisfied
- 诚实失败信号（property_unobserved / target_not_observed / indeterminate）连续出现一次即应切换到 diff 路径，而不是换下一个猜测继续轮询

## Counterexamples
- 效果异步且晚于动作边界（如点击后数秒由网络驱动更新）：动作即时 diff 可能为空，应 wait 轮询身份稳定的对象，而非据空 diff 判定失败
- 回执不提供任何效果边（只读操作或平台不返回 observed_effects）：只能 fresh snapshot / 谓词验证，diff 路径不存在
- 目标对象身份稳定且明确投影目标属性（如输入框的 value_text 回读）：一次直接谓词等待比 diff+水合两跳更短，不应机械走 diff
