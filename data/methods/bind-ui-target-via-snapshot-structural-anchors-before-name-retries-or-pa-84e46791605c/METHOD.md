---
method_id: bind-ui-target-via-snapshot-structural-anchors-before-name-retries-or-pa-84e46791605c
name: bind-ui-target-via-snapshot-structural-anchors-before-name-retries-or-page-pivots
description: 当 semantic snapshot 里同名元素跨行重复、或 accessible name 含零宽字符等不可见字节导致 match_count=0 时，不要改写 name 变体重试，也不要弃掉已定位的证据去打开别的页面找替代控件。snapshot 当时已给出更窄的身份锚：对象唯一 id/grounding_ref、parent/child relations、行内 href 等唯一属性。先用这些结构关系把候选从 N 个同名元素缩到 1 个（行容器→目标按钮），再以对象引用或逐字节精确 name 提交操作。失败回执 receipt_ref 与上次相同时说明命中同输入缓存，必须换定位输入而非换措辞重发；导航后旧 id 作废，先重取 snapshot 再动作。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9f3f9ab8-30d9-4a2d-9f58-148054503778:2032:4675863b05297e3893f8
evidence_refs: learning:learn:09093b7385d0
created_at: 2026-10-11T00:02:15.861109+08:00
updated_at: 2026-10-11T00:02:15.861109+08:00
---
## Trigger
需要对 snapshot 中已观察到的页面元素执行点击/操作，但 accessible name 跨行重复或含不可见字符（出现 target_not_found / match_count=0），同时 snapshot 已提供 id、grounding_ref、relations 或 href 等可作身份锚的结构事实。

## Discriminator
第一次失败之前 snapshot 已可见：每个候选对象都有唯一 id/grounding_ref；目标行的 title link href 唯一含 entity ID；同名按钮各自携带 parent/child relations 可绑定到具体行。这些事实足以把 N 个同名候选缩成 1 个精确目标，无需 name 猜测、变体重试或转去其他页面另找入口。

## Short path
- 未知量「目标是哪个对象」：在当前 snapshot 内先找 href/属性唯一含目标 entity ID 的行元素，不新开页面。
- 沿 relations（parent/child）定位该行容器内的同名元素，取得其 id/grounding_ref；未知量「工具接受什么定位输入」——一次试探即可判定，用对象引用或逐字节复制 name 属性（含零宽前缀等不可见字节）。
- 读回执分支：match_count=1 且 receipt_ref 为新值 → 完成；若 receipt_ref 与上次失败完全相同 → 命中同输入缓存，改变定位输入（换 id/ref 或 selector），不重发原输入。
- 若期间发生导航或 document/scope generation 变化，旧 snapshot 与 id 一律作废：重新 snapshot 后再定位执行。
- 目标事实（行归属、元素存在性）已被最新 snapshot 与回执交叉验证即停止，不继续枚举入口或替代通道。

## Stop conditions
- 回执 match_count=1，且所引用对象 id/grounding_ref 与最新 snapshot 一致，操作效果已确认。
- 最新 snapshot 显示目标元素根本不存在（区别于同名冲突/名称字节问题）→ 才转入换入口、换通道或询问用户。
- 操作不可逆且结构绑定仍不确定 → 停止探测式点击，向用户确认后再动作。

## Verification
- 回执 match_count=1，且 receipt_ref 与此前失败回执不同（排除同输入缓存）。
- 所用对象引用出自最新 snapshot，observed_version/world_version 与当前页面 generation 一致。
- 操作后重观察页面状态（如行数、元素存在性）确认效果，而非仅凭回执 status=success。

## Counterexamples
- kinds 过滤返回 matched_total=0（如本集复选框查询）：元素确实不存在，属功能缺失结论，正确动作是换入口/通道，不适用本方法强行定位。
- snapshot 输出不含 id/relations/结构属性（纯文本转储）：结构锚不可用，需先取得结构化观察再定位。
- 刚发生导航、scope/generation 已变：旧 id 已过期，必须先重取 snapshot，套用旧引用会失败或绑错行。
- 目标页面类型本就不承载该控件（如公开文章页无作者管理按钮）：这是「功能不在此页」而非定位问题，不应在错误页面上反复找按钮或据此下错误结论。
