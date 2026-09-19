---
title: worktree 逐提交归因循环中 git checkout - 导致 stash pop 冲突的修复与预防
scenario: git worktree 中循环 checkout 旧提交做逐提交测试归因（A/B 红集合对比、bisect），期间工作区有未提交改动需 stash，跑完要回到原分支继续
root_cause: ""
solution: "①循环结束回原分支必须用显式分支名（git checkout fix/xxx），不要用 git checkout -（@{-1} 在循环后指向最后一个被测提交，stash pop 在错误基线冲突成 UU）；②pop 冲突时 stash 条目保留：reset --hard 清冲突 → checkout 显式分支 → 重新 pop；③untracked 验证用 stash@{0}^3:path 而非 stash@{0}:path；④在共享 worktree 做任何 checkout 前先确认无正在运行的该目录后台 pytest，否则其结果被污染需重跑"
evidence: "job_output job-857c92977e7441f69291 / job-17d3da967fcc4946965d 红清单；git stash list 显示 pop 冲突保留条目；git show 'stash@{0}^3:src/llm_loop/core/prefix_unit.py' diff 验证 UNTRACKED-IDENTICAL；job-a724fb0d95664ac79ff7 终验因运行中 checkout 污染作废重跑（job-6a380b66be7b473693d3）"
tags: [git, worktree, bisect, stash, 归因, checkout-hygiene]
source: {}
status: active
created_at: "2026-09-11T00:35:40.440234+08:00"
updated_at: "2026-09-11T00:35:40.440234+08:00"
---

1. 在 worktree 中循环 checkout 旧提交做归因时，最后一步必须 `git checkout <显式分支名>`，绝不用 `git checkout -`（其语义是 @{-1}=最后一次 checkout 的位置，循环后即最后一个被测提交）。
2. stash pop 冲突时 stash 条目不会删除，tracked 部分可能已 apply：先用 `git show 'stash@{0}:path'` 验证 tracked、`git show 'stash@{0}^3:path'` 验证 untracked（`-u` 存的 untracked 在第三 parent，直接 stash@{0}:path 会报 not in stash），与磁盘 diff 一致后才 reset --hard 清理冲突并 drop。
3. 在共享 worktree 上任何 checkout/reset 前先查后台任务（job_output）——正在该目录跑的 pytest 会读到中途被切换的文件版本，结果作废需重跑。