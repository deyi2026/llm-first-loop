---
method_id: serialize-cas-writes-by-chaining-snapshot-refs-65d014ca9b9a
name: serialize-cas-writes-by-chaining-snapshot-refs
description: 当对同一文件的多次编辑所用的写工具是『基于版本基线的条件写』（回执含 expected_snapshot_ref / etag 类前置条件，成功后铸造新 immutable 版本号）时，禁止把多个编辑用同一基线并行批量发出：要么合并为一次多处替换写，要么逐个串行发、每次以上一次成功回执的新版本 ref 作基线。本集首次写回执已完整暴露 CAS 语义，却仍 4 发同基线批量写，导致 3 次必然版本冲突；该语义无需试探即可预判。
aliases: 同一基线并发写必然冲突, 每次拿回执新 ref 接着改, etag 前提写必须排队发, 多处编辑并成一次替换, 改一处撞一处
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:182:b9316e6cbe05c109745b
evidence_refs: learning:learn:fc0559d8442b
created_at: 2026-09-25T12:08:36.120429+00:00
updated_at: 2026-10-23T05:53:07.329989+08:00
---
## Trigger
需要对同一文件连续做 2 处以上编辑，且任一次写回执已显示 file_contract/expected_snapshot_ref（或等价 If-Match/etag）前置条件、写成功会产出新版本 ref

## Discriminator
成功写的回执中 precondition_checked=true 且记录了具体 expected_snapshot_ref，同时铸造新的 immutable snapshot ref——表明写入是 compare-and-swap：同一基线的并发批量写最多一个成功，其余必然『版本冲突、未写入』

## Short path
- 首次写成功后立即读回执：确认基线前置条件与新铸造的版本 ref，判定写路径为串行 CAS（无需试探）
- 若工具支持单次调用多处替换，将剩余编辑合并为一次写并以最新 ref 为基线；否则逐个串行发
- 每次成功后，用回执中的新 ref 作为下一次写的 expected 基线；绝不以同一旧基线并行发多个写
- 冲突回执若出现且非自身批量所致，视为存在并发写者：重读文件重建基线、重估剩余编辑是否仍适用后再续链
- 全部落地后核对完整 diff 行数与计划编辑数一致，再提交

## Stop conditions
- 所有计划编辑均已成功且回执链自洽：每次 expected ref 恰为上一次成功回执的新 ref
- 完整 diff/diffstat 与计划编辑吻合，无部分写入丢失或重复写入
- 冲突回执表明外部并发写者时，停止续链，先重读重建基线

## Verification
- 检查每次写回执的 expected_snapshot_ref 是否恰为上一次成功回执铸造的新 ref（链式无断点）
- 失败回执应为纯版本冲突且未写入任何字节（防护生效、文件未损坏）
- 最终 git diff 与计划编辑数一致，工作树状态符合预期

## Counterexamples
- 写工具为无条件写或内部自动 rebase（回执无 expected 版本前置条件），此时并行批量无害甚至更快，不应套用串行链
- 多次写针对不同文件，各自有独立版本链，可安全并行
- 仅剩一处编辑时无需任何链式或合并处理，直接写
