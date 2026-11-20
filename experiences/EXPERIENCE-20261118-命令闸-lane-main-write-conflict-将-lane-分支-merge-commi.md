---
title: 命令闸 lane_main_write_conflict 将 lane 分支 merge commit 误判为 main 直写——无合法放行入口，PR61 集成 HOLD（P1 待安全审查）
scenario: PR61 隔离集成（worktree=<repo>/.worktrees/multiagent-final-closure-20261117，branch=feat/multiagent-final-closure-20261117，lane-067ce5bb 本会话 own）：git merge --no-ff e9507bd9 解决 2 个 Host 冲突后执行 git commit --no-edit，被 execute_command 命令闸以 lane_main_write_conflict 拒绝（理由：存在他人 live lane lane-94405afe open v1）。物理事实：该 commit 仅前进 feature 分支（HEAD=bf479eccee，merge parents=bf479eccee+e9507bd9），不触碰 main ref。受管替代路径全部不可用：lane_open 同 branch 被一对一约束拒绝（branch 已被 lane-067ce5bb 占用）；回执豁免形态（git commit -- receipts/verification 路径）不适用于 9 文件集成提交；等待 lane-94405afe 收口不可控（M0-A 停滞候选）。
root_cause: 命令闸 main 直写保护为保守一刀切：他人 live lane 存在时拒绝所有非回执路径 git commit，无「会话↔lane↔branch/worktree 绑定」归属感知；合法 lane 分支 commit 与真 main 直写未被区分。
solution: "按主统筹 2026-11-18T10:28 指令：立即停止提交尝试（不用改命令写法/git -C/手改 ledger/强推/伪造路径绕过，不提 escalation）；git merge --abort 恢复 clean（实测 HEAD=bf479eccee、porcelain=0、MERGE_HEAD CLEARED）；保留 lane CAS v7 9 路径声明；本 lesson 登记 P1 待安全审查。修复建议：命令闸增加 lane 归属感知（校验会话为该 lane owner 且 commit 目标=该 lane worktree 分支时放行），或提供显式分支 commit 人工审批入口；修复前 PR61 新基线集成（merge 方案已验证：冲突面恰为 2 Host 文件 take main blob 逐位一致、tools_merge_queue auto-merge、A.5 manifest 待移除 host-gate-p1-closure 组件）处于 HOLD。"
evidence: "回执链：execute_command merge commit 被拒 lane_main_write_conflict（2026-11-18T10:2x）；lane_open constraint_violation branch 已被在途 lane 占用 lane-067ce5bb；data/audit/lanes.jsonl lane-94405afe status=open v1；git merge --abort 后 HEAD=bf479eccee/porcelain=0/MERGE_HEAD CLEARED。"
tags: [command-gate, lane_main_write_conflict, PR61, P1-pending-security-review, merge-integration-hold]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-18T10:29:54.547638+08:00"
updated_at: "2026-11-18T10:29:54.547638+08:00"
---