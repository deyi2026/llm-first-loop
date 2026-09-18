---
title: 任务启动纪律：过去已完成的任务不重启，未完成任务启动前必须先问用户
scenario: 会话恢复/新会话开始/每轮任务决策时，面对历史任务（已完成的）或未完成任务（task frontier 中 pending/blocked、后台 job、历史 episode）需要决定是否启动执行时。
root_cause: 自动重启历史任务浪费资源、可能产生重复副作用（重复写入/通知/覆盖产物）；任务是否启动/重启的语义决策权在用户，不在模型或程序。
solution: "三条纪律：① 已完成的过去任务一律不重新启动；② 未完成任务需要启动/恢复前，必须先向用户说明并征得明确同意后才执行；③ 任何\"重跑历史任务\"的动作默认视为高影响动作，未经用户授权不执行。可先列出历史任务清单供用户挑选，等确认后再执行。"
evidence: "用户原话（2026-09-02 会话）：\"就是过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起\""
tags: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律, 高影响动作]
source:
  type: user_feedback
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-02T20:02:56.123456+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "rule:RULE-AI-23"
promoted_to_rule: RULE-AI-23
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---