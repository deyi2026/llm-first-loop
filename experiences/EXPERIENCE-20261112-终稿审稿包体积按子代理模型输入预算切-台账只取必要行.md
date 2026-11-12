---
title: 终稿审稿包体积按子代理模型输入预算切：台账只取必要行
scenario: 给 MiniMax-M3.1-Flash 子代理构造终稿审稿包，首版 33404 字符超出该子代理 31698 字符输入上限
root_cause: 审稿包未在生成时按子代理模型输入预算裁剪，把整份台账塞进去导致超限。
solution: 审稿包按「主稿全文 + 机检回执摘要 + 台账必要行 + 论文 summary/comment 逐字原文」组装；台账 117 行不必全放，只放与本班主张直接相关的源码读数行（本班取 16 行），其余由机械审计回执（audit / ledger-index）覆盖。最终 26910 字符。子代理侧要求「只读一个文件一次 + 禁用检索类工具 + 写侧 deny」。
evidence: "本班 d79（2026-11-12）：首版 receipts/d79-review-pkg-final.md 33404 字符（断言 31698 失败），改为台账只取 16 行源码读数行后 26910 字符，独立子代理 subagent_9b5ca9c2db56 正常读取并给出 VERDICT: PASS。"
tags: [审稿包, 子代理预算, context, minimax]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T12:43:48.536018+08:00"
updated_at: "2026-11-12T12:43:48.536018+08:00"
supersedes: [EXPERIENCE-20261109-审稿包体积必须按子代理模型的输入预检预算切分-minimax-m3-1-flash-子代理预算实测]
---

审稿包按「主稿全文 + 机检回执摘要 + 台账必要行 + 论文 summary/comment 逐字原文」组装；台账 117 行不必全放，只放与本班主张直接相关的源码读数行（本班取 16 行），其余由机械审计回执（audit / ledger-index）覆盖。子代理侧要求「只读一个文件一次 + 禁用检索类工具 + 写侧 deny」。当前性验证：造包后跑 `python3 -c "print(len(open('docs/promotion/receipts/d79-review-pkg-final.md').read()))"`，须 ≤ 31698；再跑独立子代理读同一文件，确认给出 VERDICT。