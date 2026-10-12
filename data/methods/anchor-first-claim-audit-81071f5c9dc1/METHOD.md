---
method_id: anchor-first-claim-audit-81071f5c9dc1
name: anchor-first-claim-audit
description: 审计一份此前写好的系统分析时，先从来文枚举全部可检验断言并三分类：可各用一条廉价命令核实的持久状态锚点（git HEAD、deployment/manifest JSON、action receipts、journal 统计）、有明确指向位置的代码行为断言、不可独立复核的遥测统计。第一批并行核实所有状态锚点——它们最廉价、因分析写作时刻滞后而失真率最高，且证伪会级联改变方案（如版本漂移层数、部署排序）。代码断言只在被指向的确切 file:line 验证；遥测类显式标注'未独立复核、按来源采信'。行动方案只从已核实事实重排，每条修正须可追溯到第一手命令输出。本 episode 中 git HEAD 锚点首轮即证伪'main=606755367'，但 deployment/receipts 等同级廉价锚点拖到第 7/8 轮才查，且开场只声明核'三处'导致各轮被动扩围——前置批量锚点可近乎减半轮次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:789:2eb6ab156d3e9926e6b5
evidence_refs: learning:learn:be6a5a968cb4
created_at: 2026-09-18T14:30:28.127597+00:00
updated_at: 2026-09-18T14:30:28.127597+00:00
---
## Trigger
收到一份先前写成的分析/评审/报告，其中混合引用持久运行状态（版本号、部署代、action 回执、统计计数）与代码行为断言，且后续行动方案依赖这些断言成立

## Discriminator
来文本身是否点名了可各用一条廉价命令直接核实的持久状态工件（git HEAD、managed deployment/desired-state JSON、service action receipts、journal 计数）。这类断言存在写作滞后、失真率最高，且单条证伪即可级联改变方案优先级；该判别在收到消息当时即可做出，无需任何后续发现。

## Short path
- 通读来文，枚举全部可检验断言并三分类：持久状态锚点 / 代码行为断言（记录其指向的确切位置）/ 不可独立复核的遥测统计
- 第一批并行核实所有状态锚点（git log/status、deployment JSON、最近 action receipts、journal 计数，各一条命令），立即标记被证伪或滞后项
- 仅对未被锚点证伪的代码断言，按其指向的确切 file:line 读取验证，标 ✅/❌/nuance
- 无法廉价复核的遥测统计显式标注'未独立复核、按来源采信'，不与已核实事实混列
- 用核验表重排行动方案：每条修正给出第一手输出出处，并说明对方案的影响（如漂移层数、gen 发布排序）

## Stop conditions
- 所有影响行动方案的断言均已核实或显式标注采信
- 新出现的待核断言先入表分类，不再无清单地临时补查
- 对已核实断言不再追加'再确认'式读取

## Verification
- 最终核验表每行 ✅/❌ 均引用确切 file:line 或第一手命令输出
- 每条修正可追溯到锚点命令输出，而非用户复述或事后推断
- 未核项与已核项在结论中显式区分，方案仅基于已核项

## Counterexamples
- 来文只含纯代码语义断言、未引用任何持久状态工件 → 无锚可批，直接按位置读码
- 状态工件读取昂贵或有副作用（生产库、破坏性命令）而代码在本地 → 反转顺序或仅抽样
- 分析是本会话实时生成、无滞后窗口 → 锚点失真概率低，无需前置批量复核
- 用户只要求核验单一断言 → 不建全量清单
