---
method_id: designed-suppression-is-capability-gap-enumerate-gates-not-ungate-ce4a2c5e5e25
name: designed-suppression-is-capability-gap-enumerate-gates-not-ungate
description: 当用户要求让某类被抑制行为（定时任务/通知/注入）"生效"，而任务输入或首轮证据已表明抑制是成文设计（规则ID、以该行为为断言的测试、服务 docstring）时，不在抑制点找缺陷、也不直接取消闸门。把任务重构为能力边界枚举：沿"生产者→执行"逐个在源码确认工具校验、授权账本、admission 等闸门的拒绝条件；若全部关闭，结论是系统缺合法执行通道，交付新的被授权通道设计（含不变量、幂等、用尽降级），并显式否决"让被归档内容直接进 prompt"类补丁。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:125:37dfe11ad2f3affcd01a
evidence_refs: learning:learn:4f6a0b89dede
created_at: 2026-10-19T08:46:29.314385+08:00
updated_at: 2026-10-19T08:46:29.314385+08:00
---
## Trigger
用户要求使某被抑制行为"生效/变成任务"，且报告文本或首轮检索已显示该抑制带成文授权语义：引用了规则ID，或命中以该抑制零效果行为为断言的单元测试/docstring。

## Discriminator
抑制点不是缺陷而是被断言的设计：用户报告原文已写明"X 是设计行为，按规则一律归档、不构造 Message、不进 prompt"，或首轮 grep 命中 test_…asserts 该行为的测试。该事实把搜索空间从"全库找 bug 并修抑制点"缩为"枚举该生产者输出到 run 执行之间的全部闸门，判定是否存在任一合法通道"。

## Short path
- 接受设计意图为真值：抑制不是缺陷；把未知量改写为"该语义是否存在任何合法执行通道"。
- 读规则SoT对应条目，提取支撑闸门的不变量（如外部内容未经显式授权不得成为模型输入），作为一切修法必须保留的约束。
- 沿 telemetry 中的来源指针（from=/工具名/id=）定位生产者默认出口，确认未授权路径只产生零 prompt 遥测、不触发 run。
- 枚举同一生产者的其他通道（如一次性 wake）：分别在工具 schema 校验、授权/签名账本、admission/budget 契约的源码行确认拒绝条件。
- 所有闸门均关闭 → 结论为能力缺口：交付新的被授权通道设计（签发方、次数/有效期、幂等、用尽降级为通知），盘点存量受影响条目量化影响，并显式说明为何直接 un-gate 违反支撑闸门的不变量。

## Stop conditions
- 每条候选通道的拒绝条件都已在生产源码 file:line 确认（非仅文档/测试推断），且支撑不变量已从规则SoT读到 → 停止诊断，进入设计与迁移方案。
- 发现任一现有通道其实覆盖该语义（如一次性 wake 已够用）→ 转入该通道内的配置/路由修复并停止枚举。

## Verification
- 每个声称的闸门在生产源码存在可指认的拒绝分支（本例：工具层 wake+周期组合被拒、签名账本拒重复条目、非 wake 条目到点仅归档）。
- 新方案不违反被引用的不变量：未授权外部内容不自动构造 Message/进入 prompt；被调度 run 不能递归签发授权。
- 受影响存量条目已盘点（条数、空转次数），影响结论不建立在单次最显眼症状上。

## Counterexamples
- 抑制无成文规则/测试支撑，可能是回归缺陷 → 走普通根因定位（git log 找引入提交）后在抑制点修复，而非设计新通道。
- 目标语义本就是纯提醒，"生效"等价于 UI/检索可见 → 修可见性与检索路径，不加执行通道。
- 闸门属资源/限流类（rate limit、预算上限、队列深度）→ 在现有语义内调参或申请豁免，不需要新授权机制。
