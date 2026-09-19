---
method_id: capability-surface-vs-callsite-diff-fdc1f150874a
name: capability-surface-vs-callsite-diff
description: 集成接线类任务先用差集定规格再动手：结构读 provider 模块枚举完整能力面（全部方法签名），用这些方法名 grep consumer 得到实际调用点；差集（有原语、无调用）即精确工作清单。千行级大文件只在 grep 命中区间做局部读，不先全量读。实现前读一个目标表面样板（既有工具/测试 harness）复用结构而非重新发明；只读 API 的测试必须含不存在 key 的探针，用于暴露隐藏写副作用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:823:2ba514c99a4a31774ab4
evidence_refs: learning:learn:8a308fb89d4d
created_at: 2026-09-19T02:38:18.250215+00:00
updated_at: 2026-09-19T02:38:18.250215+00:00
---
## Trigger
任务是把已存在的原语/能力接入另一组件的真实生命周期，或把内部事实暴露到新表面（工具面/API面），provider 与 consumer 都是可 grep 的本地代码，且 provider 的方法签名/结构可完整枚举。

## Discriminator
provider 结构读输出的完整方法签名列表 × consumer 中这些方法名的 grep 命中：某原语零命中（或仅 import/字段声明命中）即证明该能力未接线。该差集在读任何大文件之前即可获得，且每条缺口都有可复核的零命中证据。

## Short path
- 确认基线与 goal 边界（repo 状态同步），不做无关枚举
- 结构读 provider 模块，枚举完整能力面（全部方法名+签名）
- 用能力面方法名 grep consumer：命中行号给阅读位置，零命中原语直接进缺口清单
- 只读命中区间±少量上下文，确认缺口语义（默认参数、错误路径、调用时机）
- 读一个目标表面样板（同类工具/同类测试 harness），复用其结构模式
- 逐缺口写 RED（含只读表面的未知 key 探针）→ 实现 → 全链验证（单测/相邻套件/lint/类型/CI）

## Stop conditions
- 差集为空且既有调用语义已覆盖目标 → 无缺口，直接验证并汇报
- provider 签名不足以判定语义（无类型/无 docstring/歧义）→ 停止 diff，转读实现
- 全部缺口 RED→GREEN 且验证链通过 → 停止，不顺势重构差集外代码

## Verification
- 每个『未接线』结论都有 grep 零命中（或仅 import 命中）的可复核证据
- 新表面返回的事实字段与 provider 真实返回逐字段一致
- 只读表面用不存在 key 探测并断言无状态变更；发现写副作用先修复再继续
- 相邻既有套件与全量门禁（lint/类型/CI）通过

## Counterexamples
- consumer 本身很小（如 <200 行）时全量读更便宜，构造 grep 差集属过度流程
- provider 方法名/签名不表达语义（无类型标注、重载歧义）时差集会误导，须先读实现
- 绿地开发：原语尚不存在，无 provider 面可 diff，规格来自设计文档而非调用缺席
- 正确性依赖时序/崩溃等涌现行为（竞态、TTL 到期）时，调用点差集只回答『哪里没接』，不回答『接得对不对』，必须补真实时钟/文件系统的行为测试
