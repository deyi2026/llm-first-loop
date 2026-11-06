---
title: 并行会话 lane 全链路（开发→全量门禁→人工合并→push）的可复用路径与三个坑
scenario: 并行会话协同开发中，需要把一个功能修复 lane 从开发一路带到推送到 origin/main：队列 verify 层未启用、main 被并行会话持续推进、审查闸随产物 sha 变化反复失效
root_cause: ""
solution: 按先例走通完整链路：红→绿→4 轮 full_test 审查→ci_gate 全量→合并审查回执→--no-ff 人工合并→S1 回执回填→verify 凭证签发→git_push 审查→推送；产物每次变化后重过闸，绝不复用旧 PASS
evidence: merge f7c09f06c + push 411270248 均有审计事件与回执文件；4 轮 full_test + 2 轮 git_push 审查记录在 data/review_admission/
tags: [lane, parallel, merge-gate, review-admission, ci-gate]
source:
  goal_id: GOAL-20261106-cfaf140a
  lane: lane-5af8407a
  merge_commit: f7c09f06c
  pushed: 411270248
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T15:13:37.777395+08:00"
updated_at: "2026-11-06T15:13:37.777395+08:00"
---

链路：lane_open(sub) → worktree（.venv/node_modules 软链锚定）→ 红测试冻结 → 修复 → review_admission(full_test) PASS → bash scripts/ci_gate.sh（exit 0）→ 合并审查 PASS 回执 → 主仓 merge --no-ff → S1 回执回填 → verify 凭证签发（EVO-20261106-7782d438 签发者）→ review_admission(git_push) PASS → push。关键点：(1) 每次产物变化（含 lint/baseline 提交）都会使审查资格失效，重过闸；(2) queue verify 层恒 fail 时按先例 40c16d39b 走人工临界区；(3) ci_gate 的 tier0 预检在并发会话同时跑测试时曾出现收集异常（1 passed/51 deselected）——非提交门禁，全量第 5 步才是权威，定性后如实登记不豁免；(4) review_admission status 报 review_child_not_owned 时去掉 previous_child_id 重 start 即可。