---
method_id: divergence-direction-from-per-side-commit-lists-not-ahead-behind-labels-426541ec0e5f
name: divergence-direction-from-per-side-commit-lists-not-ahead-behind-labels
description: 本地分支与远端同名分支双向分叉、且方向影响集成顺序或『会不会覆盖他人提交』类决策时，ahead/behind、left/right 等方向性两数表述（任务简报的压缩语、echo 自贴标签）都可能被读反或互相矛盾。不要在标签层面裁决谁对，立即把两侧各物化成一次按侧短列表（每侧独有 commit 的 oneline 主题），按内容身份归类（本地工作线命名 vs 远端 PR/发布命名），把『方向』改写成两个 commit 集合的陈述后再做对照与决策；报告与后续集成顺序只引用集合，不引用标签。
aliases: ahead behind 哪边多搞不清, 分叉方向搞反了, 两个数哪边是本地哪边是远端, 谁领先谁落后怎么确认, 用提交列表核对分叉方向, origin 比本地多几个提交
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4ea6a78e-8253-4002-b27b-26c495af4605:1:a345f16f1d43d7f81ad6
evidence_refs: learning:learn:24e351eff1d7
created_at: 2026-11-16T01:30:35.042176+08:00
updated_at: 2026-11-16T01:30:35.042176+08:00
---
## Trigger
本地分支与远端同名分支双向分叉，任务简报或工具回执把分叉表达为方向性计数（ahead X / behind Y、left/right 两数、『某侧独有 N』），且该方向会被用于集成排序或安全判断（如先集成谁、是否可能覆盖他人提交）。

## Discriminator
方向性计数天然歧义：ahead/behind 是读者相对的，left/right 依赖命令参数序，echo 自贴标签可能写反——同一对数字在任务文本与工具回执里可能指向相反方向；而两侧 commit 的内容身份（本地修复/功能线命名 vs 远端 PR/发布/受管部署提交）是无歧义的绝对判别物，且在计数出现当时就已可低成本取得。

## Short path
- 多 remote 时先按 URL 身份线钉死权威远端，再取两数计数，并记录产生该计数的确切参数序（哪个引用在左、哪个在右）。
- 任何方向性结论落地前，两侧各物化一次短列表：每侧独有 commit 的 oneline 主题（两条按侧 range log）。
- 按内容身份归类两侧（如本地工作分支名 vs 远端 PR/发布提交名），把『方向』改写为两个 commit 集合的陈述，并给出各侧规模与代表性主题。
- 与简报中的方向性说法对照：一致则标注一致；矛盾或含糊则以集合为准，显式写明『方向已按实值澄清』及两侧各是什么。
- 后续所有集成顺序、覆盖风险讨论与最终报告只引用两个 commit 集合，不再引用 ahead/behind 或 left/right 标签。

## Stop conditions
- 两侧 commit 集合已物化、内容身份归类完成，方向可由集合直接读出且与简报说法的对账已记录。
- 一侧为空（纯 fast-forward）或当前问题只需布尔判断（是否最新/是否需要 pull）时，物化列表即停止。

## Verification
- 每侧抽查 1–2 条 commit 的实际内容归属，确认与集合归类一致（本地线确实落在声称的一侧）。
- 把最终方向陈述还原为带参数序的计数复核：两侧集合大小应与最初两数一一对应。

## Counterexamples
- 只需回答『是否已同步』这类布尔问题时，物化两侧列表是过度动作，计数即可。
- 两侧 commit 主题被 squash/rebase 成无信息量（全是 merge 或相同前缀）时，内容归类失效，须退回 SHA+patch 级检查，本方法归类步不可用。
- 纯 fast-forward（一侧为空）时标签无歧义，无需此流程。
