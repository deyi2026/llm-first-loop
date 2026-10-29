---
title: 生产 record_use 决策遥测缺口：独立产品改动候选（subject-binding reopen 前置条件①）
scenario: "Subject-binding v3 研究线收口审计（2026-10-06）：唯一可落地的生产洞察是\"生产 record_use 遥测缺口\"——真实自然 closeout 回路里 method 使用决策不可观测。"
root_cause: ""
solution: 作为独立小任务排期：在生产 closeout 回路为 record_use 决策（applied/adapted/not_applicable/rejected）增加轻量遥测落点；这同时是 subject-binding 线 reopen 的前置条件①与 method 生命周期治理的数据基础。不与 v3 研究线混合。
evidence: worktree commit 5f0b794f9 AUDIT.md（production value audit 49 行）；main merge b03e89968；本会话 2026-10-06 磁盘复核。
tags: [method-lifecycle, telemetry, record_use, production-observability, subject-binding-reopen-precondition, backlog]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-06T15:49:42.341634+08:00"
updated_at: "2026-10-06T15:49:42.341634+08:00"
---

v3 confirmatory 92/92 审计（evals/method_binding_efficacy_v3/confirmatory_provider_v1/AUDIT.md，commit 5f0b794f9）确认：eval harness 内 record_use 决策完全可观测（92/92 单一成功决策），但生产自然 closeout 回路中该决策不落任何遥测，导致 subject-binding 线 reopen 前置条件①无法在真实流量上核验，且 method 生命周期治理（哪些 method 真被 applied/rejected）缺少数据面。属独立产品改动（engine/telemetry 面），已从 v3 线剥离；reopen 只按审计文件三条件走。v2/v3 worktree 已归档，冻结证据已入 main（b03e89968）。

当前性验证：cd /Users/<user>/Project/llm-first-loop-mirror && git log --oneline -1 应含 b03e89968；grep -n "reopen" evals/method_binding_efficacy_v3/confirmatory_provider_v1/AUDIT.md 应命中前置条件清单；grep -rn "record_use" src/llm_loop/telemetry* 应为空（缺口仍存在）。