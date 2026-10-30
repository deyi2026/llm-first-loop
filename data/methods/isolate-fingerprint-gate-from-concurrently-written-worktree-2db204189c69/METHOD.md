---
method_id: isolate-fingerprint-gate-from-concurrently-written-worktree-2db204189c69
name: isolate-fingerprint-gate-from-concurrently-written-worktree
description: 快照/指纹型准入闸门（指纹含工作树、未跟踪文件或 mtime）遇到并发写者共享主工作区时，共享面上冻结的值在核验时刻必然漂移，清理或等待都救不回。判别：同一只读面两次观测不一致（status 计数 25→26、staged diff 在两次调用间消失、src/tests 出现 3 分钟内新 mtime）。做法：不要在主工作区枚举性排查污染源（ignore 覆盖、引用 grep、反复 recount），直接在拟推提交处物化隔离 worktree 跑闸——delta 恰为拟推提交、树全干净、漂移构造性消失；过审推送后用 ls-remote（而非本地 tracking ref）核验远端。
aliases: 指纹一直变怎么过审推送, 别人还在改代码我这边要推送怎么办, 冻结到别人WIP就换副本跑门禁, 共享仓库推送审查去干净副本跑, 未跟踪文件计数在涨 推送准入漂移
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:3896:76ecfc841986669e077f
evidence_refs: learning:learn:296df40a1090
created_at: 2026-10-30T16:41:17.112347+08:00
updated_at: 2026-10-30T16:41:17.112347+08:00
---
## Trigger
带快照/指纹语义的准入或审查闸门（指纹覆盖工作树状态、未跟踪文件或 mtime）需要在多会话共享的主工作区执行，且同一只读面的两次廉价观测结果不一致（status 计数变化、staged diff 消失、src/tests 出现新鲜 mtime），即并发写者正在改写指纹覆盖面。

## Discriminator
对同一只读面（git status 计数、staged diff、最近几分钟 mtime）做两次观测并比对：结果不同 ⇒ 并发写者活跃且写入落在指纹覆盖面内 ⇒ 任何在共享工作区冻结的指纹在核验时都会失效——该结论在动手清理/排查前就已成立，无需再枚举污染源属性。

## Short path
- 续跑/接手后只用 git 证据定当前任务面：log 带时间戳 + status + 本地与远端差，得出剩余动作（如推送 N 个提交）
- 对同一只读面做两次观测比对：计数、staged、mtime 任一变化即判定并发写者活跃且影响指纹
- 闸门指纹含工作树 ⇒ 直接结论：主工作区跑闸必漂移；跳过对共享面的清理与排查（ignore 覆盖检查、引用 grep、反复 recount）
- 在拟推提交处物化隔离 worktree 并 checkout 到目标 SHA，在其中跑准入：delta 恰为拟推提交、工作树全干净
- 审查 PASS → 推送 → 用 ls-remote 核验远端 tip 是否包含拟推提交（本地 tracking ref 可能因 .git 锁权限滞后，不可作依据）

## Stop conditions
- 隔离副本内闸门冻结指纹重算与冻结值逐字段一致，且独立审查 PASS
- ls-remote 确认远端 ref 已含拟推提交，闭环完成
- 两次只读观测完全一致且无并发写者 ⇒ 不需隔离，直接在主工作区过闸

## Verification
- 隔离副本的 delta 清单 == 拟推提交清单，且其工作树 status 为空
- 用闸门自身的重算逻辑复核指纹，确认与冻结值一致
- 推送后 git ls-remote origin <ref> 的 SHA 包含本地拟推 HEAD，而非只看本地 tracking

## Counterexamples
- 单会话仓库、两次观测一致：主工作区直接过闸即可，隔离反而增加成本与分叉风险
- 拟推内容仍是未提交 WIP：在 HEAD 处隔离会审批错误范围，必须先在主工作区提交再隔离
- 并发写者只写指纹排除路径（已 ignore 的 data/* 等运行时目录）：漂移不影响闸门，无需隔离
- 闸门语义只审计提交内容、不含工作树指纹：直接在当前分支过闸，隔离无收益
