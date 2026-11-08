---
title: 共享 worktree 有他人 staged 未提交文件时，用 merge-tree+commit-tree+update-ref+restore 完成合并而不碰其 index
scenario: "并行会话把未提交文件 staging 在共享 main worktree，直接 git merge 报 \"Your local changes to the following files would be overwritten by merge\"；这些文件不属于当前 lane，既不能丢弃/暂存，也不能替人提交。"
root_cause: git merge 要求待更新路径的 index 与目标树一致；他人 staged-add（index 有、HEAD 无）在合并后的 index 里没有对应条目，git 拒绝覆盖以保护这些未提交工作。共享 worktree 下 stash/pop 或 reset 都会碰他人产物，不可用。
solution: "用 plumbing 绕开被污染的 index，只落地本 lane 路径：①git merge-tree --write-tree <main> <lane> 得合并树 OID，并核它是否等于 lane^{tree}（相同则合并后无新增未验内容，验过的全量结论直接覆盖）；②git commit-tree <tree> -p <main> -p <lane> -F msg 造 --no-ff 合并提交；③git update-ref refs/heads/main <new> <old> 做 CAS 更新；④git restore --source=main --staged --worktree --pathspec-from-file=<本 lane 路径清单> 只把这些路径在 worktree/index 落地；⑤收口核验：git diff --stat main -- <路径清单> 为空、他人 staged 计数不变、main 工作树跑定向测试。全程不 stash、不 reset、不碰他人 index。"
evidence: "main=4e833aaa3（parents cc8b0bc6c + 669779e4f）；main^{tree}=fbb108f6d0 == lane^{tree}；git diff --stat main -- 53 路径 为空；合并后 main 工作树 tests/peer 165 passed/3 skipped；他人 data/methods 46 + experiences 23 个 staged-add 计数合并前后不变"
tags: [git, worktree, lane-merge, index, parallel-session, plumbing]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:11:51.851688+08:00"
updated_at: "2026-11-08T13:11:51.851688+08:00"
---