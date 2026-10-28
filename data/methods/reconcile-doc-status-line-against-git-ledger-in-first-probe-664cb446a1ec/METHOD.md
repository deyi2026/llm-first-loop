---
method_id: reconcile-doc-status-line-against-git-ledger-in-first-probe-664cb446a1ec
name: reconcile-doc-status-line-against-git-ledger-in-first-probe
description: 重建『权威状态摘要内嵌在版本库文档头部』的项目的当前进展时，文档状态行可能与 git ledger 脱节：定时任务/异步执行者已把新结果 commit，状态行却停在旧版本。开局首轮并行探测就应带上 git log（可限定治理文档路径）并与状态行声称的最新版本比对；ledger 新于状态行 ⇒ 先读这些新提交对应的小节/回执，再逐项读悬念回执；任何中期状态总结须以 ledger+回执为准，滞后状态行先修订提交再给建议。与 fresh-read（成稿前重读）和 resume-via-git-delta（续跑指令）互补：本条管开局对账的时序。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:1251:36a1c5ad68e46b1b2886
evidence_refs: learning:learn:a697adaea73d
created_at: 2026-10-16T08:55:26.611746+08:00
updated_at: 2026-10-16T08:55:26.611746+08:00
---
## Trigger
会话开局需重建项目当前状态并给下一步建议，且项目把状态摘要内嵌在版本库文档（状态行/changelog 头），同时存在定时任务或并行执行者会异步提交新结果。

## Discriminator
首轮探测即可得的对账事实：git log 最新提交（含该文档路径）是否新于状态行声称的最新事件/版本；或 evidence/mtime 显示文档近期被改过而状态行最新事件停在更早时点。二者不一致 ⇒ 状态行是陈旧摘要，不能作为终局事实源。

## Short path
- 首轮并行探测合并 git log（限定 -- <治理文档> 与相关输出目录）+ git status --short，与读状态行、目录 mtime 同批执行；未知量：自上次会话后账本上实际发生了什么。
- 比对 ledger 最新提交与状态行声称的版本/事件；未知量：文档摘要是否当前。
- ledger 存在状态行未提及的提交 ⇒ 先读这些提交对应的文档小节及其回执（真实最新结果），再读各悬念项回执，避免按陈旧摘要框架化。
- 工作树为 M 状态时区分『已提交事实』与『未提交追加』（定时任务常只追加不改头部）。
- 事实齐备且状态行滞后 ⇒ 修订状态行并只提交该文档收口，再输出建议；每条『最新事实』须映射到 commit 或已读回执。

## Stop conditions
- ledger 与状态行一致（无比对差异）且关键回执已读 ⇒ 直接总结，跳过修订步骤。
- 所有待核事实均已由 commit hash 或已读回执支撑 ⇒ 停止取证，进入建议。
- 用户只问某一具体回执 ⇒ 直接读该回执，无需全局对账。

## Verification
- 最终总结中每条『最新事实』都能指到具体 commit hash 或已读回执的 evidence ref。
- 修订后状态行版本不低于 ledger 中该文档最新事件版本，且收口提交只含该文档。
- 对账在首轮完成：不存在基于状态行单独给出的中期状态结论。

## Counterexamples
- 文档不在版本库内、或无内嵌状态行 ⇒ 无对账面，直接读回执即可。
- 状态行维护规约是『与事件同 commit 更新』且从未滞后 ⇒ 比对恒真，属多余步骤。
- 并行轨道高频提交且与目标子系统无关 ⇒ 不限定路径的宽 log 反而引入噪声扩散；须限定 path/author。
- 用户提供明确且唯一的核查点（只问某一份回执是否存在）⇒ 跳过全局对账直接读。
