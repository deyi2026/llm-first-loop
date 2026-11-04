---
title: 内容审稿子代理必须用精简审稿包+只读该包约束，否则会因上下文爆掉而失败收口
scenario: LFL 推广班次的独立内容审稿：把正文、台账、arXiv 抓取全文、源码行打成一个 ~43k 字符的审稿包交给子代理，子代理仍自行去读 arXiv 抓取全文（1.6 万行）等文件，tokens_in 打到 286k，预检失败、lease 过期，续话被拒，最终没有产出任何审阅结论。
root_cause: ""
solution: 重开子代理时改为：只给一个精简审稿包文件（~40k 字符，只含正文逐字+台账+关键源行+热榜字段+话题页片段+源码行+静态读数），在任务里明令「这是唯一可读文件，禁止再读其它文件、禁止联网」，并要求输出 ≤60 行、不复述原文、每条问题含正文行号。同一班次第二次 spawn 即成功产出 REVISE 9 项（P1 2/P2 7）并自报核对计数与未核对项。
evidence: "docs/promotion/STATUS-20261103-daily56.md 第六节（子代理 subagent_12d05b2f946e 失败收口 vs subagent_98a52d617e2a 产出 REVISE 9 项）；审阅包 receipts/d56review-pack-min.txt（40,270 字符 / 590 行）"
tags: [推广班次, 审稿子代理, 上下文预算, Rule28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-03T13:42:56.358042+08:00"
updated_at: "2026-11-03T13:42:56.358042+08:00"
---