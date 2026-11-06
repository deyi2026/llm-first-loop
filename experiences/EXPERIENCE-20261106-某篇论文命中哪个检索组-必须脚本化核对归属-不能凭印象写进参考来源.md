---
title: 「某篇论文命中哪个检索组」必须脚本化核对归属，不能凭印象写进参考来源
scenario: LFL 推广班次写参考来源时凭印象写「2611.05650 与 2610.38392 出现在 self-evolving agent 组，2611.06682 与 2611.06039 出现在 tool use safety / MCP security 组」，第四轮审稿要求核验归属时才用脚本从 arxiv_queries.jsonl 反查，真实归属是：2611.05650v1 在 q5_context_longhorizon（38 条）、2611.06682v1/2611.06039v1/2611.04879v2 在 q7_agent_prompt_injection（27 条）、2610.38392v1 在 q9_agent_self_improve（9 条）与 q2_self_evolution_retry（19 条）——初稿的归属三处全错。
root_cause: ""
solution: 写脚本从检索原始回执（arxiv_queries.jsonl）逐组遍历、按论文编号反查全部命中组，生成「论文→命中组→该组窗口内条数」的归属映射，落盘进审稿包与台账；正文参考来源的归属句按脚本输出改写，审稿时让子代理按同一映射核对。另注意初版映射脚本用 break 提前退出，只能给出每个论文的第一个命中组，必须遍历全部组后再下结论。
evidence: receipts/d64research/arxiv_queries.jsonl；receipts/d64-review-pkg2.md 第七节；receipts/d64-review-fixes.md 第 17 行；主稿参考来源第 6 条最终文本
tags: [arXiv, 检索归属, 脚本化核对, 事实诚实]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T08:33:20.607876+08:00"
updated_at: "2026-11-06T08:33:20.607876+08:00"
---