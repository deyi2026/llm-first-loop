---
method_id: pin-inherited-label-scope-via-closeout-chain-and-source-gap-844e278b0626
name: pin-inherited-label-scope-via-closeout-chain-and-source-gap
description: 续跑/派发指令引用上一会话内部规划自造的批次标签或代号（如 B2、某 P1 项）作为待办范围时，该标签往往没有正式任务定义。先沿最新收口链取指针（最新 goal 状态→最新交付报告→其引用的 spec 节），再在源码定向验证『spec 验收 − 已实现面』的缺口，并用一次任务图查询确认标签是否有正式任务记录；若无，由推导显式声明范围后开工，而不是翻更旧交付报告或重复整读长 spec 找『定义』。与 resume-via-named-provenance 卡互补：那条管状态重建，本条管 provenance 链终止于一个无定义标签时如何钉死范围。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:799:22c6f9fce4316c02c8a6
evidence_refs: learning:learn:1b9e7c66572d
created_at: 2026-10-16T07:01:29.263534+08:00
updated_at: 2026-10-16T07:01:29.263534+08:00
---
## Trigger
用户或调度指令以上一会话内部规划产生的批次标签/代号/简写（如 B2、『P1 项』）指代待办工作，本会话没有该标签的任务书，需要先确定确切范围才能开工。

## Discriminator
当时已可见的事实：最新交付报告已点名该标签并给出括号释义与 spec 引用；对该 spec 做定向 grep 即可取到对应验收行；对 spec 点名的入口/事件名在源码一次 grep 即知读写两侧是否已实现；任务图一次查询即知标签有无正式任务记录。『不存在独立的定义文档』不是障碍——这些事实已把范围收敛为『验收标准 − 已验证现状』，继续枚举文档只会找不存在的东西。

## Short path
- 读最新 goal 状态 + git log 定位最新交付报告：未知量=停点、批次序列、标签指针（标签=哪个 spec 节的哪一项）。
- 按报告引用对 spec 做定向 grep，只读相关节：未知量=该项的验收标准是什么。
- 对 spec 点名的事件/入口/工具面在源码定向 grep：未知量=写入侧与读取侧已实现到什么程度，范围缺口在哪。
- 一次任务图/回执目录查询确认标签是否有正式任务定义：有→读任务书即止；无→下一步。
- 由『验收标准 − 已验证现状』推导范围，显式写出推导依据后开工；不再翻更旧报告、不再整读长 spec 寻找定义句。

## Stop conditions
- 标签在任务图/回执中确有正式定义或任务书：以其为准，停止推导。
- 最新报告批次序列、spec 验收行、源码现状三者均已核实：范围已钉死，进入执行。
- spec 与收口链均不覆盖标签语义：停止考古，向用户确认。

## Verification
- 推导出的范围能在最新交付报告与 spec 验收行中各找到一句直接支撑。
- 『已实现/未实现』结论来自源码 grep 或工具 schema 的当场证据（如 kind enum、事件常量），而非记忆。
- 开工前的范围声明与用户指令中的括号释义一致，或差异已显式披露。

## Counterexamples
- 标签在任务图里确有 open 任务与完整任务书：直接读任务书，不要从 spec 自行推导范围。
- 标签指向内容不在任何 spec 内（会上口头约定的运维杂项）：源码/spec 考古无意义，问用户最短。
- 全新项目无收口报告与 spec：本方法无 provenance 链可用，回退到通用恢复或直接询问。
