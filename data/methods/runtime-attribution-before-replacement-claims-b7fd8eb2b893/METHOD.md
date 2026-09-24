---
method_id: runtime-attribution-before-replacement-claims-b7fd8eb2b893
name: runtime-attribution-before-replacement-claims
description: 当评审“用现有组件替代 CoT/推理载体”时，先验证组件是否真在运行并产生可归因结果，而不是只看代码存在或使用计数。若只有 access/inject 而无 citations/guidance/新鲜遥测，则把问题定性为观测与归因缺口，按可证伪性给出补遥测、补归因、最小函数改动顺序。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:9f0b8d02-5ee4-426e-bd9f-1eeca2436fb0:115:dcd6d981356cea7b1959
evidence_refs: learning:learn:314e75b268bf
created_at: 2026-09-22T17:13:16.795706+00:00
updated_at: 2026-09-22T17:13:16.795706+00:00
---
## Trigger
用户要求评估某套已有组件能否替代另一机制，且证据包含运行状态、配置、日志/计数，但缺少因果归因指标。

## Discriminator
关键事实是运行时开关/模式、遥测新鲜度、以及 outcome 字段（如 citations/guidance）是否非空；仅 access/inject 计数不能证明被用对。

## Short path
- 把每个待替代能力映射到组件、运行时开关、遥测事件和归因字段。
- 用最小命令确认开关是否生效、遥测是否新鲜、归因字段是否非空。
- 若只有检索/注入计数而无引用/使用结果，先判定为归因缺口，停止宽泛代码枚举。
- 对每个组件只查一个决定性事实：state 是否落盘 v0.2 字段、retriever 是否有 by_id、config 默认模式。
- 按可证伪性排序建议：先补遥测/归因，再做最小函数改动，最后晋级未验证能力。

## Stop conditions
- 已能区分组件“存在”“启用”“产生可归因结果”三种状态。
- 每个结论都有对应命令输出或文件字段证据。
- 用户目标只是评审/排序，不要求实现。

## Verification
- 检查最终结论是否把 access/inject 与 citations/guidance 分开解释。
- 确认配置默认值、遥测最后事件时间、state 文件非空字段计数被引用。
- 确认建议顺序能先产生可证伪数据，再改变主循环。

## Counterexamples
- 纯静态设计评审，没有可运行的配置/遥测/日志可查。
- 用户明确要求实现并启用组件，而不是评估替代是否成立。
- 已有独立 A/B 或权威结果直接证明效果，无需先补归因。
- 目标能力不需要归因指标，例如只需验证服务存活或缓存命中。
