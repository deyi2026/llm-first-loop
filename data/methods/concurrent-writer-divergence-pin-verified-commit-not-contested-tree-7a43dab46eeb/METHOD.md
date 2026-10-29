---
method_id: concurrent-writer-divergence-pin-verified-commit-not-contested-tree-7a43dab46eeb
name: concurrent-writer-divergence-pin-verified-commit-not-contested-tree
description: 持久交接记录（task_state/handoff）写明的发布前置（脏树/暂存/分支）只是当时快照；实时仓库与其不一致时，第一未知量不是'按记录清树'也不是'查清分歧全貌'，而是'快照之后有没有并发写者'。用 reflog/log 时间戳对比快照时间：有快照后新提交即证明并行会话在场，记录里的 blocker 可能已失效，且 stash/checkout 共享主树会干扰他人。改把发布钉死到已验证 commit 的独立 worktree/快照，只核查并发提交是否触及发布内容路径；不相干分歧 flag 给用户，不追查、不代处置、不阻塞。
aliases: 发布前仓库被别的会话动过了, 暂存区文件消失要不要查到底, 交接快照过期怎么判断, 不碰主树用独立worktree部署, 按已验证commit发布不追并行变更
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:2316:2b26dc7886e0883dd932
evidence_refs: learning:learn:7487723f76d7
created_at: 2026-10-29T11:27:31.774347+08:00
updated_at: 2026-10-29T11:27:31.774347+08:00
---
## Trigger
基于 task_state/handoff 等持久记录执行 gated 发布/部署，记录中的前置条件（脏树、暂存文件、分支位置）是历史快照；目标仓库多会话共享，可能有并行会话正在提交或切分支

## Discriminator
实时 status 与记录不一致（暂存区变空、分支/HEAD 漂移）时，立即取 reflog/log 时间戳与记录快照时间对比：快照之后落地的提交就是并发写者在场的可观察证据，一次判'记录过期+共享树不可碰'，把'解释全部分歧'压成'变更是否触及发布内容'一项

## Short path
- 从记录钉死待发布内容的 commit 身份与验证凭证（push 回执/测试结果），不依赖树状态
- 实时核对共享仓 status；与记录不一致 → 查 reflog/log 时间戳，判定快照后变更的提交人与触及路径
- 确认并发写者在场后，放弃任何'清理/避让共享主树'的既定计划（stash/checkout 都算干扰）；只做路径相交核查：快照后提交是否触及待发布内容路径
- 从部署机制的权威源码/测试确认可自固定 commit 的独立 worktree/.releases 快照取树，据此执行发布并绑定 git_head 与产物指纹，全程不触碰共享主树
- 不相干分歧（暂存文件消失、本地 main 超前）写入交付说明 flag，移交用户与并行会话，不追查到底、不代为处置

## Stop conditions
- 部署回执 desired 已固化且 git_head/generation/工件指纹与钉死值一致，共享主树分支/HEAD 未被本会话改动
- 路径相交核查非空：快照后提交触及待发布内容路径 → 停止执行，升级用户裁决发布范围（旧 commit 不再代表完整意图）
- 部署契约不支持独立快照取树 → 退回共享树整理路径，需先与并行会话协调

## Verification
- log --since <快照时间> -- <发布内容路径> 为空，证明并发变更与发布内容不相交
- 回读部署 desired：git_head/generation/webui 工件指纹与钉死 commit 一致
- git worktree list 复核：共享主树仍留在并行会话的分支与 HEAD 上，本会话零改动

## Counterexamples
- 实时树与记录一致（无快照后提交）：记录 blocker 仍真实，按原计划清理即可，无需解耦快照
- 部署机制强制从当前 checkout/工作树取内容、不支持外部快照：必须整理共享树，钉独立 worktree 反而违反部署契约
- 并发提交或消失的暂存内容与待发布改动集重叠：分歧即阻塞，不得拿旧 commit 径直发布
- 用户要的是'最新全部'而非已验证单元：钉旧 commit 会静默丢弃新提交，须先确认发布范围
