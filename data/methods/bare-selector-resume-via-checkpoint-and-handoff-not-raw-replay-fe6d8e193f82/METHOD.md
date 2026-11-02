---
method_id: bare-selector-resume-via-checkpoint-and-handoff-not-raw-replay-fe6d8e193f82
name: bare-selector-resume-via-checkpoint-and-handoff-not-raw-replay
description: 用户以裸选择符（如单个数字『2』）恢复一段已被压缩的裁决会话时，重构入口应是状态面而非历史面：先取最近一条 goal 级 checkpoint 汇总，再直读交接/现状文档中被点名的未决裁决小节，最后只对裁决点名的事实做定点新验证。判别信号：原始会话档案回执里条目 chars=0、original 为空、sha256 为空串哈希，说明档案是纯索引，分页或顺其引用逐条 hydrate 只会拿到与决策无关的机械回执。
aliases: 用户只回一个数字 恢复上下文先读什么, 裸选项指令怎么重构裁决, 会话档案条目全空还翻吗, checkpoint 汇总优先于翻原始消息, 重构未决裁决从哪入手
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:1823:2a1d5467d506a22ab3d9
evidence_refs: learning:learn:f7493c8507df
created_at: 2026-11-01T10:28:31.793923+08:00
updated_at: 2026-11-01T10:28:31.793923+08:00
---
## Trigger
用户以极简令牌（单个数字/单词）从已被压缩或跨会话的上下文中选定一个未决裁决并要求执行，需要先重构『被选项指什么、执行与验收口径是什么』

## Discriminator
重构伊始的首个原始会话档案回执中，条目全部 chars=0、original 为空、sha256 为空串哈希——该档案是纯索引不含决策正文；同时 evidence 库按记录种类显式区分出 goal 级 checkpoint 汇总（『累计 N 次 | 最新…』式状态摘要）与命名的交接/现状文档。这两类事实当时即可见，足以把『翻全部历史』缩为『读两个状态面』。

## Short path
- 未知量=选项②指哪条裁决：取最近一条 goal/checkpoint 汇总记录读状态摘要，而不是翻原始会话档案或逐条 hydrate 消息快照
- 未知量=裁决的交付物与验收口径：直读摘要/检索命中的交接或现状文档中被点名的未决裁决小节，得到具体交付物清单
- 未知量=文档口径是否仍为真：只对裁决文本点名的事实做定点新验证（提交祖先关系、干净副本 apply-check/apply/reverse-check、直读现行源码对应函数）
- 无法当场验证的项如实标注为未验证边界；交付补丁与沙盒外步骤后即停，不再枚举其他来源

## Stop conditions
- 裁决小节中每一条验收项要么有本轮新回执支撑、要么被显式标注为未验证边界
- 用户所需事实已由命名权威面（checkpoint 汇总/交接文档）加定点验证闭合，无『沿用旧口径』断言

## Verification
- 交付物内每条状态断言可回指本轮回执或权威文档小节，未混入未经复核的旧结论
- 补丁类交付在干净副本上 apply-check/apply/reverse-check 三验通过

## Counterexamples
- 档案条目非空（chars>0、original 含正文）时，近端 assistant 消息可能正是①②③选项原文，读档案尾部反而是正确首步
- 一次性会话、无 checkpoint/交接文档存在时，从会话历史重构是唯一途径，本方法不适用
- 选项列表就在上一轮未压缩上下文里，无需任何重构，直接执行即可
