---
title: 任务启动纪律：历史任务不自动重启
scenario: 会话恢复/新会话开始时，面对已完成的历史任务或未完成任务（task frontier、后台 job）的启动决策
root_cause: 自动重启历史任务浪费资源且可能产生非预期副作用；重启决策权在用户
solution: 已完成的过去任务一律不重新启动；未完成任务需启动/恢复时，必须先询问用户并获明确同意
evidence: 过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起
tags: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律]
source:
  kind: user_instruction
  statement: 过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起
  legacy_format: shell_written_markdown
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-02T15:20:34.191557Z"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "rule:RULE-AI-23"
promoted_to_rule: RULE-AI-23
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

# 任务启动纪律：历史任务不自动重启
- **scenario**: 会话恢复/新会话开始时，面对已完成的历史任务或未完成任务（task frontier、后台 job）的启动决策
- **rule**: 已完成的过去任务一律不重新启动；未完成任务需启动/恢复时，必须先询问用户并获明确同意
- **root_cause**: 自动重启历史任务浪费资源且可能产生非预期副作用；重启决策权在用户
- **tags**: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律]
- **source**: 用户本会话原话："过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起"
- **note**: save_experience 通道因死循环病理未触达，本文件为 shell 直写副本
