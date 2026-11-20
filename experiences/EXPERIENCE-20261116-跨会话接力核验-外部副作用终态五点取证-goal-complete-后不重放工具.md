---
title: 跨会话接力核验：外部副作用终态五点取证（Goal complete 后不重放工具）
scenario: 接手一个已由他会话收口（Goal status=complete）的跨会话接力快照，需要在不重放来源会话未结算工具的前提下，判定外部副作用是否真的闭合
root_cause: 接力快照里的“已完成/已通过”多为历史陈述，来源会话当时的工具回执未复制；若直接沿用声明或重放工具，会造成重复执行与虚假完成
solution: "不重放来源工具，改做五处只读取证：①Goal/Task 真值（get_goal/task_frontier，确认 status=complete、无开放 Task）；②Git 终态（真实 git fetch origin 后比对 origin/main 与 PR merge commit、gh pr view 状态=merged）；③CI 终态（gh run view 核对 status=completed/conclusion=success 且 headSha 等于精确 merge SHA）；④lane 账本终态（读 data/audit/lanes.jsonl，同 id 取最后一行，确认目标 Goal 全部 lane=merged，并另核分支内容是否已在 main：git log origin/main..branch 为空且 diff 为空）；⑤运行态终态（service_control status 看 alive/matches_desired_generation/in_flight/barrier，判断 docs-only 增量是否免重启）。再对 spec_archive 的 result_doc 做 blob 级核对（本地文件 git hash-object == origin/main:path 的 blob），避免“登记了相对路径但内容不是 main 真值”。结论只报已取证事实，残留项（他 Goal 的 PR/lane、他人 inbox 请求、本地 detached 旧检出）只列不擅动。"
evidence: 本次实测（2026-11-16）：git fetch origin 后 origin/main=9edfa3481ebe4a33d5278a4e9ae0e40de5f1e8f6；gh pr view 50 → state=MERGED mergeCommit=9edfa3481；gh run view 43881101984 → status=completed/conclusion=success/headSha=9edfa3481；data/audit/lanes.jsonl 中 GOAL-20261116-d83c9c53 的 5 条 lane 末行 status 均为 merged；git log origin/main..origin/feat/w1-board-version-strip-20261116 为空且 diff 为空；service_control status 四服务 alive 且 matches_desired_generation=true、in_flight/orphan_barrier 为空；result_doc 本地 blob=8942c069 与 origin/main 同路径 blob 一致。
tags: [cross-session-handoff, verification, terminal-state, git, lane-ledger, service-control]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-16T22:25:41.947934+08:00"
updated_at: "2026-11-16T22:25:41.947934+08:00"
supersedes: [EXPERIENCE-20261112-接管跨会话发布任务-用-info-v2-快路径独立复核公网终态-跨会话-goal-收口路径, EXPERIENCE-20261101-接力后先验外部副作用终态-reflog-回执-ls-remote-工作树四源交叉-再决定是否重开推送]
---