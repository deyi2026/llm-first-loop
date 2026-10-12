---
method_id: truncated-record-hit-recover-from-same-store-2d655d402037
name: truncated-record-hit-recover-from-same-store
description: 当按精确 ID/kind 检索结构化记录（审批、演进建议、审计日志）已命中目标但回执被截断时，截断是显示/传输限制，不代表记录缺失。应留在同一记录源取全文：按 ID 请求完整字段或更大 limit；若工具层无法返回全文，则按记录 kind 的命名族（evol|suggest|review|audit）在数据目录用 ls+grep 文件名定位 backing 文件（如 evolution_suggestions.jsonl），再按 ID 解析取全文与状态。禁止动作：对含 zip/b64/log 大文件的树做全库 content grep（必然超时）；把「换个介质再搜一遍」当作截断的第一反应。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:141:1f609dcf122ef42db503
evidence_refs: learning:learn:75e8f3e49250
created_at: 2026-10-11T01:19:42.696624+08:00
updated_at: 2026-10-11T01:19:42.696624+08:00
---
## Trigger
需要读取一条结构化记录（审批/建议/审计类）的完整原文与当前状态；检索已按精确 ID 命中恰好 1 条且时间戳与外部回执一致，但返回文本被截断。

## Discriminator
当时已知的两条事实：(1) 用户回执已给出精确记录 ID 与新状态（executing）；(2) search_records(kind=evolution, query=该ID) 恰好返回 1 条命中——权威 store 已被证明持有完整记录，未知量只剩「全文原文」。这把候选空间从「全库任意文件」缩到「同一 store 及其按 kind 命名的 backing 文件」，无需任何新搜索。

## Short path
- 用已有事实锁定未知量：ID 与状态已在回执中，缺的只是全文原文——不需要重新发现「是哪条记录」。
- 优先同一 store 取全文：按精确 ID 请求完整记录/更大 limit；截断≠缺失，不换介质（本集中 event_stream 返回的是会话自身 action_trace，属另一 store，证明换介质无收益）。
- 若 store 工具仍只回截断文本：对数据目录做一次 ls + 按记录 kind 命名族 grep 文件名（evol|suggest|review|audit），定位 backing 文件（如 data/audit/evolution_suggestions.jsonl）。
- 对该文件按 ID 精确解析（python/jq 单条命令）取全文与 status；绝不全库 content grep——目录含 zip/b64/log 大文件时必超时。
- 校验 id/ts/status 与回执一致后停止发现，进入执行（该路径约 2 次调用，对比实际的 ~7 次含 2 次 60s 超时）。

## Stop conditions
- 已从与首次命中同源、ID+时间戳与回执一致的记录中取得完整原文与当前状态。
- 确认该 store 无法提供全文且不存在可按名定位的 backing 文件——此时才允许升级为更宽发现，且先目录级列举、后内容搜索。

## Verification
- 最终记录的 id/ts/status 三元组与用户回执及首次命中完全一致（如 executing、21:17:21 人工审批）。
- 全文来自按 ID 精确过滤的 backing 记录，而非宽搜碰到的近似或过时文本。

## Counterexamples
- 目标在源码而非审计记录中（如本集后半段定位 web_search.py 实现）：search_files 内容搜索是正确工具，本方法只适用于「结构化记录」类目标，不适用于代码实现定位。
- 首次检索 0 命中或 ID 存疑：没有「store 已持有该记录」的证据，应先核对 ID/换检索词，而不是去找 backing 文件。
- 记录源是一次性外部媒介（网页片段、粘贴文本），不存在可按名定位的 store；此时宽发现才是正解。
