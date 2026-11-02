---
title: 引用论文表格里的括号差值前必须读表题注确认基线（差值可能对 RAG 2 轮而非 1 轮）
scenario: LFL 推广稿件引用 arXiv 论文表格的「低 N 个百分点」类差值。
root_cause: 表格题注里写明了差值的参照基线（RAG (2rd)），而正文只抄了数字、没抄基线，读者默认按上一行（RAG 1 轮）相减即成算术错误。
solution: 引用任何表格差值前，先 grep 该表的题注/说明行确认基线口径并写进正文（如「括号里的差值都是对同一列 RAG（2 轮）的差」）；若题注未写明，就自己按同行数值相减并在正文标明「本文自算」，绝不把差值安到相邻基线上。
evidence: "arXiv:2610.34073v1 表 1 题注（receipts/d54research/arxiv_html_2610.34073v1.txt:288）：\"Cells are shaded in proportion to how far they fall below or rise above RAG (2rd)\"; 本班正文 9 个括号差值经独立审稿逐个相减验证全部对 RAG（2 轮）成立（72.2-31.8=40.4、90.0-63.0=27.0 等）。"
tags: [promotion, arXiv, 表格差值, 基线口径, 审稿]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T20:30:21.915517+08:00"
updated_at: "2026-11-02T20:30:21.915517+08:00"
---