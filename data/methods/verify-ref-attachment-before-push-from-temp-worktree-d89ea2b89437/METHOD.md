---
method_id: verify-ref-attachment-before-push-from-temp-worktree-d89ea2b89437
name: verify-ref-attachment-before-push-from-temp-worktree
description: 在临时/一次性 worktree 里按提交 SHA 检出 PR head 得到的是 detached HEAD；其上 merge 产生的新提交不落在任何分支 ref 上，随后按分支名 push 只会得到 'Everything up-to-date' 空推送，远端 CI 根本没被新提交触发。方法：在执行任何以分支名为目标的远端操作前，先确认 HEAD 是否挂在分支上（读检出消息措辞或 git branch --show-current）；detached 时改用显式 refspec HEAD:refs/heads/<branch> 推送，并用远端 tip SHA == 本地 HEAD SHA 一次性验证推送真正生效。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:814:eee2884aeecb2e0823cc
evidence_refs: learning:learn:369260edba6f
created_at: 2026-09-19T10:57:33.511925+00:00
updated_at: 2026-09-19T10:57:33.511925+00:00
---
## Trigger
在临时/一次性 worktree（或任何按 SHA 检出的 detached 状态）中完成 merge/rebase/commit 后，准备按分支名 push 到远端，并期望远端基于分支更新触发检查。

## Discriminator
检出时输出为 'HEAD is now at <sha>' 而非 'Switched to branch <name>'；或 git branch --show-current 为空 / git status 显示 '## HEAD (no branch)'。此事实在 merge/push 前已可见，直接推出：本地分支 ref 仍指向旧提交，按名推送不会携带新提交。

## Short path
- 进 worktree 后先 git branch --show-current（或读检出消息措辞）确定 ref 挂载状态；未知量：后续新提交会落在哪个 ref 上？
- 若为空（detached）：git checkout -B <pr-branch> <head-sha> 挂上分支，或记录后续必须用显式 refspec 推送
- 执行 merge main，验证 diff 仍恰为声明的变更集并跑本地门禁
- 推送：detached 情形用 git push <remote> HEAD:refs/heads/<pr-branch>，从回显的 <old>..<new> 区间确认远端确实前进
- 一次验证：远端 refs/heads/<pr-branch> tip SHA == 本地 HEAD SHA，一致才进入等待检查/合并流程

## Stop conditions
- 远端分支 tip SHA 与本地新提交 SHA 一致，且变更集与声明完全吻合，即停止同步动作转入等待检查
- push 被拒且原因为 non-fast-forward（远端又前进）→ 回到同步/合并步骤，而非继续换 refspec 重试
- 仅做本地 merge 可行性验证、不打算推送时，无需处理 detached 状态

## Verification
- 本地刚产生新提交后收到 'Everything up-to-date' 一律视为异常信号：先解释（多半 ref 未挂载或推错 refspec）再继续
- push 后用回显区间或 git ls-remote 取远端 ref tip，与本地 HEAD SHA 比对，不等 CI 就能确认推送生效

## Counterexamples
- worktree 以分支名创建（git worktree add <path> <branch>）或用 gh pr checkout：分支已挂载，按名推送即正确，无需切换 refspec
- 主检出就在目标分支上的常规单仓流程：分支名推送本就正确，套用显式 refspec 属多余步骤
- push 失败原因为权限/网络/non-fast-forward：不是 ref 挂载问题，套用此方法会误诊
