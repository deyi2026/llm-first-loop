---
title: 审稿子代理 spawn 被 worktree 限额阻断：只读审稿可关 fs_isolation 复用共享工作区
scenario: LFL 推广班次的独立内容审稿子代理（minimax/MiniMax-M3.1-Flash，只读 2-3 个文件）；本仓 .worktrees/ 长期积累孤儿树。
root_cause: 程序侧 worktree 供给限额：spawn 需要 fs_isolation=true 时必须新建工作树，而仓库已有孤儿 worktree 占用配额，判定条件只看数量不看你是否复用已有树。
solution: spawn 时 requires 声明 fs_isolation=false（子代理只读审稿包与正文，不需要工作树写隔离）；仍报 worktree 限额则先确认是否需要写隔离，纯只读审稿一律走共享工作区；孤儿树清理保持人工核对（有两棵含未提交改动），不得在班次里顺手删。
evidence: docs/promotion/receipts/d54review-pack.txt（审稿包）；本次两个审稿子代理 subagent_86fa636bc6df / subagent_f5d169d072bb 均在 fs_isolation=false 下完成，reviewer 各 3 次 read_file、rounds=3，PASS 回执见 docs/promotion/STATUS-20261102-daily54.md 第五节。
tags: [promotion, spawn, worktree, 审稿子代理, fs_isolation]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T20:30:21.544367+08:00"
updated_at: "2026-11-02T20:30:21.544367+08:00"
supersedes: [EXPERIENCE-20261031-worktree-孤儿树超限时-审稿子代理改用共享工作区只读模式-别删带未提交改动的树]
---