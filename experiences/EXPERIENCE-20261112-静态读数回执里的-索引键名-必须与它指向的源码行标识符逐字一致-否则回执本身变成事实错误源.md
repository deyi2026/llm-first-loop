---
title: 静态读数回执里的「索引键名」必须与它指向的源码行标识符逐字一致——否则回执本身变成事实错误源
scenario: 写稿时把源码静态读数做成机检回执（JSON），回执里用「键名 → 行号」索引源码行。键名是回执作者自己起的简写（如 evidence_required_line），它与该行源码里的真实标识符（evidence_refs）不一致时，回执就成了错误事实的载体：正文照抄回执的键名引用源码，审稿人拿回执指的行号去核源码，发现行内容对不上，判为事实类 P2；更糟的情况是正文按回执的错名描述了一个并不存在的机制。
root_cause: ""
solution: 写静态读数回执时，键名直接取源码行的真实标识符（正则从该行抽出标识符再写进键名），不要用自造的语义简写；出回执前跑一遍「键名 → 行号 → 该行是否真含该标识符」的机械断言。本班 d81 实测：回执键名 evidence_required_line 指向 task_store.py 第 94 行，而该行标识符是 evidence_refs；审稿子代理判为 P2（其余 17 个键名均逐字对应，仅此一处不符），更正键名并保留 observed_at 后，第 2 轮复审确认「无第二处同类键名错配」、P2 消解。
evidence: "本班 d81：receipts/d81-lfl-readings.json（observed_at 2026-11-12 20:06:01）中 task_store 分组的 evidence_required_line=94，而 src/llm_loop/introspection/task_store.py:94 实为 `evidence_refs: list[str] = field(default_factory=list)`；第 1 轮审稿子代理 subagent_92f68f16e301 记为 P2-1；改名后第 2 轮 subagent_e126ecb084e4 复核 18 个回执索引键「17 个逐字对应、1 个已更正，无第二处同类错配」，VERDICT PASS。"
tags: [LFL推广, 静态读数, 回执, 事实一致性, 2026-11-12]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-12T20:21:59.859636+08:00"
updated_at: "2026-11-12T20:21:59.859636+08:00"
---