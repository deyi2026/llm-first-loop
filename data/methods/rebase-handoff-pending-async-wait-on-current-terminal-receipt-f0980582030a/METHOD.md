---
method_id: rebase-handoff-pending-async-wait-on-current-terminal-receipt-f0980582030a
name: rebase-handoff-pending-async-wait-on-current-terminal-receipt
description: 接手跨会话交接时，交接中『某机制等待中、条件满足后自动完成』的未了项是最不可信的一类断言：其真值可在交接写完后无任何写者更新的情况下悄然翻转（等待超时→failed），且发起方自身常是阻塞者。方法：把该 pending 项当唯一未知量，用其显式 action/机制 id 直查当前权威 terminal 状态与原因，而非整读被审计历史占据的大快照；若已 failed，按该机制已验证协议接管——重发后立即收尾本 run、不轮询不 override，并注册 wake 执行交接遗留的核验清单。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89b60cd3-41c3-4e13-ba52-f4f3dcd83454:9:3658851d36259e3e27da
evidence_refs: learning:learn:d03934816945
created_at: 2026-10-13T20:52:06.992561+08:00
updated_at: 2026-10-13T20:52:06.992561+08:00
---
## Trigger
接手跨会话/跨执行体交接，交接除已完成事实外还点名一个『等待中、预期自动完成』的异步机制（如 restart/deploy/屏障等待），并委托后续会话核验其结果

## Discriminator
交接已给出该机制的显式 action id 与『等待→自动完成』语义；且当前服务/机制回执中可见 terminal 字段（stage_fact、barrier、live HEAD vs desired deployment）。凡等待机制都有 patience 上限：『发起至今耗时』已超上限、或回执已示 failed/barrier=null，即证明断言过期。判别只需当时已有的 id 与当前回执字段，可直查该 action 自身落地记录，不必先翻完整运行时快照。

## Short path
- 并行取交接三项关键事实（goal 状态、服务/机制运行态、报告核验清单），声明文本本身不算数
- 把交接点名的 pending 机制作为唯一未知量：用其显式 action id 直查该 action 当前 terminal 状态与失败原因，而不是先分页整读被 generation_lag 类审计历史占据的大快照
- 若回执仍为 waiting 且阻塞前置（如 requester 仍活跃）成立→不重发，只注册 wake 等自然完成；若已 failed→按该机制已验证的接管协议重发，发起后立即收尾本 run，不轮询不 override
- 重发前仅从快照取接管前置：无 admission barrier、desired deployment 就绪（gen/HEAD 对齐）、busy 归因确认（active run locks 含本会话）
- 注册 wake 执行交接遗留核验清单（HEAD/generation/存活/冒烟），本 run 立即结束，偏差如实报告

## Stop conditions
- pending 项当前回执仍为 waiting 且其阻塞前置成立——不重发（避免双写冲突），只挂 wake 复核
- 已从 action 自身记录取得 terminal 原因并完成接管（重发+本 run 收尾）——停止继续翻查失败历史
- 交接全部声明均已被当前回执证实/证伪且偏差已处置——收口

## Verification
- 重发后的新 action id 与 desired generation 已记录在案；wake 时长小于机制 patience 上限
- 交接声明逐条对照当前回执，偏差（本例 stage_fact=failed ≠ 声明 waiting）在最终答复中如实标注
- 只验证状态类事实；已闭合的重结论（如全量回归）不重跑

## Counterexamples
- 当前回执显示机制确在等待且前置成立（requester 仍活跃）——重发可能双写冲突，应等待或仅 wake
- 交接只含已完成事实、无 in-flight 项——存在性抽查即可，无需深挖机制记录
- 机制无 patience 上限且由外部 supervisor 兜底重试——failed 可能自愈，先观察再接管
- 『自动完成』由外部事件触发且无 action 落地记录——action-id 直查捷径不可用，只能定时复核当前回执
