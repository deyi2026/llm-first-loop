---
method_id: opaque-id-provenance-copy-child-id-and-full-sha-from-producing-receipt-170c1bd1e615
name: opaque-id-provenance-copy-child-id-and-full-sha-from-producing-receipt
description: 多 lane 并行的异步审查/子任务会同时产生一组难以区分的 opaque ID（child_id、完整 SHA）：凭记忆引用 ID 会收到 not_owned 类拒收，凭短前缀脑补完整 SHA 会因前缀恰好一致而蒙混通过。规则：opaque 全长 ID 只以回执为权威来源——每次查询前从该 lane 最新 spawn/commit 回执逐字复制；收到 not_owned 拒收先回读回执换 ID，而不是换一条记忆中的候选；短前缀匹配不构成同一性核验。
aliases: subagent id 记错查错人了, 串到别的 lane 的 child id, 短 SHA 前缀一样不是同一个 commit, 查审查子任务先回 spawn 回执拿 id, not_owned 被拒先怀疑 id 拿错
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8d5d9ff-e288-4ad6-8855-48df99c3362e:1490:d80af789f845a7affc3b
evidence_refs: learning:learn:4f2ac062c090
created_at: 2026-11-11T23:05:37.468131+08:00
updated_at: 2026-11-11T23:05:37.468131+08:00
---
## Trigger
要用 opaque 全长 ID（child_id / 完整 SHA）发起状态或核验调用，且上下文中已存在多个同类 ID（并行 lane、多轮重审、多个后台任务）；或某次查询刚返回 reason=…_not_owned / not_found 这类纯标识符层面的拒收。

## Discriminator
每次 accepted 的 spawn/commit 回执都显式携带权威 ID（审查提交回执含 child_id 与 waiting_protocol 字段，artifact 回执含 sha256 字段），且该回执在出错前已出现在上下文中；而记忆中的 ID 无权威性，两个不同的完整 SHA 完全可能共享同一短前缀。

## Short path
- 发起任何 status/verify 调用前，先定位该 lane 最新一次 accepted spawn（或 commit/artifact）回执，从中逐字复制全长 ID；未知量：这个 ID 的权威来源是什么
- 多子并行时维护一行 lane→child_id→来源回执 的微型账本，每轮新 spawn 覆盖旧值，杜绝跨 lane 串号
- 收到 reason=…_not_owned/not_found 拒收时，先判定这是 ID 出处错误而非内容裁决：回读回执重取 ID 重发一次
- 完整 SHA 一律取自产出回执/artifact 记录的 sha256 字段；绝不依据短前缀从记忆补全长
- 回执返回后回核：查询所用 ID 与回执字段一致，且结果是真终态裁决，方可在账本记为已核

## Stop conditions
- 调用所用 ID 与该 lane 最新 spawn 回执逐字节一致，且返回的是内容级终态（PASS/REVISE/DENIED 实质裁决）而非 ID 级拒收
- 回读回执重取 ID 后同一 not_owned 拒收仍复现 → 判定为所有权/会话边界问题并上报，停止轮换其他记忆 ID

## Verification
- 每次 status 查询后回核：child_id 与该 lane 最新 accepted spawn 回执的 child_id 字段逐字节相等
- 任何被使用的完整 SHA（base/head/artifact）与产出回执的 sha256 字段全串比对通过；仅短前缀一致即使用视为未核验

## Counterexamples
- 只有一个异步子且其 ID 就出现在紧邻的上一条回执里 → 直接引用即可，无需回查仪式
- ID 是语义化人类可记名（如 job 名 ci_gate）→ 混淆风险低，记忆加一次回执交叉即可，不必建账本
- 宿主本身提供『列出我拥有的子任务』枚举 action → 直接枚举过滤即得权威 ID，无需自维护账本
