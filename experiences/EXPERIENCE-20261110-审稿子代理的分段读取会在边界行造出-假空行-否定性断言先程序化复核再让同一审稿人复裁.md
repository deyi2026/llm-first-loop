---
title: 审稿子代理的分段读取会在边界行造出「假空行」：否定性断言先程序化复核再让同一审稿人复裁
scenario: 审稿子代理报「台账缺行 / 文件里有空行 / 数量对不上」，且该结论来自一份较大的包（子代理需要分两段读取）。
root_cause: ""
solution: "先程序化复核再决定改不改稿：把被指认的行在审稿包里逐字读出（该行是否真为空）、统计行数与空值行、核对源文件；程序化复核脚本落盘留回执；若确为子代理分段读取在边界行截断造成的假阳性，用 agent_followup 让**同一审稿人**在明确不切断行的区间重读并复裁，而不是直接改稿。本班实例：第五轮 A2 报 a2 包第 426 行是空 bullet 导致台账缺行，复核显示该行完整为「第 16 行到第 17 行 | …escalation.py:16-17…」，台账 110 数据行与声明一致、无空 bullet，复裁后 PASS。当前性验证（仓库根执行）：python3 -I docs/promotion/_d76_ledger_recheck.py 应得 ledger_data_rows=110、row_count_matches_decl=true、empty_bullet_lines=[]、a2_pkg_line_426_has_content=true。"
evidence: "docs/promotion/STATUS-20261110-daily76.md 第五节第 5 轮；receipts/d76-ledger-recheck.json（ledger_data_rows=110、ledger_declared_rows=110、row_count_matches_decl=true、empty_bullet_lines=[]、a2_pkg_line_426_has_content=true）；子代理 subagent_983e2fa0fb72 复裁后改判 PASS"
tags: [审稿, 假阳性, 分段读取, 台账]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-10T09:14:17.668421+08:00"
updated_at: "2026-11-10T09:14:17.668421+08:00"
supersedes: [EXPERIENCE-20261110-分段读取的边界行会被截断成假空行-否定结论前必须连续覆盖被裁字段]
---