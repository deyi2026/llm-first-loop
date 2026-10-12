---
title: 主仓 checkout 分支≠main：提交前必须核 git branch --show-current，main 落点走 worktree cherry-pick
scenario: llm-first-loop-mirror 多 worktree 结构：主 checkout（runtime root）可能停在任务分支（本次实测停在 evo-20260914-exec-surface-followup，且该分支已含他人未进 main 的提交 7766dbe1e），而 main 被 .worktrees/smc-subject-v01 占用。若凭 git log 内容（与 main 同步）想当然认定在 main，直接 commit 会落在任务分支上，且 cherry-pick 落 main 时容易把他人未合并提交一并 ff 进 main。
root_cause: ""
solution: 提交前先 git branch --show-current + git branch -v 核对落点；若当前分支≠main 且 main 被 worktree 占用：在任务分支上完成提交与全部验证 → git -C .worktrees/<main-worktree> cherry-pick <sha>（前提：目标提交与他人未合并提交无文件交集，git show --stat 核对）→ cmp 逐字节核验 main 落点与已验证代码一致。不要 git checkout main（被 worktree 占用会失败）；不要把任务分支 ff 进 main 以免夹带。任务分支上留下的 cherry-pick 重复提交（按 patch-id 等价）留给后续合并时处理，不擅自 reset 他人分支。
evidence: "TASK-003 P0-C：主 checkout 实测在 evo-20260914-exec-surface-followup@79d9b8cb8（git checkout main 失败\"smc-subject-v01 已用于 worktree main\"）；git -C .worktrees/smc-subject-v01 cherry-pick 79d9b8cb8 成功得 main=4327d5ee2；7/7 文件 cmp MATCH（主树 vs main worktree）；7766dbe1e（tools/measure_method_sampling.py 等 2 文件）确认与改动零交集未被夹带。"
tags: [git, worktree, main, cherry-pick, deployment-readiness]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T02:46:18.914462+08:00"
updated_at: "2026-09-19T02:46:18.914462+08:00"
supersedes: [EXPERIENCE-20260911-worktree-git-checkout-stash-pop]
---