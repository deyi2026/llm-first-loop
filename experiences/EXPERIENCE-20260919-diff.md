---
title: 字节一致≠语义一致：执行已批准方案需对批准全文做语义 diff，完成宣称须与执行回执对账
scenario: "执行一条已人工批准（accepted）的演进方案、把方案阶段1落地为 method 候选时：仅核对了候选文件字节哈希与写入回执一致，未对批准全文做语义比对；产出纪律把 record_use 当效果评估载体（该工具无 task_benefit 参数、程序固定 not_evaluated）、把阶段2\"相似样本<3 不硬算 delta\"扩大为\"同一 method 使用<3 不得 pass\"、把阶段3\"列出依赖冲突与交集场景\"窄化为\"只核对 use_decision 一致性\"、新增超出提案的\"以指标为准\"终审，并宣称存在不存在的\"下次任何 method 使用自动测试\"挂钩；同轮宣称\"批准已执行到位\"而 exec 回实为 skipped/unverified。"
root_cause: 哈希只证明字节未变，不证明语义对齐批准文本；起草纪律时未核对工具真实参数面（record_use 根本没有 task_benefit 入参），把两个生命周期阶段（适用性声明 vs 效果评估）的条款混写在同一份纪律里。
solution: "执行批准方案的四步纪律：①先取批准文本全文（权威存储），逐条映射到产出物做语义 diff，每条标注实现位置或显式偏差；②涉工具行为的条款先读实现确认机械可落地（本例 record_use 无 verdict/task_benefit 入参，\"在 record_use 上降级\"无处发生）；③完成宣称与执行回执对账（evolution_exec 状态、工具拒绝分支如 evolution_complete 仅接受 executing+归属会话），登记不了就明说\"待人工 CLI evolve-complete\"；④引用机械指标前核口径（action_trace=最近30条滚动、llm_rounds=累计计数，均不按 task/episode 隔离，不得直接归因单任务）。修订产物走 save_candidate v2+parent_ref，旧版置 hold 注明替代关系，不用 refine 改正文（refine 仅支持流转状态）。"
evidence: "EVO 全文：data/audit/evolution_suggestions.jsonl（EVO-20260919-eabe3d37, accepted）；v1 全文：method:record-use-a7d0337b11cf；实现证据：src/llm_loop/methods/store.py record_use（task_benefit 无参数、硬编码 not_evaluated）、src/llm_loop/introspection/tools_exec_complete.py:129（非 executing → FAILURE，限归属会话）、src/llm_loop/introspection/status.py:584/598（action_trace[-30:]，llm_rounds 累计）；修订版：method:record-use-v2-2c0e93d22ed6（content_hash c33825a1…，本回执取得）。"
tags: [semantic-drift, evidence-discipline, method-learning, evolution-execution, implementation-check]
source: {}
status: archived
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T11:44:27.765388+08:00"
updated_at: "2026-09-19T12:02:35.333250+08:00"
---

执行已批准的演进方案时，产出物与批准文本的字节/哈希一致不等于语义一致：v1 method 候选在六处偏离 EVO-20260919-eabe3d37 原文（record_use/qualification 阶段混同、"不足3"条款主语与后果双重转移、"以指标为准"加码、阶段3窄化、轻量声明被加负、虚构"自动测试"挂钩），而执行会话当时仅核对哈希即宣称"批准已执行到位"，与 evolution_exec 的 "ai skipped unverified" 回执脱节。正确做法：①对批准全文逐条做语义 diff 并标注每条实现位置或显式偏差；②涉及工具行为的条款先读实现（参数签名、硬编码、前置校验）确认机械可落地；③完成宣称与执行回执对账，不能登记就如实说待人工；④引用机械指标前核口径（滚动窗口/累计/是否按任务隔离）。