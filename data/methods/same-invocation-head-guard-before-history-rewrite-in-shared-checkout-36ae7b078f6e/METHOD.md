---
method_id: same-invocation-head-guard-before-history-rewrite-in-shared-checkout-36ae7b078f6e
name: same-invocation-head-guard-before-history-rewrite-in-shared-checkout
description: 多会话共享同一检出树时，任何早前观察到的 branch/HEAD 都是会过期的断言：并发会话可在你两次工具调用之间 checkout 切换分支。对改写历史的 git 操作（commit --amend、reset、rebase、filter-branch），身份校验必须与改写放进同一条 shell 调用（guard && mutation）；guard 失败即证明目标提交不归本任务：立即零改写退出，把改动迁到隔离 worktree 的自有分支提交，绝不改写当前 HEAD。事故样板：未核对就在共享主树 amend，把本任务一个文件并进另一会话刚切过来的分支提交，只能靠 reflog+reset --soft+restore 抢救。普通新增提交与只读操作不需要此原子 guard。
aliases: 多会话共用仓库 amend 前先确认分支, 共享主树被别的会话切走分支还能 amend 吗, 差点改到别人提交的防呆检查, 改写提交要和查 HEAD 放同一条命令, 共享 checkout 改写历史 TOCTOU 防护
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:2247:babe1a72ed433c0578ed
evidence_refs: learning:learn:58bb04925399
created_at: 2026-10-28T22:28:18.701613+08:00
updated_at: 2026-10-28T22:28:18.701613+08:00
---
## Trigger
在多会话共享的检出树上执行改写历史的 git 操作（amend/reset/rebase/变基式收口），或把提交落到『当前分支』之前；而你对 branch/HEAD 的认知来自更早的工具调用输出，不是本次即将执行的这条命令的输出

## Discriminator
共享树上早前观察的 branch/HEAD 默认视为过期断言。判别动作：把 `git branch --show-current` 与 `git rev-parse HEAD` 的预期比对作为改写命令的前缀 guard 放进同一条调用——guard 通过/失败本身就把『改写的是我的提交』与『改写的是别人的提交』两个世界分开；分两次调用先查后改仍留竞态窗口，不构成判别

## Short path
- 列出本次改写操作的预期目标：预期分支名 + 预期 HEAD sha（取自最近一次观察，默认标注为可能过期）
- 同一条 shell 调用内执行 guard+改写：仅当当前分支与 HEAD 均等于预期时才执行 commit --amend/reset/rebase；任一不等则该调用以零改写退出
- guard 失败时不修复、不切换当前 HEAD：先把工作区改动以 patch/stash 保全，迁到隔离 worktree 的自有分支提交本次改动
- 核验影响面：其它已知活跃分支的 tip hash 不变、reflog 无外来改写条目、本次改动完整落在自有分支提交上

## Stop conditions
- 同调用 guard 全部通过：目标提交确属本任务，执行改写后停止
- 改动已迁至隔离 worktree 的自有分支：后续改写只在自有树进行，本任务在共享树上不再有历史改写操作

## Verification
- 改写前后对每个已知活跃分支执行 `git rev-parse <branch>`，tip hash 必须保持不变
- `git reflog` 中不出现对非自有提交的 amend/reset 条目
- 本次改动 diff/blob 完整存在于自有分支的提交中

## Counterexamples
- 独占树（单会话仓库，或带租约隔离的委派子代理 worktree）：观察不会中途失效，常规两步先查后改即可，原子 guard 只是增加延迟
- 只读或纯新增操作（status/log/diff/普通新 commit）：不改写他人历史，落错分支的后果可温和恢复，不需要原子 guard
- 仓库已配置强制分支守卫的 pre-commit/服务端 hook 时：信任 hook 的拒绝信号即可，不必在每条命令里重复内联 guard
