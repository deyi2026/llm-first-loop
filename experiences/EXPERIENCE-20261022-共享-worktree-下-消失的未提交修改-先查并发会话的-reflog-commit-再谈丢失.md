---
title: "共享 worktree 下\"消失的未提交修改\"：先查并发会话的 reflog commit 再谈丢失"
scenario: "多会话共用同一 git worktree 时，一个会话观察到另一个会话的未提交修改\"凭空消失\"（不在工作区、不在 HEAD、不在 stash）"
root_cause: ""
solution: "先查 git reflog --date=iso 同时间窗是否有 commit，再 git branch -a --contains <sha> 定位提交落在哪个分支；本例 7ce5cd99a 被 EVO 会话在 18:01:45 提交到当时被另一会话 checkout 的 release 分支顶端，未推送、未进 main，随后 checkout 回 main 即表现为\"消失\""
evidence: "git reflog 2026-10-22 18:01:45 commit 7ce5cd99a（review_host_admission: push material follows push target + first-upload anchor, EVO-20261022-331eee17）；git branch -a --contains 7ce5cd99a 仅本地 release/ledger-recheck-20261022；merge-base --is-ancestor → NOT_IN_MAIN；event_stream workspace 显示并发会话 4262a65a 于 17:56–18:01 持续编辑该文件并 git add+commit，与会话 7c026852（⑤收口）共享同一 worktree。"
tags: [git, concurrency, worktree, integrity, reflog]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T19:04:19.977008+08:00"
updated_at: "2026-10-22T19:04:19.977008+08:00"
supersedes: [EXPERIENCE-20260919-checkout-git-reset-hard-artifacts-owner-path]
---

现象：某会话报告工作区 17:56 出现的未提交修改（review_host_admission.py ~98 行），18:49 复查时"不在工作区、不在 HEAD、不在 stash"。排查：git reflog --date=iso 显示 18:01:45 有一条针对该文件的 commit（7ce5cd99a，EVO-20261022-331eee17）；git branch -a --contains 定位其只存在于本地 release 分支；merge-base --is-ancestor 确认不在 main。根因：并发会话共享同一 worktree/HEAD，一个会话 checkout 的分支决定了另一个会话 commit 的落点，该提交落在已推送过 PR 的 release 分支顶端（推送发生在提交之前），PR 合并不含它，随后切回 main 即"消失"。适用条件：多会话/多代理共用一个仓库工作区、出现"脏文件凭空消失"类完整性疑点。步骤：1) git reflog --date=iso 找同时间窗 commit；2) git branch -a --contains <sha> 定位；3) 判断是否进入远端/主线；4) 若滞留已合并分支，cherry-pick 到新分支救回。反例：git reset --hard / clean 不留 reflog 痕迹，若 reflog 无 commit 则另查 stash 全量与 event_stream 会话动作轨迹。