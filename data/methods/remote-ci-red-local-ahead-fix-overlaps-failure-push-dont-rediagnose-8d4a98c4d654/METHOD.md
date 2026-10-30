---
method_id: remote-ci-red-local-ahead-fix-overlaps-failure-push-dont-rediagnose-8d4a98c4d654
name: remote-ci-red-local-ahead-fix-overlaps-failure-push-dont-rediagnose
description: 远端默认分支 CI 连续红、本地 git 回执却显示 main ahead ≥1 时，先别开新诊断：把失败 run 点名的具名测试与 implicated 文件、同 ahead 提交的 diffstat、以及在含修复本地树上按 CI 原命令重跑该具名测试的结果（ratchet 基线两侧登记值一致）三者对表。吻合即证明红测量的是『没有修复的旧树』，下一步是走既有推送管道（flush 积压知识→push 闸→push→ls-remote 核对→盯新 run），而非重新排查或另写修复。任一不吻合则分流：diff 无交集=独立新失败；本地仍红=修复不足；非严格后代或基线漂移=并发写者介入，先重测差距。
aliases: 本地绿远端红怎么归因, CI红了但修复还没推上去, ahead 1 的提交对上 CI 失败文件就直接推, 远端门禁红要不要重新排查, push 就能回绿的判断条件
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:4312:9f9a473fda1a587ce057
evidence_refs: learning:learn:c76e5d05fd93
created_at: 2026-10-30T16:34:54.784004+08:00
updated_at: 2026-10-30T16:34:54.784004+08:00
---
## Trigger
远端默认分支 CI 连续红（状态/CI 查询可见），同时本地 git 回执显示本地 main 领先 origin/main（ahead ≥1），且当前任务是决定下一步动作（修什么/推不推/要不要诊断）

## Discriminator
同轮已可见的三事实合取：(a) 失败 run 日志点名的唯一失败测试及其 implicated 文件/符号；(b) ahead 提交的 diffstat 恰好触及该文件；(c) 在含修复的本地树上按 CI 同名命令跑该具名测试 PASS，且 ratchet 基线登记值本地=远端。合取成立即可把『新 bug 诊断』的候选空间缩成『红在等那笔未推提交』

## Short path
- 一条 git 回执取分叉事实：本地 tip vs origin tip、ahead 数、ahead 提交信息与改动文件
- 一条 CI 回执取失败身份：failing job → step → 具名测试与 implicated 文件/符号（其余 job 是否全绿作为排除信号）
- 未知量①：show --stat 核对 ahead 提交是否触及 implicated 文件；触及 → 假设『红=缺推送』
- 未知量②：在含修复的本地树按 CI 原命令只跑该具名测试；PASS 且基线登记值两侧一致 → 假设成立
- 成立则不开新诊断：flush 积压知识 → 走 push 闸 → push → ls-remote 核对远端 tip → 盯新 run 回绿

## Stop conditions
- ls-remote 确认远端 tip == 本地 tip，且新 run 中该具名失败测试退出失败清单
- 任一判别事实（diff 交集 / 本地具名测试绿 / 基线一致 / 严格后代关系）不成立，即停止『推送即修复』归因，转入对应分支

## Verification
- 推送后对新 SHA 的 run 核对具名失败症状是否消失——整体 conclusion 可能因其他 job 仍红，症状退出才是修复生效判据
- 推送前核对本地树是远端失败 tip 的严格后代，且 ratchet/基线登记值两侧一致

## Counterexamples
- 本地 ahead 但 ahead 提交与失败文件无交集：推送不会让该红消失，需独立诊断该失败
- 本地树不是远端失败 tip 的严格后代（并发写者另行插入提交）：本地 PASS 失去证明力，先重测差距再归因
- 失败是 flaky/超时/环境依赖而非代码差异：push 归因不成立，需在触发 SHA 上复现归因
- ratchet 基线本地与远端登记值不一致：先解释基线漂移（并发写者），不能拿本地绿灯当证据
