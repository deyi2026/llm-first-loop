---
method_id: pin-live-remote-tip-before-computing-push-set-8c4373cef87e
name: pin-live-remote-tip-before-computing-push-set
description: 远端 tracking ref 只是上次观测的本地缓存，不是远端现状。要对外推既有共享 ref（算待推集合、领先/落后、快进判断）而缓存有陈旧信号（隔轮数小时、存在并发推手、或沙箱禁止写 .git 致 fetch 无法刷新 ref）时，第一未知量是远端当前 tip：用不写任何本地 ref 的 ls-remote <url> refs/heads/<branch> 直读真值，一切 delta 从真值 tip 重算。审查闸回执里的 remote_commit 是一份免费的远端真值样本：与本地 tracking ref 冲突时先假设缓存滞后，用祖先包含关系裁决，而不是先假设远端被回退。
aliases: push 前先查远端真实 tip 别信本地领先数, 领先提交数虚高的假象, fetch 被沙箱拦了怎么拿远端状态, 回执里的远端 commit 跟本地记录对不上, 远端 main 是不是被人回退了, 隔了几小时还拿上次的状态算待推清单
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:3255:fbc1b603616063785873
evidence_refs: learning:learn:c19f3011e659
created_at: 2026-10-29T18:10:45.479061+08:00
updated_at: 2026-10-29T18:10:45.479061+08:00
---
## Trigger
在回执声明仅允许写工作区/缓存目录的沙箱里准备 push 共享远端既有 ref（如 main），需要给出待推提交集或 ahead/behind 结论；或隔轮/隔小时后基于本地 remote-tracking ref 复核远端状态；或闸回执的 remote commit 与本地 tracking ref tip 不一致

## Discriminator
三条当时即可见、无需未来知识的信号：1) 每条工具回执都标注沙箱仅允许写工作区与缓存目录，而 worktree 的 .git 位于父目录——remote-tracking ref 根本无法刷新，fetch 也会被拒；2) 开局自己承认『距上轮已过数小时 state 可能变化』却仍用本地 ref 下『事实复核通过』结论；3) 闸回执的 push_remote_commit ≠ 本地 tracking ref tip。任一成立即判缓存不可信，真值只能来自不写 ref 的网络读

## Short path
- 接到 push 指令：先 ls-remote 直读远端目标 ref 当前 tip（网络未隔离、不写本地任何 ref），解决唯一先决未知量『远端现在在哪』
- 用 merge-base --is-ancestor 判定真值 tip 与本地 HEAD 拓扑：祖先关系成立→快进可行、待推集=<live-tip>..HEAD；分叉→改走分支/PR 路径；live-tip==HEAD→no-op 直接报告不付闸成本
- 从真值 tip 重算的待推清单与闸回执冻结的提交集核对一致后，再让审查闸启动/结算
- push 执行用 workdir 参数，避免复合 cd 命令被宿主准入拦截
- 推后单次 ls-remote 验证远端 SHA==HEAD 即收口；同时明确记录本地 tracking ref 仍冻结在旧值，本会话后续不再引用它报领先/落后数

## Stop conditions
- 远端 tip 已由一次 ls-remote 直读并与闸回执、推送结果闭环（推后 SHA==HEAD），即停止，不再做祖先/IN-remote/reflog 考古
- 拓扑为分叉或 no-op 时按各自分支收口，不做快进推

## Verification
- 推后 ls-remote 得到的远端 SHA 等于本地 HEAD
- 待推清单从 live tip 重算后与闸回执冻结提交集一致
- 在非沙箱 fetch 修复 tracking ref 之前，不再从本地 tracking ref 向用户报任何领先/落后数字

## Counterexamples
- 刚在同一会话 fetch/push 完成、无并发写入者的单人参仓库：tracking ref 是新鲜缓存，再 ls-remote 是无谓网络往返
- 网络被完全隔离且只有本地镜像 remote 可读时：真值通道是镜像 tip 直读，不是 ls-remote
- 只回答本地状态（HEAD、脏文件、diff）的问题与远端真值无关，不需要网络查询
- 若 tracking ref 比回执 remote commit 更新、且 reflog 显示其后有一次成功 push，则『远端真被回退』才是待验证假设——用同一包含关系测试对称裁决，不单向默认缓存滞后
