---
title: method 卡 qualification 通道的断点：写回执能力一直在，断的是回执→lifecycle 执行
scenario: 要提升 method 卡资产消费质量时，先分诊 candidate。2026-10-30 实测全库 1624 张 method 卡：candidate 1569、hold 28、active 23、qualified 1、retired 2。usage.jsonl 全库为 0（usage 账本从未被写过）。有 qualification.jsonl 回执的仅 60 张，全部 evaluator=model 自评、verdict 多数 not_evaluated，其中 51 张带 promotion=pass —— 但这 51 张至今仍是 candidate。
root_cause: ""
solution: |
  断点不在"写回执能力"，而在"回执→lifecycle 的执行环节"：store.record_qualification 与 update_status 都可用且 candidate→qualified 无门槛，lifecycle_attempts.jsonl 仅 1 条历史 blocked 记录（cross_task_type_qualification，属已废止旧规则，当前代码无此门槛）。所以"批量 qualify"技术上零成本，真正的成本是"能否诚实地说这张卡值得用"。
  落库分工必须父子分工：子代理的委派消息带 program_origin=True → is_human_user_message 为假 → current_episode_ref() 为空 → 子代理自己拿不到 episode ref；而 record_qualification 对 promotion=pass 要求 task_ref 以 episode: 开头且独立于该卡 source_episode_refs，模型自造 ref 会被程序拒绝。故：独立子代理出结论，父会话（持真人回合）落回执。
  关键量级修正：store.list() 排序键是 (score, coverage)，status 不进排序键；status 只在分数与 coverage 完全打平时定先后。所以"qualify 改善召回"是错的说法——提升召回靠的是把卡的正文/aliases/Trigger 写好，不是改 status 徽章。分诊口径应优先选"真实 query 命中过"的卡，而非按关键词全库扫描。
evidence: "src/llm_loop/methods/store.py list() 排序键与注释（status deliberately NOT a key）；_update_status_locked 的 \"Explicit no-gate contract\"；record_qualification 对 task_ref 的 episode: 前缀与独立性校验；src/llm_loop/core/loop/events.py _resolve_current_episode_ref 依赖 is_human_user_message；data/methods/lifecycle_attempts.jsonl 仅 1 条 blocked（requested=active, missing_fact=cross_task_type_qualification），当前代码已无该门槛；本轮实测 25 张卡独立评审→落库→1 张转 qualified 全部成功，回执 qualification_episode_ref=episode:cab051cc-...:157:...，磁盘复核 confirmed。"
tags: [method-card, qualification, lifecycle, triage, subagent, knowledge-asset]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T02:05:21.871517+08:00"
updated_at: "2026-10-30T02:05:21.871517+08:00"
---