---
title: spawn_subagent 并发发起会 5 秒超时且不创建 child：须逐个发起并用 topology/child_state 确认
scenario: 需要在一次响应里同时启动多个内容审稿子代理（每轮 2–3 个独立审稿人）。
root_cause: ""
solution: "不要并发发起 spawn_subagent：并发 3 个时三个调用全部返回「执行超时（超过 5s 未完成）」且**实际没有创建 child**（用 subagent_topology(parent_id=…) 实查 active_children=none 确认，不是已创建但回执慢）。改为逐个发起 spawn_subagent（每个调用单独一条消息），三次均正常返回 child_id 与 tool_scope。当前性验证：每次 spawn 后用 subagent_result(child_id=…, wait_seconds=0) 查 child_state=running 即证明 child 已创建；若报 timeout，再用 subagent_topology 确认是否真的没创建，勿把超时当作「已在跑」。"
evidence: docs/promotion/STATUS-20261110-daily76.md 第九节第 3 条（本班三处并发 spawn 全部 5s 超时）；subagent_topology(parent_id=…) 回执 active_children=none，随后逐个 spawn 三次均成功返回 child_id
tags: [子代理, spawn, 超时, 审稿]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-10T09:14:17.955092+08:00"
updated_at: "2026-11-10T09:14:17.955092+08:00"
---