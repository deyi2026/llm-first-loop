---
method_id: component-default-lookup-via-source-constant-chain-fc7cc626c012
name: component-default-lookup-via-source-constant-chain
description: 被问某子组件的参数默认值/上限（轮数、超时、预算）而运行时状态只覆盖主循环时，先从已读回执（工具 Schema 文本、运行时配置）提取当前值与全局硬上限以界住答案空间，再用一次定向源码检索进入定义链（构造器默认赋值 → 常量 import → 字面量），链闭合后同时解出『数值是多少』与『能否/是否放大』两个子问题。records/docs/event 历史只含实例不含默认值，留到定义链断裂后才用。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:253:c06ad36b208b12532692
evidence_refs: learning:learn:deb73b321d46
created_at: 2026-10-17T20:32:39.787350+08:00
updated_at: 2026-10-17T20:32:39.787350+08:00
---
## Trigger
用户或任务询问某子组件（子代理 runner、worker、队列等）的参数默认值或上限（轮数、超时、预算），组件源码在当前工作区可检索；已读到的运行时状态/工具 Schema 只报告了主循环或调用方的对应值，问题针对的是子组件自身。

## Discriminator
摩擦点之前已读的 adjust_strategy Schema 文本显式写出全局硬上限数值、architecture_status 给出当前值——答案空间已被界住，剩余未知量只是一个静态定义事实：『子组件构造器默认取什么』。对定义事实，权威来源是源码赋值语句及其常量 import（定义链）；records/docs/event 只提供实例或叙述，无法证明默认值。

## Short path
- 从已读回执提取界：当前值（如 max_iterations=500）与 Schema 文本中的硬上限，把问题缩为『子组件默认值是什么』这一单一未知量
- 对该参数名做一次定向内容/文件名检索，限定在目标组件源码（如 subagent runner），取得默认赋值语句（MAX_ITERATIONS = HARD_CAP_MAX_ITERATIONS）
- 沿赋值语句中的常量引用（import/provenance edge）检索常量定义文件，取得字面量，定义链闭合
- 交叉验证：字面量 vs 已知硬上限；相等则『是否需要放大』同链得解（已顶格且不可超上限→结论是拆分接力而非放大），一次回答两个子问题
- 停止；不查 records/docs/event_stream，除非定义链断裂（默认值动态计算或由调用方覆盖）

## Stop conditions
- 定义链闭合：默认赋值→常量定义→字面量全部读到，且字面量与 Schema/运行时回执中的硬上限一致，或差异已定位到明确 override 路径
- 用户的两个子问题（数值是多少、能否/是否放大）均可由该链推出，无需经验数据补证

## Verification
- 三方一致：子组件源码默认 == 常量字面量 == 已知全局硬上限；不一致时先找 per-spawn/配置覆盖路径再作答
- 确认默认值所在代码路径确实是子组件实际执行路径（无中间层强制改写默认）

## Counterexamples
- 参数为动态值：spawn 时由调用方显式传入（如 max_rounds 参数）或按任务规模计算 → 源码默认不等于实际值，应查调用点/运行记录，本方法不适用
- 问的是经验事实（『子代理实际用了多少轮、余量是否充足』）→ event/records 才是权威来源，定义链不回答该问题
- 工作区源码版本与实际 runtime 不一致（镜像仓/旧分支）→ 源码字面量只对当前 checkout 成立，需以运行时回执优先
- 参数定义在配置文件/环境变量而非代码常量 → 应检索配置层而非源码常量链
