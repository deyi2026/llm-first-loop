---
method_id: feed-legal-values-to-all-other-hard-gates-when-testing-soft-warning-ca91c465232b
name: feed-legal-values-to-all-other-hard-gates-when-testing-soft-warning
description: 在带既有硬拒约束（唯一性/1:1/version CAS/状态机/合同校验）的入口上新增软性不阻断检查后，验证该软路径时不要让 fixture 同时违反任何既有硬门：先枚举入口全部硬拒点，让 fixture 在这些维度全部喂合法值，只保留软告警目标维度为唯一违规。否则任一硬门先短路，观察到的失败属于 fixture 维度污染而非新功能缺陷，白跑一轮调试后才发现测的不是目标路径。判据：测试失败的 reason/异常若对应某个既有硬门（如 1:1 唯一性拒绝），即证明污染。
aliases: 软告警测试被唯一性校验拦了, 测试夹具误触其他校验怎么排, 只留一个违规维度的用例设计, 验证告警不阻断前先过硬门, 测软路径 fixture 全绿前置
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1a7bb31d-f3da-497f-9322-336483f4435a:576:15e4c2e0804d18280249
evidence_refs: learning:learn:8154d9778150
created_at: 2026-11-14T13:14:38.681715+08:00
updated_at: 2026-11-14T13:14:38.681715+08:00
---
## Trigger
为入口新增的软性（只告警不阻断）检查写测试或手工验证其触发路径，且该入口同时存在多个先于或独立执行该软检查的硬拒约束（唯一性、状态转移、CAS、参数合同）

## Discriminator
入口源码/工具定义在写测试前已显式列出硬拒点及其判定顺序（如 _assert_unique 的 1:1 裁决、version CAS、状态转移表）；任一硬维度违规都会在软告警可观测之前抛出拒绝——这个事实当时已可见，足以要求 fixture 在硬维度上先全绿

## Short path
- 从入口源码枚举全部既有硬拒点（唯一性、CAS、状态转移、合同校验）及执行顺序
- 构造 fixture/调用参数：除软告警目标维度外，所有硬维度喂合法值（如全新 goal_id、全新 branch/worktree）
- 断言软告警出现且登记/写动作未被阻断
- 若失败回执显示被某个既有硬门拦截，判定为 fixture 污染：只修该维度后重跑，不怀疑新功能实现

## Stop conditions
- fixture 仅违反目标维度时软告警路径走通且动作未被阻断
- 确认软检查在代码序上先于所有硬门执行时，才允许 fixture 同时违反硬门

## Verification
- 失败信息中的拒绝原因/reason_code/异常类型对应某个既有硬门 ⇒ 判 fixture 污染，修 fixture 而非修功能
- 软路径通过后补一条『硬门仍硬』的对照测试，确认没有把既有硬拦偷偷放松成告警

## Counterexamples
- 测试目标本身就是断言硬门的拒绝行为——此时必须违反对应硬门
- 入口没有任何既有硬约束的独立纯函数/新入口——无需枚举硬门
- 软检查在代码路径上先于硬门执行，硬门违规不会短路软告警的观测
