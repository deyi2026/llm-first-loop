---
title: "简报\"知识健康度\"是单卡最新评分，不是知识库整体健康度——解读前先读该行 ref"
scenario: "2026-10-29 12:06 收到\"自我检查\"指令后，运行上下文头部显示\"知识健康度: 0.11 (-3.07 ↘)\"，看起来像知识库整体退化（比上一次掉 3 分）。若据此断言\"知识库正在退化/经验库失效\"，属误读：0.11 实际是上一轮结算里某一张卡的单卡评分。"
root_cause: ""
solution: "解读简报\"知识健康度\"时，先核对 data/knowledge_scores/ledger.jsonl 最后一条非 error 行的 ref 与 expected，再看 knowledge_health 维度的 status/warnings 作为整体口径；两者混用会把单卡波动误报成全局退化。本次核对结果：ledger 末行 ref=experience:EXPERIENCE-20261022-execute-command-内联脚本的撇号-触发词会误触发-rule-ai-28-保护分类器，expected=0.1119（标签\"无帮助\"，decision_reported=not_applicable），同卡当日 01:04 曾评 3.2229/applied；而 architecture_status knowledge_health 维度当时为 status=healthy / writes_enabled=true / reasons=[] / warnings=[]。结论：0.11(-3.07) 是单卡判定为\"本次不适用\"的正常波动，不是退化信号。"
evidence: "源码 src/llm_loop/runtime/briefing.py:151-207（_knowledge_health_lines 只取 ledger 最后两条成功打分行算最新分与 Δ，不做池级聚合）；data/knowledge_scores/ledger.jsonl 末行 ts=2026-10-29T10:10:53.411158+08:00 expected=0.1119 ref=experience:EXPERIENCE-20261022-... decision_reported=not_applicable，同 ref 于 01:04:31 expected=3.2229 decision=applied；architecture_status knowledge_health 返回 status=healthy, writes_enabled=true, reasons=[], warnings=[]"
tags: [知识健康度, 指标语义, 自我检查, 误读防护]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-29T12:21:19.754768+08:00"
updated_at: "2026-10-29T12:21:19.754768+08:00"
---