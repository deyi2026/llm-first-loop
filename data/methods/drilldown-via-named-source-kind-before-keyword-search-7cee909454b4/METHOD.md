---
method_id: drilldown-via-named-source-kind-before-keyword-search-7cee909454b4
name: drilldown-via-named-source-kind-before-keyword-search
description: 当回执/报告已把每个指标映射到具名 record kind（如『来源 declaration_check』『来源 exception_log』）或已示范 kind= 检索语法时，下钻核查应直接用该具名结构化过滤，而不是先猜自由关键词组合。本集在搜索发生前检索轴就已完整可见，仍先发了 2 次 keyword miss 后才切换到 kind 维度命中。关键词搜索仅作为无名轴或具名查询失效时的后备，不应作为对结构化记录库的默认开局。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:7bd90e8c-559a-47d4-8b0a-a458da824909:4:27a549b09f5f16f9903f
evidence_refs: learning:learn:16042def0b8c
created_at: 2026-09-28T17:33:42.331263+08:00
updated_at: 2026-09-28T17:33:42.331263+08:00
---
## Trigger
任务需要核查某个结构化报告/回执中的指标构成（如 self_eval 的 honesty_rate/exception_rate），且该报告在首次搜索动作之前已显式标注各指标的来源 record kind，或示范了 kind= 检索语法。

## Discriminator
搜索动作发出前，上下文中已可见具名检索轴：指标行内标注『来源 <kind>』（declaration_check、exception_log 等），且回执明示 search_records(kind=...) 语法。此时检索维度不是未知量，无需关键词枚举。

## Short path
- 执行 self_eval；未知量：当前健康指标。同时把回执中每个指标的来源 kind 记为后续合法检索轴，不要丢弃。
- 读取 context/status；未知量：本会话与历史样本的边界（本会话 exception_log 是否为空）。
- 对要下钻的指标直接 search_records(kind=<报告标注的来源 kind>)；未知量：该指标的原始样本构成。
- 抽样阅读返回记录，判断失败是否可归因于自身决策（如本集 exceptions 全为 LLM 传输层/Provider 错误）。
- 目标指标核查完即停止，成稿时区分『回执支撑的事实』与『未验证推断』。

## Stop conditions
- kind 过滤查询返回记录的 kind 标签与报告标注来源一致，且已覆盖目标指标的样本构成
- 目标指标全部核查完毕，无剩余未知量，进入成稿
- 具名 kind 查询连续两次返回空 → 转向 schema/kind 枚举发现，而不是继续换关键词重试

## Verification
- 返回记录的 kind 标签 == 指标行标注的来源 kind（如 exception_log 记录确来自 exception_rate 的来源）
- 报告中引用的每个发现都能对应到至少一条抽样记录原文，而非仅凭聚合数字
- 最终答复保留 fact/inference 区分标注（如对 honesty_rate checker 误判推断的显式未验证标注）

## Counterexamples
- 记录库不提供 kind/结构化过滤参数，仅支持自由文本检索 → 关键词搜索是合法首步
- 报告/回执未标注来源 kind，只给聚合数值 → 检索维度确实是未知量，需先探索
- 任务是语义探索（按主题/内容找记录），没有具名轴可依赖 → 不适用本方法
- 具名 kind 已被证实失效（改名/清空，查询为空）→ 沿用具名轴会空转，应转 schema 发现
