---
title: 审稿覆盖缺口：窄包漏掉图注/尾注时，最后一轮改全文入包而非继续窄审
scenario: LFL 推广班的分级审稿进入 R3（只收 P0/P1）时，窄包漏掉图注与部分尾注条目
root_cause: ""
solution: 最后一轮改全文入包（正文+全部图注+全部尾注+完整摘要原句+台账+机检回执），输出仍只收 P0/P1，并强制给 COVERAGE 行逐项回答
evidence: "receipts/d85-review-pkg-R3.md（24,978 字符全文入包）；R3 子代理回执 COVERAGE 行全 OK；docs/promotion/STATUS-20261114.md 跨班遗留⑬"
tags: [promotion, review, coverage-gap, subagent, plan-d2]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T13:58:20.919544+08:00"
updated_at: "2026-11-14T13:58:20.919544+08:00"
---

场景：LFL 推广班按 PLAN D2 分级审稿——R1 全量审 → R2 窄复审（只送 diff + 改动理由 + 相邻上下文 + 事实类兜底清单）→ R3 起只收 P0/P1。
实测（d85，2026-11-14）：R2 在窄包里明确指出「fig362/fig363 图注与部分尾注条目既不在 diff 也不在兜底清单，本轮无法全量核对」——即窄包无法覆盖审稿任务书里「必须覆盖标题/尾注/图注」的范围要求；这不是等级问题，是覆盖缺口，不能靠再送一轮窄包闭合。
解法：最后一轮改**全文入包**（正文 + 全部图注 + 尾注全部条目 + 论文摘要原句全文 + 台账 + 机检回执），输出仍只收 P0/P1，但第三行强制给 COVERAGE 行（captions/tailnote/title/tags 各 OK 或问题）。d85 该包 24,978 字符，未超子代理输入预算；R3 在 2 轮内收敛 PASS（P0=0 P1=0）。
验证：receipts/d85-review-pkg-R3.md；R3 回执「COVERAGE: captions=OK ; tailnote=OK ; title=OK ; tags=OK」；STATUS-20261114.md 跨班遗留⑬。