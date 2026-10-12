---
method_id: resolve-handoff-pending-check-before-broad-history-search-2535072636ef
name: resolve-handoff-pending-check-before-broad-history-search
description: 跨会话状态问询（X 进展到哪了）且会话全新时：先读最近 action trace，识别上次会话遗留的未决验证（如在等的 CI/轮询结果），把它作为第一未知量直接到 ground truth 解掉；历史检索只做一次线程枚举，不换关键词变体重复宽搜、不查已知为空的源；枚举出的每个线程用一次权威状态检查（CI 结果/merge 状态/链尖提交）定态，全部线程有权威状态即停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:0:026dad93da29cf7f97b7
evidence_refs: learning:learn:9835d82d535d
created_at: 2026-09-19T11:03:28.333953+00:00
updated_at: 2026-09-19T11:03:28.333953+00:00
---
## Trigger
新会话无活动 Goal/Evidence，用户询问某主题的当前进展或状态，且最近 action trace 显示上次会话以未完成的验证动作收尾（等待 CI、轮询某个可查询结果）

## Discriminator
trace 中可见的最后动作即'等待某个可查询结果'（如 gh run list 轮询 main CI），加上 list_evidence 已回执'当前会话无 Evidence'——这两条当时已知事实把'进展'从全源关键词宽搜缩成：先解该 pending 验证，再对历史枚举出的线程逐个查 ground truth。

## Short path
- 读会话状态与最近 action trace，识别遗留未决验证；第一未知量=该验证现在的结果（如 main CI 是否通过）
- 用单一关键词做一次历史/事件检索，枚举该主题全部工作线程（分支链、worktree、EVO、经验记录），不做多源关键词变体并行
- 一次组合命令取 ground truth：上次 pending 检查的结果 + 各线程是否合入 main + main 上相关提交
- 对未合入线程查链尖最后提交与 ahead/behind 数，得出冻结点与时间
- 所有线程均有权威状态后停止并作答；不再对 docs/摘要做关键词变体重搜

## Stop conditions
- 上次遗留的 pending 验证已有权威结果（CI 结论明确）
- 枚举出的每个线程都有 ground-truth 定态：已合入（有提交号）或冻结于某提交且确认无 open PR

## Verification
- 每条状态结论对应可复查权威来源：CI run conclusion、git merge/cherry 结果、分支 tip commit 与 ahead/behind 数
- docs/搜索摘要只作线索不作为进展真值；真值以 repo 与 CI 为准

## Counterexamples
- 上次会话以完整答复收尾、trace 无 pending 验证时，不存在'先解 pending'入口，应直接从一次历史枚举开始
- 主题没有 repo/CI 等 ground truth（纯讨论类）时，权威状态就是历史记录本身，git/gh 检查不适用
- 用户问'为什么停在那里/决策理由'而非'进展到哪'时，merge 状态不足以作答，必须读冻结文档与决策记录
