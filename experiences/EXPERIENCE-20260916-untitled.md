---
title: 压缩存活注入必须跨轮持续：瞬态注入在锚点前移后消失，稳态恰是最依赖锚点的时刻
scenario: "LLM runtime 压缩器/窗口构建层做\"压缩存活\"注入类改动（锚点 pinning、快照块、审计字段）"
root_cause: ""
solution: 注入必须在压缩态全程持续（归档轮/锚点>0/marker 折叠/稳态早退四条件），而非仅压缩轮一次性；语义内容（用户消息原文）走锚组保护、程序合成块仅限 durable 事实逐字投影；审计索引沿既有 local→original 映射管线；退化防御沿用 _anchor_protected_groups 体量核查
evidence: "commit 7004b9b8; tests/unit/test_task_anchor_pin_compaction.py::test_steady_state_round_after_compaction_keeps_snapshot_without_reminder; src/llm_loop/core/history.py _maybe_inject_task_anchor_block（注入条件含早退路径）"
tags: [compaction, history, task-anchor, prompt-build, evo-execution]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T15:48:01.674120+08:00"
updated_at: "2026-09-16T15:48:01.674120+08:00"
---

背景: 执行已审批演进 EVO-20260916-ccc978b2（压缩触发时任务锚点强制 pinning）时发现的架构要点。核心洞察: build_history_messages 每轮从 session messages 重建视图，压缩后下一轮 sess.history_anchor 已前移（或 marker 已折叠）——任何只在"压缩发生轮"注入的锚块下一轮必然消失，而压缩后稳态恰是最依赖任务锚点的时刻。落地: (1) 注入条件=本轮归档 OR 锚点>0 OR marker 折叠（_markers_folded 标志），含 total_chars<=compact_limit 早退路径，使锚块在压缩态全程持续在场；(2) 用户消息原文不经合成块（由锚组保护从最后 1 条扩到最近 N 条真实 user 指令解决——原始任务指令常是倒数第 2 条而非最新条），合成块只投影 durable 事实（Goal objective/最近 checkpoint/frontier 单行/evidence 引用），与"程序不合成语义"约束一致；(3) 锚区体量核查遍历 _anchor_protected_groups 本体，扩展保护区自动纳入既有"锚区超窗"退化防御，无需另设防御；(4) 事件审计字段（pinned_msg_seqs_local base 编号）经 projection 段与 cache_compacted 相同的 _map_compacted_source_indices 映射回原 session 序。验证: tests/unit/test_task_anchor_pin_compaction.py 4/4（含稳态轮锚块在场+一次性锚提示不重复+直连默认零回归）；全量 unit 含 engine_loop 回归通过；commit 7004b9b8。