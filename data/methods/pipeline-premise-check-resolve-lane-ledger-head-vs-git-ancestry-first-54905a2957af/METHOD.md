---
method_id: pipeline-premise-check-resolve-lane-ledger-head-vs-git-ancestry-first-54905a2957af
name: pipeline-premise-check-resolve-lane-ledger-head-vs-git-ancestry-first
description: 执行既定合并管线（rebase→重跑ci_gate→重签凭证→排队）前，管线的前提『我的工作尚未入 main』必须与外部条件一起核实：读名下 lane 的权威账本，若记录 head 与本地分支 HEAD 不一致（出现不认识的提交）或状态停在 merging/verifying 而我并未在收口，说明他人已代推进/代合并。先在 git 对象面解析该 head（show / branch --contains / merge-base --is-ancestor 对 main）：已入 main ⇒ 整条管线坍缩为收口记账（lane_close(merged) + 新 main 定点复验 + 解除对他人的 push 阻塞），不再 rebase/重验/重签/排队；未入 main 才按原管线等条件执行。
aliases: rebase计划还要不要做, lane卡merging是不是被别人合了, 账本head和工作区对不上, 排队前先查lane是否已被代收口, 陌生提交已入main
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:2773:2f52036c1acaacc27059
evidence_refs: learning:learn:23044af239c5
created_at: 2026-11-09T18:23:05.890813+08:00
updated_at: 2026-11-09T18:23:05.890813+08:00
---
## Trigger
并发协作仓库中续跑『等外部条件满足后对我的工作单元执行多步合并管线』的既定计划，或发现名下 lane 账本状态与本地实际不符时

## Discriminator
账本记录的 lane head SHA ≠ 本地分支 HEAD（存在不是我创建的提交），或账本停在 closing 态而我没有任何收口动作在进行——这是他人代推进/代合并的可观察信号，先解析该提交身份再谈管线

## Short path
- 用一次定点探测回答任务问的外部条件（如 main tier0 红绿），不做宽枚举
- 读名下 lane 账本条目（路径由闸源码/队列工具直接给出），比对 head vs 本地 HEAD、status vs 实际活动
- head 不一致 ⇒ 在 git 对象面解析：git show 该 head；branch --contains / merge-base --is-ancestor 对 main
- 是 main 祖先 ⇒ 管线前提被证伪：跳过 rebase/重验/重签/排队，只做收口（lane_close(merged)+新 main 上定点复验+回复被阻塞方）
- 非 main 祖先 ⇒ 前提成立，等条件满足按原管线走；本地存在超出账本 head 的新提交 ⇒ 管线只覆盖增量

## Stop conditions
- 名下 lane 已终态（merged/closed），且不再有我方 closing 态 lane 阻塞他人 push
- 前提裁决已带证据上报：代收口 merge 的 parents 同时含旧 main 与 lane head
- 新 main tip 上对本 lane 涉及路径的定点测试通过

## Verification
- git show --format=parents 确认 merge 提交 parents 含 lane head
- 新 main 上只跑本 lane 涉及的定点测试而非全量
- 重读账本确认自己 lane 终态、原先被阻塞方的 push 不再被挡

## Counterexamples
- 账本 head 与本地 HEAD 一致且不在 main：无错位，前提成立，照原计划走管线，不要臆测代合并
- 本地曾 rebase 改写历史：账本旧 SHA 在 main 不覆盖新提交，增量仍需走管线（祖先判定只对当前工作 head 有效）
- 单写者仓库无并发会话：账本出现陌生 head 更可能是 store 损坏而非代合并，应先查账本完整性
- 包含该 head 的只是镜像/非权威远端分支：只有权威 main 的祖先关系才能证伪管线
