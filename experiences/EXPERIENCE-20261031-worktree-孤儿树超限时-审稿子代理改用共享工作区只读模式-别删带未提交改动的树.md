---
title: worktree 孤儿树超限时：审稿子代理改用共享工作区只读模式，别删带未提交改动的树
scenario: 需要拉起只读子代理做独立审稿/复核时，宿主 worktree 隔离位被历史孤儿树占满，子代理启动失败。
root_cause: ""
solution: 不要删带未提交改动的孤儿树；改用共享工作区模式（fs_isolation=false + write_scope deny + 只读工具集），并在任务书里显式写「只读、不得修改任何文件」，同时保留独立性（异模型 glm/glm-5.3、非写稿方子会话）。
evidence: 2026-10-31 spawn_subagent 首次失败 WORKTREE_LIMIT（observed=10 孤儿树，上限 8）；worktree 列表与 status 显示其中 2 棵有未提交改动；改 fs_isolation=false + write_scope deny 后两个审稿子代理正常启动并完成，review_admission 宿主 reviewer 也独立通过。
tags: [subagent, worktree, review, isolation, RULE-AI-28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T09:30:41.825578+08:00"
updated_at: "2026-10-31T09:30:41.825578+08:00"
---

场景：2026-10-31 daily-46 需要独立只读审稿子代理，先 spawn(fs_isolation=true) 失败：reason_code=WORKTREE_LIMIT（非活跃孤儿树 10 >= 上限 8），且 .worktrees/ 下有两棵树带未提交改动，不能直接删。处置：审稿子代理改用 requires.fs_isolation=false + requires.write_scope={mode:deny} + 只读工具集（read_file/search_files/execute_command/inspect_code/search_docs），并明确提示「与写稿方共享工作区、严禁写文件」；两轮审稿（REVISE→PASS）全程未产生写入。核对孤儿树是否可删的判据：git worktree list、git -C <tree> status --porcelain、有无当日文件被改、subagent_topology 的 active_children。