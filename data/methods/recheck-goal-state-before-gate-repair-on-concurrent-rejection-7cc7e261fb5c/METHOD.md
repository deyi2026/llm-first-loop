---
method_id: recheck-goal-state-before-gate-repair-on-concurrent-rejection-7cc7e261fb5c
name: recheck-goal-state-before-gate-repair-on-concurrent-rejection
description: 审查/准入闸限定的写动作（如 git push）被拒、且拒绝根因指认共享工作树或远端正被并发写者改动（资格指纹漂移、他人未提交改动在飞）时，不要先投入根因诊断与补救（重开准入、建隔离 worktree）：拆掉你资格的并发写者很可能同时已把目标完成。被拒后第一个未知量是『任务目标是否仍存在』——fetch/ls-remote 取权威远端真值，用祖先包含判定目标提交是否已入远端；已入则停止补救并报告，未入才修闸。
aliases: 推送被拒先看远端是不是已经推上去了, 资格失效先确认任务还存在, 别的会话把我要推的提交推了, 被拒后先fetch再决定要不要补救, 闸被拒先查目标态再修
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:3377:4af84f7c860c641de72d
evidence_refs: learning:learn:d4fad8d700fb
created_at: 2026-10-30T16:45:04.040316+08:00
updated_at: 2026-10-30T16:45:04.040316+08:00
---
## Trigger
准入/门禁限定的写动作（如审查闸下的 git push）被 Host 拒绝，且拒绝原因或同批观测指认共享状态正被并发写者改动：资格指纹含共享工作树且在漂移、他人未提交改动在飞、他方会话此前有推送同一远端的历史

## Discriminator
invalidator 与 satisfier 是同一批并发写者：使你资格脱钩的他方会话同样有能力（且已有历史）推送同一共享远端；而本地 tracking ref 只是上次观测的缓存，他方 push 只有 fetch 之后才可见。因此『被拒且根因指向并发改动』这条回执本身就是重测目标态的信号，而不是先修自己准入路径的信号。

## Short path
- 被拒后暂停闸故障诊断：先 fetch 刷新（或 ls-remote 直读）权威远端 tip，一切判定基于刷新后的真值而非本地缓存 ref
- 对目标提交做祖先包含判定（branch -r --contains <target> 或刷新后的 rev-list 计数）：目标是否已在远端？
- 已含目标 → 任务作废：不重开准入、不建补救 worktree，按 SHA 祖先证据报告并停止
- 未含目标 → 才进入闸修复（如冻结产物含共享工作树 → 改在 detached 于目标提交的干净 worktree 冻结），且修复后推送执行前再取一次真值

## Stop conditions
- 目标提交已验证为刷新后权威远端 tip 的祖先（本会话 fetch/ls-remote 的观测，非旧 tracking ref）
- 确认他人不具备满足目标的能力（如仅本会话持有的全新私有分支），可径直修复重试

## Verification
- 复查判定所用的远端 tip 来源是 fetch/ls-remote 真值而非本地 tracking ref
- 报告中的 ahead/behind 与 contains 结果在刷新后的 ref 上重算一致
- 若走了修复分支，推送动作执行前再核一次远端真值未再前进

## Counterexamples
- 拒绝是纯本地确定性缺陷（复合命令需拆分、远端 URL/凭据写错）且无任何并发信号：直接按自描述错误码修复重试，不必前置远端复查
- 目标是只有本会话可写的全新私有分支：他方不可能替你完成目标，跳过目标态复查
- 远端不可达/离线取不到真值：按本地证据先修复，恢复可达后再核对目标态
