---
method_id: anchor-directive-timestamp-diff-authoritative-concurrent-records-31393cedac00
name: anchor-directive-timestamp-diff-authoritative-concurrent-records
description: 多会话并行环境中收到新的策略/流程指令（如部署要『等收口一起上』）时，先以指令接收时刻为锚，对照带时间戳的权威并发记录——事件流中其他 session 的动作、git log/status 的在途改动、服务控制的 barrier/restart 状态——检测竞态窗口内是否已有 actor 做出与策略冲突的动作；不要先做语义记忆检索（按『上线/发布』等词搜索易命中无关业务域历史）。发现冲突时合成时间线交用户裁决，默认不擅自回滚已执行动作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1e362f1c-6242-47df-8cfd-2b1de1b0b20e:1:d1f9b52a276e953ed603
evidence_refs: learning:learn:6ae3c07c0bef
created_at: 2026-10-13T21:24:03.640638+08:00
updated_at: 2026-10-13T21:24:03.640638+08:00
---
## Trigger
在存在并行会话/并发写者的工作区，用户下达一条新的流程或策略类指令（部署节奏、合并策略、协作规则），指令执行依赖『当前在途状态』，且策略自即刻起生效。

## Discriminator
指令有明确接收时刻；architecture_status 的 pending/failed 服务动作与 event_stream 中其他 session 近期的带时间戳动作，在做任何语义检索之前就已把『是否符合新策略』缩为『该 actor 在指令时刻前后做了什么』这个可直接查证的窄问题；而按指令关键词做语义记忆检索会命中其他业务域的历史噪音，不能作为合规判据。

## Short path
- 锚定指令接收时刻；从 architecture_status 的 pending 服务动作与 event_stream 识别活跃并行 session 及其最新动作时间戳
- 对识别出的并行 session 做定向 event_stream 查询，确认其 publish/commit/restart 类动作与指令时刻的先后关系
- git log + 工作区 status/diff 量化『收口』清单：未提交修改、未跟踪文件、未合并提交
- 读服务控制/admission barrier 状态，确认当前部署/重启所处阶段与发起者
- 合成时间线：存在竞态冲突则列出冲突与在途清单请用户裁决，并声明安全默认（不擅自回滚已执行动作、本会话不新增同类动作）

## Stop conditions
- 时间线闭合：各权威记录相互印证，冲突存在与否已确定，在途清单已量化
- 无并行 session 活动且无 pending 服务动作：直接按本会话版本库状态执行策略，无需仲裁
- 用户已裁决冲突选项：停止扩散检查，按裁决执行

## Verification
- 每条时间线断言都对应一条带时间戳的权威记录（事件条目、git commit、barrier created_at），不靠推测『对方没收到消息』
- 并行 actor 动作时间与指令接收时间的先后顺序可由第三方记录复核
- 向用户呈现的默认选项不包含任何未经授权的回滚/撤销动作

## Counterexamples
- 单会话环境无并发写者：无需查并行记录，本会话版本库 status 即为全部在途事实
- 指令是内容域操作规范（如发文时的声明勾选约定）：语义记忆检索才是正确来源，事件流/部署状态无关
- 纯前瞻性指令不依赖当前在途状态（如『以后都用中文回复』）：直接确认执行，无需状态重建
- 并行 actor 的动作本就符合新策略（已在批量收口）：无冲突可报，确认合规后继续，不制造伪仲裁问题
