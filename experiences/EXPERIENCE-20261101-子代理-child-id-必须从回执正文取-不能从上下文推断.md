---
title: 子代理 child_id 必须从回执正文取，不能从上下文推断
scenario: 并行 spawn 多个子代理后，需要按 child_id 轮询结果；回执里没有直接可见的 child_id，只能从 evidence 正文取。
root_cause: "spawn_subagent 的短回执只含 evidence_ref 与状态，不含 child_id 文本；我在批量调用后按记忆/上下文补出了 id，并把\"查不到 handle\"误判为工具故障（进而怀疑 spawn 失败、模型名不匹配），实际是寻址字串错误。属于\"用推测填充未读到的字段\"。"
solution: |
  结论：子代理 id 必须从 spawn 回执的**正文**取得（read_evidence 读 evidence_ref，形如 subagent_xxxxxxxxxxxx），不能凭可见性推断或从别处补。出现 child handle 不存在时，先核 id 字串本身（前缀是否缺失、是否拿成 evidence hash），再怀疑子代理生命周期。批量 spawn 后应第一时间对每个 evidence_ref 做一次 read_evidence 记录 id，避免后续多处推测。
  
  当前性验证：对任一 spawn 回执 ref 执行 read_evidence(range_type=text_char, start=0, limit=700)，输出应含 `child_id=subagent_` 前缀串；用该串调用 subagent_result 应返回 child_state=running|completed，而非 "child handle 不存在"。
evidence: "本会话：批量 spawn 三个子代理后，我用\"看似来自回执\"的 12 位十六进制串（3fe9b2d0e655 等）调用 subagent_result，连续得到 \"child handle 不存在、已淘汰且无durable topology\"；read_evidence 回执正文后看到真实 child_id 为 subagent_3fe9b2d0e655（带 subagent_ 前缀），改写后 subagent_result 立即返回 child_state=running。同批次 3 个子代理实际一直存活。"
tags: [subagent, tool-receipt, id-addressing, self-correction]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T11:29:16.554629+08:00"
updated_at: "2026-11-01T11:29:16.554629+08:00"
---