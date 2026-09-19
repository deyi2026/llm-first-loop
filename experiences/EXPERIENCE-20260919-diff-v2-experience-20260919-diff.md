---
title: 字节一致≠语义一致：批准方案执行需全文语义diff+归因分层+逐步回执对账（v2，取代EXPERIENCE-20260919-diff）
scenario: "执行已人工批准（accepted）的演进方案、把方案阶段1落地为 method 候选时：仅以字节哈希+局部对照代替批准全文语义比对即宣称\"批准已执行到位\"；事后归因若不分层，会把提案自带缺陷误计为候选漂移、把工具描述混淆误归为凭空编造、把单次 skipped 回执外推为\"什么都没发生\"。"
root_cause: "分层：(a)提案自带缺陷——阶段1原文即在record_use上要求task_benefit判定与\"指标矛盾必须降级\"，与实现参数面脱节，缺陷在提案层；(b)候选转换漂移/虚构——\"不足3\"扩大、阶段3窄化、虚构自动测试挂钩；(c)工具描述诱因——method_manage共用参数表含task_benefit而record_use分支不消费，读共享表属可理解混淆；(d)过程缺陷——哈希+局部对照代替全文语义diff，单次skipped回执外推整体未执行。"
solution: 四步纪律：①批准全文逐条语义diff，每条标实现位置或显式偏差，并分层归因（提案自带缺陷≠候选漂移≠工具描述诱因）；②涉工具行为的条款先读实现核参数面与分支实际消费；③完成宣称与逐步执行回执对账，单次skipped仅否定该次，不外推；④记录型哈希绑定写入时快照，状态机操作后旧哈希失效属预期。归因分层后分别走：演进修订（提案缺陷）、候选纠正（漂移）、schema建议（描述混淆）。本解决方法待一次正式评估试用验证。
evidence: "EVO原文：data/audit/evolution_suggestions.jsonl（EVO-20260919-eabe3d37，阶段1\"verdict与指标矛盾…必须降级\"、阶段2\"相似样本<3输出insufficient\"、阶段3\"列出依赖冲突与交集场景\"）；src/llm_loop/methods/store.py（record_use无task_benefit入参、行305 list()仅排除retired、行535-582 update_status仅改status/updated_at、行584-639 save_candidate存在即返回）；src/llm_loop/introspection/registry_experience.py:66-69（save_candidate参数表）；v2全文 data/methods/record-use-v2-2c0e93d22ed6/METHOD.md 第5条原句\"观测与自评矛盾 → 降级 mixed/fail\"（已按复核修订）；v3 method:record-use-v3-1c1b05bfa2ee（hash 0c68afc6…，2026-09-19回执取得）。"
tags: [semantic-drift, evidence-discipline, attribution-layering, tool-schema-mismatch, hash-semantics, method-learning, evolution-execution]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T12:02:26.738311+08:00"
updated_at: "2026-09-19T12:02:26.738311+08:00"
supersedes: [EXPERIENCE-20260919-diff]
---

【本条取代 experience:EXPERIENCE-20260919-diff（已归档）；verified 仅覆盖事故事实（下述原文条款、参数面、回执、哈希语义均可独立复核），其中"解决方法"未经真实任务验证，待一次正式评估试用后才可视为有效。】

事故事实：执行已人工批准（accepted）的 EVO-20260919-eabe3d37、把阶段1落地为 method 候选时，执行会话仅核对候选文件哈希与写入回执一致即宣称"批准已执行到位"，而 evolution_exec 回执为 skipped/unverified（该回执只否定02:29那次自动登记，不否定02:33之后实际发生的候选保存——逐步对账后候选确实已存）。

归因分层（修正旧lesson把提案自带缺陷计入"候选漂移"的错误）：
(a) 提案自带缺陷：EVO 阶段1原文即要求"在 record_use 上填 evidence_refs 判 task_benefit"且"verdict 与指标矛盾必须降级为 mixed 或 fail"，而实现 record_use 无 task_benefit 入参（固定 not_evaluated）、指标口径不按任务隔离——批准文本与实现参数面脱节，缺陷在提案层；候选v1如实转录不属漂移。
(b) 候选转换漂移/虚构：阶段2"相似样本<3输出insufficient"被扩大为"同一method使用<3不得pass"；阶段3"列出依赖冲突与交集场景"被窄化为"只核对use_decision"；虚构提案不存在的"下次任何method使用自动测试"挂钩。
(c) 工具描述诱因：method_manage共用参数表含task_benefit而record_use分支不消费——读共享表得出"可以填"属可理解混淆，不能全归为模型凭空编造；改进方向是schema按分支裁剪或明示适用action（待人工决定是否提演进建议）。
(d) 过程缺陷：以哈希一致+局部对照代替批准全文语义diff；以单次skipped回执外推整体状态。

机制补记：记录型文件的哈希绑定写入时字节快照；此后任何状态机操作（如置hold/retire，update_status重写frontmatter与updated_at）都会使旧哈希失效，属预期而非篡改——不能拿当前文件要求匹配旧哈希。旧版退出普通检索用retire（search仅排除retired，hold仅降权：store.py行305/332）；refine/update_status不持久化note，替代关系必须写进新版本正文版本链与lesson，不能依赖旧版note。

解决方法（待验证）：①执行批准方案前对全文逐条语义diff，每条标实现位置/显式偏差，并区分"提案自带缺陷"与"转换漂移"，不得互相顶替；②涉工具行为的条款先读实现核参数面与分支行为（共用参数表≠分支实际消费）；③完成宣称与逐步执行回执对账，单次skipped仅否定该次；④归因分层后结论才可执行：提案缺陷走演进修订（新候选），漂移走纠正，schema混淆走演进建议。