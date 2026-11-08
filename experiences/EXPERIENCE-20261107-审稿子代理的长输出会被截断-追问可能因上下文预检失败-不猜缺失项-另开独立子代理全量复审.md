---
title: 审稿子代理的长输出会被截断，追问可能因上下文预检失败——不猜缺失项，另开独立子代理全量复审
scenario: "LFL 推广第 67 期独立内容审稿：第一轮审稿子代理回执 result_truncated=true（P2 共 8 条，尾部 P2-6/P2-7/P2-8 未完整回传）；对其 agent_followup 追问缺失条目时回执「子代理上下文预检: 最小无损投影仍超过该模型输入容量（预算=30931字符，投影=31493字符）」失败。"
root_cause: ""
solution: "① spawn 审稿子代理时在 task 里就要求「输出务必简洁：每条一行、原文摘录≤30字、为什么≤40字、建议改法≤40字」，并给出固定格式，降低被截断概率；② 回执出现 result_truncated/omitted 时，把被截断的条目一律视为「未知」而不是「不存在」，绝不按印象补写；③ 不要在原子上追问（followup 同样会撞上下文预检），改为新开一个独立子代理做全量复审（本班第二轮即把缺失的 3 条 P2 全部回传）；④ 每一轮审稿后逐条落进修订对照表 receipts/*-review-fixes.md，最后一轮把 P0/P1/P2 计数与 md sha 一起登记，作为下一班的依据。当前性验证：跑 `grep -c \"\" docs/promotion/receipts/d67-review-fixes.md` 应得 27 条编号行（`| 1 |`–`| 27 |`），且 `grep -n \"result_truncated\" docs/promotion/receipts/d67-review-fixes.md` 应能命中第一轮截断记录。"
evidence: "本班回执：subagent_ea6766f505f1（result_truncated=true, omitted=true, recovery_ref=evidence://v1/6b7e99c...）→ agent_followup 回执「子代理上下文预检…投影=31493字符」failed → 新开 subagent_f0615586ea14 全量复审，P2-6/P2-7/P2-9 全部回传；修订对照表 receipts/d67-review-fixes.md（27 条）"
tags: [审稿, 子代理, 输出截断, context]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T08:32:40.047370+08:00"
updated_at: "2026-11-07T08:32:40.047370+08:00"
---