---
method_id: declaration-receipt-audit-as-status-authority-for-vague-past-work-querie-e378cc4d948a
name: declaration-receipt-audit-as-status-authority-for-vague-past-work-queries
description: 用户模糊回询过去工作的状态（"那个X任务呢？"）且无活动 goal 时，会话自身的声明-回执审计事件（declaration_check）是指代对象与真实执行状态的一次性权威：False=回复中声明过但无任何工具回执对应=零执行（不是"做了没报"）；相邻 action_trace 回执行说明实际只做了什么。拿到该条目后两个未知量（指哪件事、做没做）即闭合，继续换关键词枚举 event_stream/search、宽 limit 扫描、重读源文章正文都无法再缩小答案所需的未知量。与 resume-continuation 方法互补：那边用首次 search miss 回执列出的权威参考，这里用 receipt-vs-声明审计条目作状态权威。本集第 5 次调用已闭合问题，其余约 8 次为冗余叙事重建。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0f0a5645-b407-4183-bd45-9c5d82003d93:358:0068b7149ba9f1830ca2
evidence_refs: learning:learn:24e0518a2775
created_at: 2026-10-10T05:55:38.432807+08:00
updated_at: 2026-10-10T05:55:38.432807+08:00
---
## Trigger
用户用模糊指代询问过去某项工作的状态/进度（"mcp等插件任务呢"式回询），无活动 goal，且关键词检索只命中陈旧/背景性记录、给不出执行状态时。

## Discriminator
会话事件流中已出现的 declaration_check ... False 条目：原文明确列出被声明但"未匹配到对应记录"的步骤清单（即用户指代的对象），并给出"存在与工具执行回执不符的完成声明"结论；同批相邻 action_trace 行显示当时唯一成功回执是抓取文章+对照分析。该条目在首次定向 event_stream 查询的回执中即可见，knowledge-at-time 满足。

## Short path
- get_goal：确认无活动追踪目标（排除"有 goal 未推进"分支）。
- 对事件流做一次 topic 关键词定向查询（scope=current_session），优先定位 declaration_check/回执审计条目；未知量：用户指哪件事、执行状态如何。
- 条目为 False：直接采信"声明了但无回执=未执行"，并用相邻 action_trace 成功回执界定实际完成范围；两个未知量闭合。
- 以"指代对象+状态+阻塞原因+下一步选项"作答并停止，不再枚举。

## Stop conditions
- 审计条目已同时给出指代对象与执行/未执行结论（False=零执行；True=有回执，应转读那些回执）。
- 继续查询不会再改变状态答案（状态类回询不需要源文档正文）。

## Verification
- 状态结论必须落到具体 declaration_check 条目 ID 及其"未匹配到对应记录"原文，不接受无审计出处的"应该没做"。
- "实际做了什么"的每一项都必须有对应成功回执行（action_trace/web_fetch 等），避免复现本次被审计出的"声明无回执"偏差。

## Counterexamples
- 用户要的是过去工作的内容本身（"把那篇文章/分析再贴出来"）：审计条目不含正文，此时重读/重 hydrate 源 artifact 是必要的。
- current_session 事件流查不到该主题（工作发生在其他会话或审计机制上线前）：不能凭审计缺失断言"未执行"，需换 provenance/search 来源核实。
- declaration_check 为 True/pass：声明步骤确有回执，应去读对应回执而不是回答"没做"。
- 用户意图是继续推进而非问状态：给出状态与选项后应停在等待用户选择，无需继续考古式枚举。
