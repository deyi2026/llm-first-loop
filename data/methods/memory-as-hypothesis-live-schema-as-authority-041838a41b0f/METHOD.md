---
method_id: memory-as-hypothesis-live-schema-as-authority-041838a41b0f
name: memory-as-hypothesis-live-schema-as-authority
description: 评估/设计/对比类任务依赖一条关于自身平台能力的历史记忆（如'子代理只有 N 个工具'）时：把 memory/experience 记录只当假设生成器，不当作事实；对它支撑的能力未知量，直接用机器权威（get_tool_schema/工具注册表）一次调用核验，而不是先走 docs/搜索等次级来源。结论按三档分层：schema 已声明的事实 / 声明但未实测的行为（标 POC 待验）/ 需平台演进的缺口；与旧记录矛盾处显式标注记录已过时。docs 用于设计动机与历史演变，不用于'现在能做什么'。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:6:0009d147d4c7f1f517ba
evidence_refs: learning:learn:a80edcc2f392
created_at: 2026-10-12T00:02:17.576216+08:00
updated_at: 2026-10-12T00:02:17.576216+08:00
---
## Trigger
评估/设计任务的关键结论依赖一条带时间戳的 memory/experience 记录所描述的自身运行时能力，且该能力可由当前工具 schema/注册表直接核验（记录显陈旧或与当前描述存在潜在矛盾）

## Discriminator
该事实来源是 kind=memory/experience 的旧时间戳快照，而'当前能力'存在可一次调用的机器权威（工具 schema/注册表回执）；当能力结论将决定架构建议时，快照只能作假设，权威回执才能作事实

## Short path
- 命中旧记录后，先写出它支撑的关键未知量（当前真实能力是什么）
- 对该未知量直接调用机器权威（get_tool_schema 等），一次核验，不先经 docs/关键词搜索
- docs/检索只用于设计动机与历史演变类问题
- 结论按三档分层：声明已证 / 声明未测（标 POC）/ 缺口需演进；拿到权威回执即停止核验，回到主任务

## Stop conditions
- 权威回执已直接回答该能力未知量，核验结束，不追加同义确认
- 无机器权威接口时退回 docs/搜索，但结论降级为'文档声明，未实测'

## Verification
- 最终报告中每个能力性断言可指回 schema/注册表回执或源码行，而非旧记忆
- 与旧记录矛盾处显式标注'记录已过时'并保留原断言供对照
- 凡仅由 schema 文本支撑、未经运行验证的行为性结论，一律附 POC 待验标记

## Counterexamples
- schema/描述文本可能超前或失真于实际行为：行为级结论（如'child 实际可用全部工具'）必须 POC 实测，不得只引 schema 文本
- 未知量是历史演变或设计动机（如为什么当年限制为 5 个工具）：旧记忆与 docs 恰是正确来源，不应被当前 schema 覆盖
- 平台没有 get_tool_schema 类权威接口：方法退化为'标注快照时间+降级置信度'，而非强求一次调用核验
