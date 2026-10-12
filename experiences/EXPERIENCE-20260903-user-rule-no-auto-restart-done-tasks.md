---
title: 用户规则：已完成的任务禁止自动重启，未完成任务重启前必须征得用户确认
scenario: "会话恢复/后台任务/task 账本/goal-checkpoint 存在 done 或历史任务时，AI 或程序试图自动重启、继续或恢复执行（用户原话：\"过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起\"）。"
root_cause: 自动恢复历史任务绕过用户意图：重复已完成工作、产生意外副作用、消耗预算；重启决策权在用户，不在模型或程序。
solution: "1) 程序守卫（已落地）：task_store.update 对 done→in_progress/done→failed 转移要求 confirm=true，否则 ValueError(\"禁止自动重启…须先向用户征得明确批准\")；tools_task.run_task_update schema 暴露 confirm 参数并把用户规则写进 description。2) AI 行为约定：恢复任何历史/未完成任务前先向用户说明现状并等明确批准；已完成任务只能告知\"已做过\"，不得自动重跑。"
evidence: "src/llm_loop/introspection/task_store.py（confirm 守卫）；tests/unit/test_task_store.py::test_done_reopen_requires_user_confirm / test_confirm_guard_does_not_affect_normal_transitions 全绿"
tags: [user-rule, task-lifecycle, guard, confirm-gate]
source: {}
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-03T00:29:03+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "rule:RULE-AI-23"
promoted_to_rule: RULE-AI-23
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

# 用户规则：已完成任务禁止自动重启

## 规则原文
"过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起。"

## 落地物
- task_store.update confirm 守卫（done 重开/转 failed 需 confirm=true）
- run_task_update 工具 schema confirm 参数 + 规则描述注入
- 测试：tests/unit/test_task_store.py 两条守卫用例
