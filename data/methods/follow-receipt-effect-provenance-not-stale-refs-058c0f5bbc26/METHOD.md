---
method_id: follow-receipt-effect-provenance-not-stale-refs-058c0f5bbc26
name: follow-receipt-effect-provenance-not-stale-refs
description: 在带版本号的有状态环境（如语义化浏览器）中，mutation 的 action receipt 不只返回 status，往往还携带效果 provenance：before/after 版本号、observed_effects.diff_ref、以及 completeness 警告（如 identity_unstable_objects）。验证动作效果时应把 receipt 当作第一手效果证据：沿 diff_ref 读 created/removed 节点直接定位新对象，而不是整页重拍快照，更不要用 mutation 前采集的旧 ref 去轮询——被标记 identity-unstable 的对象（如被 textContent= 重建的文本节点）在变更后旧 ref 已失效，只会得到 target_not_observed。跨快照观察到的 ref 稳定性不能外推到跨 mutation 场景。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:361:9763ac1237c25c0c6a47
evidence_refs: learning:learn:dcc3e8d9c0f6
created_at: 2026-09-18T03:03:36.200414+00:00
updated_at: 2026-09-18T03:03:36.200414+00:00
---
## Trigger
刚在有状态、带版本的环境中派发了一个 mutation 动作并需要验证其可观察效果，而 receipt 同时给出效果 diff/provenance 引用和 identity 不稳定警告（或预期目标属于动态重建类对象）。

## Discriminator
receipt 中 completeness.reasons 含 identity_unstable_objects，且 observed_effects.diff_ref 给出 before→after 两代之间的精确效果边。它把"如何验证效果"从"重感知整页/对任意属性轮询"缩成"读这两代之间的 diff"。该信号在选择等待目标之前就已可见，其优先级高于"该 ref 在此前两代快照间保持稳定"的经验外推——因为重建节点的是 mutation 而非感知。

## Short path
- 派发 mutation 后先完整读 receipt：记录 before/after 版本、效果 diff 引用、completeness 警告（未知量：动作是否产生效果、落在哪些对象上）。
- 若 receipt 携带效果 diff → 直接水合/读取该 diff，取得 created/removed/changed 对象列表（未知量：变更落在哪个具体对象上）。
- 从 created 列表定位承载预期可观察值的新对象（如新状态文本节点）并读取其属性值（未知量：效果值是否等于预期）。
- 校验该对象 observed_version 与 receipt.after_version 一致且值符合预期 → 效果已验证，停止；不再重拍内容相同的快照。
- 仅当 receipt 无效果 provenance 或 diff 不可读时，才退回重新感知（并对截断输出按 evidence ref 翻页），或对结构性稳定元素（id 持久的 button/input）的属性做 wait。

## Stop conditions
- 已从 diff 派生的新对象上读到预期效果值，且其 observed_version 与 receipt.after_version 一致。
- 新读快照的内容哈希与已读代相同（状态未变）时，不再追加同内容快照。
- 禁止对被标记 identity-unstable 的对象类使用 mutation 前采集的 ref 进行 wait 或寻址。

## Verification
- 效果值来自 diff 派生对象且与预期一致。
- 该对象 observed_version 与 receipt 的 after 版本一致，形成 closed-loop provenance。
- 验证满足后无 post-sufficiency 重复感知（无冗余快照/wait）。

## Counterexamples
- 目标是结构性稳定元素（id 跨变更持久的 button/input）且 receipt 无不稳定警告 → 直接对现有 ref 的属性 wait 更省（本 episode 中 fill 后对 input 属性首采样即 satisfied）。
- 框架以原地绑定更新文本、节点 identity 保持不变 → 旧 ref 仍有效，走 diff 路线无增益。
- receipt 仅是派发回执、不含任何效果 provenance → 无边可沿，必须重新感知。
- 任务目标本身是测试 wait 工具 → 刻意选择 indeterminate 样本属于覆盖性测试，不适用本方法。
