---
method_id: deletion-shaped-review-findings-suspect-stale-base-first-3b3e9175c4ca
name: deletion-shaped-review-findings-suspect-stale-base-first
description: 向共享 main 合并的长任务候选收到委派审查『净删除 main 已有特性/回退已落地修复』级发现、但点名文件不在自有 diffstat 变更面内时，第一未知量不是内容怎么修，而是审查 base 是否落后 main 现头：用一组 git 拓扑事实（main 现头、分支 tip、merge-base 祖先、worktree vs HEAD diffstat）覆盖快照声明的基线，把真增量重述为相对现头的 diff，固化 WIP 后重放到现头，冲突按『自有增量胜出、main 侧已落地修复保留』逐文件裁决，再复审。
aliases: 审查说我删了没动过的文件, P1 净删除像是基线落后的假象, 分支落后 main 审查误报回退, 冻结送审前先对 main 现头重放, 删除型发现先核 merge-base
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:5265:8d751c46a96eecc772ea
evidence_refs: learning:learn:6deec3660c98
created_at: 2026-11-09T08:33:57.732531+08:00
updated_at: 2026-11-09T08:33:57.732531+08:00
---
## Trigger
长任务分支/异步委派审查后向共享 main 合并：审查回执含『净删除 main 已有特性/回退已修复缺陷』级发现，且点名的文件或符号不在你自有变更面（diffstat、提交说明均未触碰）内；或冻结候选送审/push 前，快照声明的基线早于 main 现头（异步审查期间 main 可能继续前移）。

## Discriminator
两条当时可见事实的矛盾：①发现形状（删除某 main 侧符号/文件）与自有 diffstat（新增面 + 少数共享文件修改）不相交；②merge-base 非 main 现头祖先。二者任一成立即可把『逐条内容排查』缩成『基线重放』。快照/回执里声明的 base 不是 git 真值，必须以 live git 事实为准。

## Short path
- 把每条删除型发现映射到自有 diffstat：点名文件是否在自有变更面内？面外且拓扑可疑 ⇒ 基线偏移假设优先于内容修复。
- 一条命令组核实拓扑：main 现头、分支 tip、merge-base 祖先关系、worktree 相对 HEAD 的 diffstat；用 git 事实覆盖快照声明的基线。
- 把真增量重述为 worktree 相对 main 现头的 diff：逐共享文件数行数，区分纯新增与真实回退（面内文件被回退才是真发现，需单独修）。
- worktree 先固化为 WIP 提交（防重放过程丢失），再从 main 现头新建分支重放；冲突逐文件按『自有增量胜出、main 侧已落地修复必须保留』裁决。
- 重放分支跑定向测试 + 复审；确认相对现头的 diff 不再含任何面外删除后走合并闸。

## Stop conditions
- 拓扑核实显示分支 base 即 main 现头 ⇒ 基线偏移假设证伪，转内容修复。
- 某条发现点名的文件确在自有变更面内（有意弃置的测试/接口）⇒ 按内容决策处理并在设计文档记录理由，不归因基线。
- 重放后相对 main 现头为纯增量、定向测试与复审 PASS ⇒ 基线问题闭合。

## Verification
- merge-base 显示 main 为新分支祖先（或 squash 后 diff 中无面外删除）。
- 曾被点名的 main 侧符号/修复在新分支中逐字存在（对照审查回执里的具体函数/谓词名）。
- 重放分支逐文件核对删除行：每一处删除都能归属为自有有意变更。

## Counterexamples
- 发现点名的文件确实在你 diffstat 内被删除（有意 deprecate 旧接口/测试）⇒ 这是内容决策，需文档化说明，怀疑基线只会延误修复。
- 单人仓库或 main 冻结期无并行推进，审查 base 已核实为现头 ⇒ 删除就是真回归，直接修内容。
- 审查明确声明以你分支 tip 为 base 且拓扑核实一致 ⇒ 发现即内容问题，勿先核基线。
