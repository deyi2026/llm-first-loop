---
method_id: sandbox-eperm-blocked-path-reveals-write-target-reanchor-git-24f498303748
name: sandbox-eperm-blocked-path-reveals-write-target-reanchor-git
description: 沙箱内 git 写操作失败且回执为确定性 EPERM（Operation not permitted）时，stderr 里被挡文件的绝对路径本身就是答案：它标出该操作真实要写的元数据位置（如 git worktree 的元数据在主仓 .git/worktrees/<name>/ 下，不在 worktree cwd 内），而沙箱写域按 cwd/workdir 锚定。EPERM 是边界不是瞬时错误：原样重试必然再败，转向反复检索经验卡正文也是扩散。正确做法是把 git 调用重锚到能覆盖该元数据路径的写域——以主仓根为 workdir、显式 GIT_DIR/GIT_WORK_TREE 指向目标 worktree（或走任务授权的非隔离通道），随后用 status --porcelain 验证改动面只剩预期条目，再继续 commit/checker/push。
aliases: git add 报 Operation not permitted 怎么办, index.lock 创建不了被沙箱挡住, worktree 的 git 元数据其实在主仓 .git 下面, 沙箱里 commit 不上去 换 workdir 试试, EPERM 还原样重试就是白费一轮, GIT_DIR 加 GIT_WORK_TREE 指回 worktree 提交
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ac770e54-e409-4936-9ad6-d191455efb75:0:5052360dbc725d0c6159
evidence_refs: learning:learn:ec7c612b6ea0
created_at: 2026-11-13T19:18:02.781716+08:00
updated_at: 2026-11-13T19:18:02.781716+08:00
---
## Trigger
在按 cwd/workdir 限定写域的沙箱里执行 git add/commit 等写操作，失败回执为 Operation not permitted 且 stderr 打出被挡文件的绝对路径

## Discriminator
解析被挡路径的位置与错误类别：路径位于当前 cwd 写域之外（说明操作的真实写目标在别处，如 worktree 元数据在主仓 .git/worktrees/ 下），且错误是 EPERM 而非 EEXIST/锁竞争/超时——确定性边界意味着 verbatim 重试和等待都无效，路径已给出重锚目标

## Short path
- EPERM 失败后先做一件事：把被挡绝对路径与当前 cwd/沙箱写域比对，确认这是写域边界而非瞬时错误；是确定性边界则禁止原样重试
- 由路径推出操作的真实写目标位置；不转去反复检索经验库正文（回执未随卡返回正文时，现场错误已是更快权威）
- 重锚调用：以能覆盖该元数据路径的目录为 workdir，显式 GIT_DIR（必要时加 GIT_WORK_TREE）指向目标 worktree；或按任务授权改用非隔离执行通道完成该 git 操作
- 验证爆炸半径：git status --porcelain 只含预期的单个条目，确认未触碰同仓其它 checkout 的未提交资产
- 回到既定流程：commit → 对照最终 HEAD 跑 checker → push → 用 ls-remote 核对远端 SHA（沙箱可能让本地 remote-tracking ref 不更新，不能以本地 ref 为准）

## Stop conditions
- 重锚后同一条 git 写命令 exit 0，且 porcelain 清单与预期条目完全一致
- 重锚后仍 EPERM：说明写目标受保护是有意设计，停止绕行，改走副本/暂存区方案

## Verification
- 重发失败命令前自问：上次错误是否确定性 EPERM？是则不允许 verbatim 重试
- 重锚成功判定：git add/commit 在新 workdir+GIT_DIR 下 exit 0，且 porcelain 只有预期单条目
- push 后以 ls-remote 的远端 SHA 为准，不信任沙箱内可能滞后的本地 tracking ref

## Counterexamples
- EPERM 路径在 cwd 之内（属主/只读挂载问题）：重锚 workdir 无用，应修权限或对该文件授权
- 错误是 index.lock 已存在（EEXIST/另一 git 进程持锁）：等待或清锁后重试正当，判别键是错误类别而非路径本身
- 沙箱禁止写 .git 是刻意的只读保护：重锚绕过写域违背安全意图，应在副本/暂存区完成后走授权通道
- 经验卡正文可一次水合且任务明确要求先查卡：先水合再动手仍正确；本方法只适用于卡正文取不回而现场错误已含判别信息的情形
