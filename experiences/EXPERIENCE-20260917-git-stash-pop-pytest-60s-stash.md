---
title: git stash/pop 不得跨长时 pytest 边界——工具 60s 超时导致改动滞留 stash
scenario: 演进实施后做回归基线对比（stash 本轮改动→跑全量测试→pop 恢复）时，stash 与 pop 被 60s 工具超时截断在长测试中间
root_cause: execute_command 60s 超时截断命令链，位于 pytest（长任务）之后的 git stash pop 未执行；命令链把状态变更（stash）与长耗时验证（全量测试）串在同一条原子命令里
solution: 永远不把 git stash / stash pop 与超过数秒的 pytest 全量运行放在同一条命令链；基线对比改为：单文件秒级 stash 验证、或 `git stash push -- <明确文件列表>` 缩小滞留面、或 git worktree 隔离；每次 stash 系操作后单独跑 git status --short 核对目标文件 M 状态再继续
evidence: "execute_command 超时回执（13:39 会话）；git stash list 显示 stash@{0} 基线 832b4dfa；git stash pop 后 git status 恢复 5 文件（4M+1??）；同会话后续改用 `git stash push -- <4文件>` 秒级验证 proc_version 基线未再复现"
tags: [git, stash, execute_command, timeout, baseline-compare, evolution]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T15:13:30.139477+08:00"
updated_at: "2026-09-17T15:13:30.139477+08:00"
---

在 LFL 环境对 git 工作区做演进实施时，曾把 `git stash -q && python3 -m pytest <全量测试> ... ; git stash pop -q` 合并为一条 execute_command。全量测试超 60s 工具超时，pytest 被中断且 stash pop 未执行，5 个改动文件滞留 stash@{0}，git status 只剩未跟踪文件，极易误判改动丢失或被后续操作覆盖。恢复方式：git stash list 确认条目（对比 stash 描述行基线 commit）→ git stash pop → git status 验证 M 文件回归。经验教训：①跨长测试的基线对比应拆为独立命令，或用 git worktree/`git stash push -- <明确路径>` 最小化滞留面；②单文件级对比（秒级）才可接受 stash 边界；③任何 stash 操作后立即 grep git status 验证目标文件 M 状态，不依赖命令链尾。