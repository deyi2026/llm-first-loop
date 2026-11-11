---
method_id: coverage-union-ledger-closes-spanned-reads-892d4c6ed64e
name: coverage-union-ledger-closes-spanned-reads
description: 对同一内容标识（blob_sha256）且带 range 元数据（start/count/next_start/complete）的来源做分段读取时，为每条回执维护已覆盖区间并集：complete:true 且并集连续无缺口即读取闭环。此后起草答案、需要引用具体数字/原句时，第一个动作是在当前上下文已收到的回执文本中定位，而不是对已覆盖区间再次取段——同 run、同 blob 身份的重取是零信息动作。本集 6 次调用中 2 次（start 3800、2500）完全落在已覆盖并集内，机械 duplicate 计数为 0 未能拦截此类重叠取段。
aliases: 读过的段落别再拉一遍, 怎么判断长文分段读完了, 引用数字先翻上下文再取段, 重复取段是零信息, 取段去重防冗余
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:03972ab0-752f-4a25-8900-9e61b4f93a68:2:41a8b4a32a0ebf5e2530
evidence_refs: learning:learn:9dad0ac116a8
created_at: 2026-11-11T21:52:23.001680+08:00
updated_at: 2026-11-11T21:52:23.001680+08:00
---
## Trigger
对同一 blob/长文按 span 分页读取（回执含 start/next_start/complete 与内容身份），且在覆盖已闭环之后进入起草/引用阶段，出现对早前已读区间再次发起读取的冲动或调用。

## Discriminator
发起下一次分段读取前可机械判定的三件事实：(1) 目标 start 是否落在已收回执区间 [start, start+count) 的并集内；(2) 同一 blob_sha256 下是否还存在 next_start 非空的未读缺口；(3) complete 是否已为 true。三者齐备时，区间内重取的信息增量为零。

## Short path
- 每收到一条分段回执，登记 (blob_sha256, [start, start+count))，用 next_start/complete 推出剩余未读区间
- 起草中需要引用某数字/原句时，先解决『它是否已在当前上下文的回执正文里』这一未知量——纯上下文内定位，不发工具调用
- 定位失败且目标确在未读缺口内，才以缺口边界为 start 发起一次读取
- complete:true 且并集连续无缺口即关闭读取阶段，后续所有引用回指已收回执的区间

## Stop conditions
- 同一 blob 的覆盖并集连续、complete:true、next_start 为空
- 答案所需的全部引用点均可在已收到回执文本中定位

## Verification
- 抽查最终答案中每个数字/引句：其所在字符位置应落在某条已收回执的 [start, start+count) 内
- 回看调用序列：不应存在 start 落在既有覆盖并集内部的取段调用，除非 blob 身份（sha/版本）发生变化

## Counterexamples
- 长会话或上下文压缩后，早前回执正文已不在当前上下文——此时有界锚点段落重取是必要的（这正是 reconsult-held-files-by-bounded-span 的适用域），判别点是所需段落是否仍可在当前上下文检索到
- 来源 volatile 且发生了新的抓取（acquired_at/blob_sha256 变化）——旧覆盖账本作废，重读并非零信息
- 回执缺少 range/complete 元数据、总长未知——无法闭环覆盖账本，须先探测边界，不能直接判定已读完
