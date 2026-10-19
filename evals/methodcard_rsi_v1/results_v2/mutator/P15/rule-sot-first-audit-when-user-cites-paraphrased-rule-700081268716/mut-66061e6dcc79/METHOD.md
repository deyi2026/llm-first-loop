---
method_id: rule-sot-first-audit-when-user-cites-paraphrased-rule-700081268716
name: rule-sot-first-audit-when-user-cites-paraphrased-rule
description: 审计"定过但疑似没执行"的内部规则：首轮检索回执若已暴露规则登记结构（rule_ref 编号、rule_sot 权威、SoT 文件名），立即转为 SoT 限定检索，用登记词汇（如"子代理"）替代用户转述词（"专用子agent"）——用户词汇≠规则词汇，且 .releases 快照树会把一行命中放大成十几条重复噪音。再用会话/时间窗限定的事件流核对 spawn/闸事件轨迹，最后以"违规前规则是否已出现在当事会话上下文"区分"没加载"与"被跳过"。反模式：拿用户原话做全库关键词变体搜索、逐词换参、逐条读快照重复命中。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:934:40586cb190e4eb8d0e6c
evidence_refs: learning:learn:cbe53aae6116
created_at: 2026-10-14T17:56:29.655137+08:00
updated_at: 2026-10-14T17:56:29.655137+08:00
---
## Trigger
用户以转述措辞引用某条内部规则（如"当时定下过规则要调 X"）并质疑其未被遵守或未加载，需要同时定位规则原文与核对实际执行；首轮结构化检索（search_records/rule 卡片）已回执规则登记元数据。

## Discriminator
search_records 回执已给出 rule_ref=RULE-AI-NN、authority=rule_sot，且规则 SoT 是单一可定位文件（docs/ai_rules.md，摩擦点前一轮已明示）；同时 search_docs 对用户原话"专用子agent 调用规则"未命中本身即证明用户词汇≠登记词汇（规则用"子代理"）。继续全库变体搜索只会命中 .releases 快照树的重复行（首搜 20 条中 14+ 条为同一行快照复制）。

## Short path
- 步骤1（未知量：是哪条规则）：只在规则 SoT 文件内用登记词汇（"子代理"/"子agent"）或规则标题索引检索，直接命中规则原文与编号（本例 RULE-AI-28 三道审查闸）；不离开 SoT 做 workspace 级变体搜索。
- 步骤2（未知量：是否被执行）：拉取限定到嫌疑会话/时间窗的事件流，统计违规窗口内 spawn_subagent 调用相对闸事件（全量测试、git push）的位置。
- 步骤3（未知量：没加载还是被跳过）：查违规时点之前当事会话自身上下文是否出现过该规则 ID/关键词（检索日志、存档 experience 标题），据此分类。
- 步骤4：规则原文锚点、执行轨迹、加载/跳过分类三项证据齐备即停止发现；补救动作（补审）另行启动，不并入调查。

## Stop conditions
- 规则原文已从 SoT 定位（含规则 ID 与行锚点）、违规窗口事件轨迹已核对（有具体时间戳与调用计数）、"未加载 vs 被跳过"已有违规前上下文证据支撑，三者齐备即停。
- 若 SoT 内未命中该规则，终止 SoT 分支，只沿结构化载体（experience/skill/governance）扩大一次并排除快照/发布重复目录；仍无则如实报告"未找到成文规则"，不做开放式变体 grep。

- Verification 未逐条通过前不结案（覆盖全部 2 条验证条目）

## Verification
- 核对定位到的规则原文措辞确与用户转述不同（解释首轮未命中，确认不是漏检）。
- 核对合规结论引用具体时间戳/事件（如违规窗口 122 条工具声明中 spawn 计数=0），而非印象判断。
- 核对"被跳过而非未加载"有违规前时点规则出现在当事会话上下文的直接证据；无此证据则降级表述为"未知是否加载"。

## Counterexamples
- 规则只是口头/临时约定，从未写入任何 SoT：SoT 检索必然落空，此时事件流与 experience 历史才是首要来源，不应继续在 SoT 内换词追查。
- 用户措辞与登记词汇一致：首轮关键词检索即直接命中，SoT 定位分支纯属多余。
- 问题纯为运行行为核查（"刚才做了什么"）而无规则合规成分：跳过规则定位，直接走限定事件流。
