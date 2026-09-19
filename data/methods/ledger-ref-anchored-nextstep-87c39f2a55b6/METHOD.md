---
method_id: ledger-ref-anchored-nextstep-87c39f2a55b6
name: ledger-ref-anchored-nextstep
description: 目标台账/完成回执已写明交付物所在分支与 commit 时，把验证锚定到该 ref（git log <ref>、git show <ref>:<path>），而不是当前工作区——HEAD 可能停在另一条带未提交改动的分支，对工作区做路径存在性检查是在检验错误假设。'下一步'方向优先取自已落盘 artifact 自声明的续作/复用条款（如 future-work 段落），而非开放式文档检索；HEAD 分叉与远端 ahead/behind 用一条廉价命令量化后交用户拍板。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:201:ebfa32fd11c4762d038d
evidence_refs: learning:learn:5755ff0536f8
created_at: 2026-09-17T22:38:04.370278+00:00
updated_at: 2026-09-17T22:38:04.370278+00:00
---
## Trigger
多步目标闭合后用户询问下一步建议；开局工具回执（goal ledger/完成回执）已明确命名交付物落地的分支与 commit（例如 '落 main（a994aa30）'），而当前 checkout 可能停留在其他分支。

## Discriminator
台账回执是否已给出权威 ref+commit。若有，此事实在动手查盘前即可把候选空间从『整个工作区+全文档检索』缩到『一个 ref 上的两三份文件』：路径核对应指向 <ref>:<path> 而非磁盘；续作方向的权威来源是落盘 artifact 的 future-work 原文，不是 docs 全文搜索。

## Short path
- 解析 goal 回执，提取权威 ref（分支+commit）与其自述的后续方向——未知量：交付物真值在哪里？
- 一条廉价命令确认 HEAD 与脏状态（branch --show-current + status --short）：HEAD≠权威 ref 时记为风险项，而非沿工作区路径试错到报错才发现
- git log <ref> 验证交付 commit 可追溯；git show <ref>:README / PROTOCOL 读取使用契约与 future-work 原文——未知量：续作方向的第一证据
- 量化 <ref> 与远端分叉（rev-list --left-right --count）作为需用户裁决的收敛成本项
- 由以上权威事实推导按价值排序的建议并停止；不发起与刚闭合目标无关的开放式检索

## Stop conditions
- 交付物已在台账指名 ref 上以 commit 追溯验证存在
- artifact 自声明的续作/复用方向已读到原文
- HEAD 分叉与远端 ahead/behind 已量化并标注需用户拍板
- 用户所需事实齐备即停止，不做『再多确认几个』式的补充枚举

## Verification
- 每条建议可回指工具回执中的具体 commit/分支/原文行
- 'reuse this pattern' 类主张与 <ref> 上 PROTOCOL/README 的实际文本一致
- 分叉数字与 git 回执一致；未引用当前工作区中不存在的路径

## Counterexamples
- 交付物就在当前工作区（HEAD 即权威 ref）时，直接检查工作区路径即可，ref 间接寻址是多余开销
- 台账/回执未指名 ref 与 commit 时，需先发现权威位置，不能假定 main
- 用户问的是与刚闭合目标无关的开放性方向（如历史技术选型）时，检索决策文档是正当动作而非扩散
