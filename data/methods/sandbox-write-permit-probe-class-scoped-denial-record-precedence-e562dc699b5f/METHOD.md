---
method_id: sandbox-write-permit-probe-class-scoped-denial-record-precedence-e562dc699b5f
name: sandbox-write-permit-probe-class-scoped-denial-record-precedence
description: 沙箱已声明受限写面（如仅工作区+缓存目录）时，判断能否在目标仓库做 commit/merge 级 git 写入，先做路径算术（该操作要写的锁文件/ORIG_HEAD/worktrees 元数据落在哪个可写根下），再谈探针。一次通过的探针只证明它实际触碰的那一类路径（如 tag 增删≈refs 写）可写，不能外推到提交/合并所需的锁文件类；恢复状态里记录过的同类拒绝（『worktree add 成功过但 commit 锁被拒』）优先于新探针的通过，不该被改判为『临时冲突』。据此直接把会产生提交的合并放进可写根内自含 .git 的场地完成，交给受管 publish 物化到运行树——部署目标本就不必写原仓 .git。避免合并中途被拒留下半成品 worktree 与整体换场重做。
aliases: git 探针过了但 merge 还是被拒, tag 建删成功就能放心提交吗, 沙箱探针假阳性怎么裁决, 上次的写拒绝是不是临时冲突, 合并不碰主仓也能上线吗, worktree 合并中途被拒怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4210:88f898ebdad3ce26ee17
evidence_refs: learning:learn:7f6f9fc62e86
created_at: 2026-10-26T06:08:44.862497+08:00
updated_at: 2026-10-26T06:08:44.862497+08:00
---
## Trigger
沙箱回执声明受限可写根；任务需要在可写性存疑的仓库里执行会产生锁文件/refs 写的 commit/merge 级 git 操作（常见于恢复的合并-重启计划）；手头有先前同类写入的拒绝记录，且/或刚做过一次通过的写探针。

## Discriminator
三条当时已在场的事实：①每条命令回执明文的可写根清单 vs 计划写入点（index.lock、ORIG_HEAD、.git/worktrees/*）的路径前缀；②恢复状态/历史回执中对目标写类的明确拒绝（如 worktree 建得成但 commit 锁文件被拒）；③新探针实际触碰的路径类（tag 增删只写 refs/tags）。若②中被拒的写类正是本次操作所需，而③通过的是另一类路径，则探针通过不构成放行证据——探针结果按路径类作用域生效，同类拒绝记录优先于异类探针通过。

## Short path
- 对计划中每个 git 写动作做路径算术：列出它要写的元数据文件，判定落在声明可写根内还是外；存在面外写入即不选原仓作场地。
- 核对该写类是否有先前拒绝记录；有、且新探针未触碰同类路径时，按不可写处置：不改判为临时冲突、不重试原路径、不中途换形式硬闯。
- 在可写根内的自含 .git 场地（clone/拷贝）完成合并：从权威仓 fetch 最新目标 ref，merge-tree 预检后执行合并，跑准入+全量门。
- 若存在受管 publish/部署管线会把产物物化到运行树（.releases/ 等），把验证过的产物交 publish 推进 desired generation，再走 restart——全程不写原仓 .git。
- 只有路径算术含糊（探针与操作同类却结果矛盾）时，才用与操作同类的最小探针（如该场地空 commit）做最终裁决。

## Stop conditions
- 合并产物已在可写场地通过门禁并经受管 publish 发布（回执含 git_head/code_root/generation），restart 已受理；不再尝试写目标仓 .git。
- 若任务真义是推进共享 ref 本身且无 publish 物化通道：停下走提权/人工协调，不在可写区单方面造平行历史。

## Verification
- 复盘每个被拒路径是否都在声明可写面之外、每个通过的探针是否只触碰了异类路径（refs 写 vs 锁文件写）。
- 部署事实（publish 回执的 git_head/code_root、live 版本）与合并产物一致，且方案不依赖任何对原仓 .git 的成功写入。
- 无遗留半合并 worktree/锁文件残留需要事后协调清理。

## Counterexamples
- 目标 .git 整体位于声明可写根内且无同类拒绝记录：直接在原仓执行即可，无需换场地或预飞探针。
- 先前拒绝源自组合命令误拦（如管道进解释器被硬拦），本次是单用途命令：该拒绝类不适用，用单命令探针裁决即可。
- 探针与计划操作触碰同类路径且都通过（如都只写 refs）：一次通过足以放行该类操作，不必再换场地。
- 没有受管 publish、且必须移动共享 ref 才算完成：可写区合并不满足目标，应提权/协调人工，而非把『不碰原仓』当成已完成。
