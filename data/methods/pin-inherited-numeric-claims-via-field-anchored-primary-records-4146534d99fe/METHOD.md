---
method_id: pin-inherited-numeric-claims-via-field-anchored-primary-records-4146534d99fe
name: pin-inherited-numeric-claims-via-field-anchored-primary-records
description: 当评审、他模型输出或早前轮次给出的量化断言（工具数、token/char 成本、百分比、文件计数）要写入文档或驱动决策时，不以“信任/争论”处理：用断言自带的字段名/键名做锚，精确落到仓库内结构化主记录（如 request.meta 事件日志），读单条全量记录钉出处与机制语义，跨多实例验一致性与常态性，派生百分比用记录内字段重算；只采用可复现口径，显式作废不可复现的继承数字，并对评审者自报的替换数字同样复跑。把“全库撒网找数字/事后返工重测”压缩成“字段→单条权威记录→一致性+常态性→重算”的固定下一跳。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:329:dbad645617a6727a7414
evidence_refs: learning:learn:2a620361f949
created_at: 2026-09-28T18:19:47.994197+08:00
updated_at: 2026-09-28T18:19:47.994197+08:00
---
## Trigger
需采用或修订来自他方评审/早前轮次的量化断言（数字、百分比、计数），且仓库内存在可 grep 的结构化持久记录；或已发布数字缺少具名出处、需要返工钉源时。

## Discriminator
断言自带的字段名（如 tool_schema_reserve_tokens / tools_count / tool_schema_reserve_chars）本身就是结构化记录的键名——键名 grep 等价于记录类选择器，可直接把“全库哪个文件”缩成单条 request.meta；且仓库存在多个会话日志实例与时间跨度，可做一致性与常态性检验。此锚在搜索前已在手（任务陈述即含字段名与 reserve_tokens 键片段），无需先枚举目录或撒裸数字。

## Short path
- 跳过目录枚举与多字面量撒网：用断言自带的字段/键名在持久记录目录精确 grep，落到单条权威记录并读全字段（含口径字段，如 tool_schema_reserve_source=projection_fallback）
- 用同一字段名在源码中定位计算/消费点（如 engine.py 的 budget 扣减处），钉机制语义
- 跨 ≥3 个会话实例复核同一字段一致性（74/37977 全一致），并在时间窗内计数记录总量（431 条 request.meta）判定“常态 vs 单点”
- 用记录内字段重算派生指标（(141557−103580)/141557→26.8%），估算值显式标注区间（+8K~+16K）
- 每个要写入文档的数字均有具名主记录出处后停止；不可复现的继承数字（18988/40.9%）作废并记录替代口径

## Stop conditions
- 所有将采用的数字均可指到具名主记录字段，且多实例一致性与常态性已验证
- 继承数字复现一致——直接采用，不额外重测
- 断言指向仓库外来源（库内无对应记录）——本方法终止，改走“标注为外部自述/volatile”路径

## Verification
- 换一个未用过的会话/样本复跑同字段 grep，数字一致
- 派生百分比可从记录内字段独立重算，不依赖被替换的原口径
- 被作废的继承数字在文档修订记录中留有“原值→替代口径→依据”条目

## Counterexamples
- 数字来自上游 README/官网自述且库内无对应持久记录：不适用，应标为 volatile 自述而非实测，不得混入实测口径
- 单次性事件（一次性事故/一次性配置记录）：常态性取样与多会话一致性检查无意义
- 字段名未知或记录为非结构化自由文本：字段锚定 grep 不可行，需先做记录结构发现
- 他方数字经复跑本就与主记录一致：直接采用即可，不为了重算而重算
