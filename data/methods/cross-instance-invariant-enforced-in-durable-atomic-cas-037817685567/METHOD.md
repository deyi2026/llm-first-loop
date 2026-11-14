---
method_id: cross-instance-invariant-enforced-in-durable-atomic-cas-037817685567
name: cross-instance-invariant-enforced-in-durable-atomic-cas
description: 审查方实测嵌套 scope 双进、崩溃未结清债务后 fresh 实例可再入，并要求 single-flight/并发≤1 在嵌套、新实例、跨进程重放下全部成立时：先直读现有 gate 源码看守卫条件的作用域——若检查被实例属性或进程内存守卫（如只在实例首笔前跑一次的旗标、local latch），则嵌套第二笔与新实例按构造绕过，唯一有效 enforcement point 是共享持久状态的原子提交点。做法：在 store.reserve 的 CAS 内、紧邻既有兄弟 profile 门（canary 等）同位点加 gate，键为持久 reservation phase：open（reserved/dispatched/unknown）拒同 kind 新 reserve，terminal（settled/aborted_before_dispatch）放行；不新建账本或锁。每条绕过面复现为具名负测，并用 raw store 直连证明门独立于 execution 层；新门拦下既有正向测试时先对照生产成功路径义务修夹具，不放宽门；外部报告的 lint/type 错误先钉树归属再记录差异。
aliases: single-flight 门放哪层, 嵌套 scope 双进怎么堵, 崩溃债务后新实例还能进, 实例 latch 挡不住第二笔, 防重入落库不新建账本, 物理调用并发一在哪层强制
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:2865:70d18a696f8e32f3d223
evidence_refs: learning:learn:27267cc0be90
created_at: 2026-11-14T07:40:38.478327+08:00
updated_at: 2026-11-14T07:40:38.478327+08:00
---
## Trigger
外部审查/父侧给出绕过实测回执（同实例嵌套双进、崩溃 DISPATCHED 债务后 fresh 执行实例可再入），并明确要求某不变量（single-flight、并发≤1、至多一次物理调用）在嵌套 scope、fresh 实例、崩溃/跨进程重放下都成立，而现有检查只位于 execution/包装层。

## Discriminator
进入实现前已读到的关键事实：现有 liability/skip 检查被实例级条件守卫——源码回执可见『if not first_reservation_done 只在本实例首笔前运行一次』以及 local latch 是进程内存。这一事实本身即裁决：同实例嵌套第二笔、fresh 实例、进程重启都按构造绕过该层，任何只挂在实例生命周期上的门都无法满足需求，enforcement 必须落在共享持久状态的原子提交点（reserve CAS 内读到的持久 phase）。

## Short path
- 从需求文本列全必须拦下的绕过面：同实例嵌套第二笔、崩溃未结清债务、fresh 执行实例、跨进程重放
- 直读现有 gate 源码守卫条件的作用域：实例属性/进程内存守卫 ⇒ 嵌套与新实例按构造绕过，该层不可能满足需求
- 把 enforcement 上移到 store.reserve 的原子 CAS 内、紧邻既有兄弟 profile 门（canary 等）同位点：open 相位（reserved/dispatched/unknown）拒同 kind 新 reserve，terminal（settled/aborted_before_dispatch）放行；不新建账本或新锁
- 每条绕过面逐字复现为具名负测，其中崩溃债务同时用 raw store 直连 + fresh 执行实例双通道证明门独立于 execution 层；串行正向沿用既有 settled 连发测试
- 新门拦下既有正向测试时，先对照生产成功路径义务（成功必须上报 complete 等）修夹具，而不是放宽门
- 全量 lint/type/专项+综合回归；外部报告的 lint 错误先钉树归属（本树全绿则如实记录差异），不追错树

## Stop conditions
- 嵌套 provider/嵌套 tool/崩溃债务 fresh 实例三类负测均有具名拒绝码断言且计数收敛（physical==1、tool==1），串行正测全绿
- 改动只落在既有 CAS gate 位点，零新账本零新锁；外部报错已钉树，不与本地树混淆

## Verification
- 负测断言具体错误码与 reservations 计数，而非只断言抛异常
- crash 债务用 raw store.reserve 与 fresh 执行实例两条路径命中同一持久拒绝，证明门不依赖 execution 层
- 新门拦下的既有正测逐条对照生产代码成功路径义务后修夹具并披露；专项与综合回归零回归、lint/type 本树全绿

## Counterexamples
- 不变量本来就是 per-instance（允许跨实例并发或有意重入）时，实例 latch 是正确且更便宜的实现，上移持久层属过度设计
- 合法并发上限 >1（如允许 ≤2 in-flight）时，门必须比较 in-flight 计数与上限，而非存在性拒绝，否则破坏合法并行
- 嵌套 scope 语义是重用外层同一 reservation（re-entrancy attach）时，应按 reservation_id 去重附同一票据，而不是拒掉内层 reserve
- CAS 热路径不允许 O(n) 扫全量 phase 时，应在同一事务内维护 in-flight 计数索引，而不是因性能退回实例层守卫
