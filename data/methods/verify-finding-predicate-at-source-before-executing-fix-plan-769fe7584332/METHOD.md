---
method_id: verify-finding-predicate-at-source-before-executing-fix-plan-769fe7584332
name: verify-finding-predicate-at-source-before-executing-fix-plan
description: 用户指示按此前给出的修复建议执行（如『按建议执行』『修 1/2/3』）且该建议是对 reviewer findings 的逐条裁决时，不得机械照做：先对每条裁决的事实断言（谁 trim、几处退化、某 import 是否未用）做定点 grep/read 到当前 definition/callsite。断言被源码证伪的条目必须拒修并附证据——修一个不存在的缺陷等于引入回归；断言成立的才修，并配回归测试，用红灯实验（还原修复→新测试精确失败）证明测试有效；行为取舍类记录不修。完成后向用户显式报告与原计划的偏差及原因。
aliases: reviewer 意见先核实再修, 照单全修前先对源码, 修复清单逐条验真, 别机械照做上轮修复建议, 误修不成立的问题等于埋回归, 红灯实验证明测试能抓缺陷
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:244:327dbb0e5b5d129da2ba
evidence_refs: learning:learn:663412fca322
created_at: 2026-10-27T17:50:37.969896+08:00
updated_at: 2026-10-27T17:50:37.969896+08:00
---
## Trigger
用户要求执行先前给出的修复计划/建议清单，而该清单源自对 reviewer/审查 findings 的逐条裁决，且裁决中含关于代码行为的断言（是否已 strip、是否未使用、几处回退、纯文案还是行为变更）

## Discriminator
一次作用域受限的 grep/read 即可证实或证伪每条断言：当前源码的 definition/callsite（如入队路径内部已是 text.trim()、被指未用的 import 实际被引用、硬编码是既有风格还是新增回退）是否支持该 finding 的前提；支持→真缺陷，不支持→伪缺陷（修复即回归）

## Short path
- 把计划中每条修复项拆成『事实断言 + 修法』两部分；未知量：断言是否在当前源码成立
- 对每条断言做一次定点 grep/read 到 definition/callsite（入队边界是否已 trim、import 引用、硬编码出现位置）
- 按证据分流：断言成立→修；被源码证伪→拒修并附证据；行为/取舍类→记录不修并说明理由
- 每个真修配回归测试，并做红灯实验：还原该修复后新测试应精确失败，证明测试真能捕获缺陷
- 重新冻结候选、更新指纹、送独立审查，向用户显式报告与原计划的偏差及原因，而非默默扩缩范围

## Stop conditions
- 每条 finding 已归入三类之一：修（带红灯验证的回归测试）/ 拒修（附源码证据）/ 记录（附取舍理由）
- 候选重新冻结、指纹更新、独立审查终态（PASS 或明确上报剩余风险与未完成项）

## Verification
- grep/read 输出与断言逐字对照（如 enqueueQueueTurn 内部 enqueueQueueMessage(sessionId, text.trim(), …) 直接证伪『空白会进后端队列』）
- 红灯实验：还原修复→新测试精确失败；应用修复→通过
- 补丁前像/后像与工作树逐文件 blob 一致；审查回执 P0/P1=0

## Counterexamples
- finding 自带确凿验证证据（reviewer 已附复现 trace/测试输出）且适用于当前版本→断言已被权威证实，直接评估修法，无需重验
- 断言自明的机械修复（diff hunk 内可见的拼写错误、字面量缺 aria-label）→直接修，不必先做源码核验
- 无源码可核的流程/文档类 findings→没有 definition/callsite 可对照，按其他证据类型裁决
