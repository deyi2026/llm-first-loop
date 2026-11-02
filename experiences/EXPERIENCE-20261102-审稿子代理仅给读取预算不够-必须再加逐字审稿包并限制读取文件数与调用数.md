---
title: 审稿子代理仅给读取预算不够——必须再加逐字审稿包并限制读取文件数与调用数
scenario: LFL 推广班次的独立内容审稿子代理（MiniMax-M3.1-Flash）：首次 spawn 时只给了「读取预算 + 文件数上限 + 单文件 limit」，子代理仍读了 10+ 个文件、消耗 189K tokens，触发上下文预检失败，裁决中断（child_state=failed，无结论）。需要审阅的原始材料（arXiv 论文全文 3067 行、LFL 源码若干行、台账、正文）合计体量远超子代理可承载范围。
root_cause: ""
solution: 改用「审稿包」策略：父级先把需要逐字核对的原文按主题切成小文件落盘，每个摘录带原始行号（如 receipts/d53review-pack.txt 199 行 + d53review-pack2.txt 42 行补核区），子代理只读 3-4 个许可文件、限 3-5 次工具调用，且明确列出「只准读这几个文件、不许多读」。本班三闸全部正常完成：首审 REVISE（P0×0/P1×5/P2×9）、定点复审 REVISE（1 条残留）、终审 PASS。同时父级自己实开核对了子代理指出的「需补充核对」项（registry.py 821 行、mcp_client.py 681 行、arXiv 1691-1700/2173-2178/2374），子代理无权扩读时由父级补证。
evidence: 子代理轨迹回执：subagent_fa27a7729dc4（failed，189K tokens/22 tools）；subagent_b4570fd20cdc（REVISE，4 轮 5 tools）；subagent_a197225512fa（REVISE，5 轮 7 tools）；subagent_bfaf52a3541d（PASS，5 轮 4 tools）。审稿包：docs/promotion/receipts/d53review-pack.txt、d53review-pack2.txt。详见 docs/promotion/STATUS-20261102-daily53.md 第六节。
tags: [subagent, review, context-budget, promotion]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-02T13:37:34.633864+08:00"
updated_at: "2026-11-02T13:37:34.633864+08:00"
supersedes: [EXPERIENCE-20261102-审稿子代理必须显式给读取预算-文件数上限-单文件-limit-总行数-否则上下文预检失败中断裁决]
---