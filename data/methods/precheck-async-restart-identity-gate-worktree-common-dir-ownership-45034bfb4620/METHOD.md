---
method_id: precheck-async-restart-identity-gate-worktree-common-dir-ownership-45034bfb4620
name: precheck-async-restart-identity-gate-worktree-common-dir-ownership
description: restart 属两阶段延迟异步执行、且控制面存在无 override 出口的身份门（code_root 与 runtime 必须同一 git-common-dir）时，发布回执 accepted 只证明 desired 绑定，不证明执行期门会通过：因主仓 .git 临时拒写而把合并/release 物化成外部自含仓派生的 worktree，会在数小时后窗口打开时被身份门拒绝（rc=2/stage_fact=not_started，物理重启从未发生）。发布时即用一条 git worktree list / 读 .git gitdir 比对 code_root 与 runtime 的 common-dir，并 cat-file 确认目标 commit 在主树对象库；不一致则 fetch 导对象、主树 worktree add --detach 重建、复核 HEAD/common-dir/clean 后再按契约（含 target）受理 restart，终态以 status(action_id) 为准。
aliases: 重启被身份门拒绝怎么修, 受理成功但重启失败要预检什么, release worktree 挂错仓库, 外部仓合并的提交导回主仓, 延迟执行的重启前置条件检查, worktree 归属不一致重建
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4279:cd0d5a1a4ca3abba4c99
evidence_refs: learning:learn:0b253fda973e
created_at: 2026-10-26T06:18:18.759435+08:00
updated_at: 2026-10-26T06:18:18.759435+08:00
---
## Trigger
受管发布链中 restart 为延迟异步执行（受理后等窗口再执行），且存在身份类前置门、无 override 出口；此前因权威仓 .git 临时拒写，把合并/release 物化成了外部自含仓库派生的 worktree（如 .releases/<hash>）

## Discriminator
发布时即可见的三件事：code_root 的 .git gitdir（或 git worktree list）显示的 git-common-dir 是否等于 runtime 主树 .git；主树对象库 cat-file 是否含目标 commit；历史成功重启（如当前 live 代的 code_root）均为主树 worktree。受理回执只覆盖 desired 绑定，不覆盖执行期门——这三条任一不满足即预示窗口打开时必拒。

## Short path
- 发布/受理 restart 前做同步预检：一条 git worktree list（或读 .releases/<hash>/.git 的 gitdir）比对 code_root 与 runtime 的 git-common-dir，git cat-file -t <目标hash> 验对象在主树库
- common-dir 不一致或对象缺失 → 该异步动作必被身份门拒：先重测主仓可写性（一条 fetch 即探针，昨夜拒写常为临时态），git fetch <外部仓> <branch> 把目标 commit 导入主树对象库
- 移除错向 worktree（外部仓侧元数据残留报 Operation not permitted 不阻塞，后置 prune），在主树 git worktree add --detach .releases/<hash> <hash> 以主树为 common 重建
- 复核三件实测：HEAD=目标 hash、git-common-dir=主树 .git、工作树 clean（对应身份门全部检查项），再按参数契约完整字段（如 target=all）受理 restart
- 终态异步核对：status(action_id) 或 service_action_terminal 检索；failed 终态保留待确认，受理不得当作完成宣布

## Stop conditions
- code_root 与 runtime 的 git-common-dir 一致、目标 commit 已在主树对象库、工作树 clean
- restart 受理返回 action_id，且随后 status 显示三服务 live git_head=desired、restart 回执 succeeded

## Verification
- 重建后三项实测：HEAD=目标 hash、common-dir=主树 .git、git status clean
- 重发后 audit action_trace 无新的 dual_root_rejected/not_started；若仍失败按 rc+stage_fact 分流：not_started=precheck 门拒绝（detail 字段路由到门源码逐条核对），started 后失败=运行时/超时分支

## Counterexamples
- 身份门有 override 出口或部署为单根（无 dual_root 校验）：归属不一致走 override/环境清理即可，重建 worktree 属过度修复
- 失败发生在 stage_fact=started 之后（超时、锁占用、进程启动失败）：属运行时问题，与 worktree 归属无关
- code_root 本就是独立部署仓（非主仓 worktree 派生），身份门比较的是其他属性（路径/指纹），common-dir 比对不适用
- 主树对象库已含目标 commit：跳过 fetch，直接删错向 worktree 重建
