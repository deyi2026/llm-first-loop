---
title: 跨论文断言归属必须逐句核到具体 arXiv ID：改归属时极易再挂错一次（一稿四篇论文本班连抓两个 P0）
scenario: LFL 推广班次一稿引四篇论文（主材料 EtE + 三篇旁证）写跨论文对比。d69 晚班 2026-11-07：第一轮审稿 P0——把 AgentCap(2611.00729v1) 摘要末句「授权…在工具边界上、独立于模型推理」挂成主材料 EtE 的结论；我修订时把该句挪到旁证二，又在 §十 局限段把 EtE 的「攻击成功率 0% + 任务完成率 100%」挂给 AgentCap（AgentCap 摘要实读命中 100% 次数 = 0），第二轮审稿再抓一个 P0。
root_cause: 一稿多引时，结论句和数字会被「就近记忆」挂到最近提到的那篇论文上；而修 P0 时如果只是把句子在段落之间搬动，没有回到摘要原文核对新归属，就会把同一种错误换个位置再做一遍——本班两个 P0 都是同一种错误（结论句/数字挂错论文），第二个还是自己修订引入的。
solution: "写作时每条跨论文断言就标注 arXiv ID；台账与审稿包按论文分组；**修订归属类问题时必须重读被引论文的摘要原文再落笔**，不能只改主稿那一句。当前性验证：跑 `grep -c '100%' docs/promotion/receipts/d69research/arxiv_abstracts.txt` 与 `awk '/^### 2611.00729v1/,/^### 2610.41181v1/' docs/promotion/receipts/d69research/arxiv_abstracts.txt | grep -c '100%'`（后者应为 0，证明 AgentCap 摘要没有 100% 这个数）。"
evidence: 本班真实失败：第一轮审稿 P0（subagent_f7fca54cc870）报「tool-boundary 授权那句是 AgentCap 摘要原句，被写成 EtE 论文结论」；第二轮审稿 P0（subagent_bf2e365a39f2）报「§十把 0%/100% 绑给 AgentCap，与 §五自相矛盾，且给 AgentCap 造出摘要没有的 100% 任务完成率」；实源核对：AgentCap 摘要段 grep 100% 命中 0 次，0%/100% 出自 EtE 摘要「reduces the attack success rate to 0% while preserving 100% task completion」。第三、四轮审稿 p0=p1=p2=0。
tags: [promotion, attribution, review, arxiv]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T20:32:51.452900+08:00"
updated_at: "2026-11-07T20:32:51.452900+08:00"
supersedes: [EXPERIENCE-20261106-某篇论文命中哪个检索组-必须脚本化核对归属-不能凭印象写进参考来源]
---