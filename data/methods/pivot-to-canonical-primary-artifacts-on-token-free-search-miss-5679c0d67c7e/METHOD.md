---
method_id: pivot-to-canonical-primary-artifacts-on-token-free-search-miss-5679c0d67c7e
name: pivot-to-canonical-primary-artifacts-on-token-free-search-miss
description: 核实/调研小众、版本化开发者特性时，若通用搜索回执只含首页级/营销/教程结果、摘要中零次出现手头精确 token（特性名、API 名、版本号），说明搜索索引未覆盖该内容：停止改写同一后端的查询，直接转官方一手产物——仓库 raw changelog/releases、文档站索引 llms.txt、本地安装产物，token 级 grep 即得权威原文；文档页 URL 不逐个猜，先取 llms.txt 索引。本集两次 bing 全命中泛化页后，changelog 一抓即得 40+ 官方 mods 条目，llms.txt 一抓解决两次 docs 404，最终用官方 d.ts 头部声明逐字回答待核实断言。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f2769b0a-b64f-4ef5-81b2-e6a1d35727de:4:e066f968256715682178
evidence_refs: learning:learn:41ec230a7e45
created_at: 2026-10-09T02:03:10.100431+08:00
updated_at: 2026-10-09T02:03:10.100431+08:00
---
## Trigger
需要核实关于某小众、版本化软件特性的具体断言（如『官方未承诺稳定性』）；通用搜索引擎 1-2 次查询均只返回首页级结果，且结果摘要中零次包含查询里的精确 token。

## Discriminator
当时已可见的机械事实：搜索回执全部是 homepage/营销/教程级 URL，摘要文本中 0 次出现精确特征 token；同时查询对象明确版本化（含版本号/release notes 语境），故必然存在官方 changelog。该信号在第 2 次换措辞搜索之前就已完整成立，足以判定『索引缺口』并停止搜索扩散。

## Short path
- 用已持有的精确 token（特性名、版本号）做一次通用搜索；回执若已呈首页级且零 token 匹配，最多再做一次定向查询即止。
- 确认索引缺口后停止改写查询，直接抓官方一手产物：官方仓库 raw 的 CHANGELOG.md/releases，token grep 得到特性条目与官方 API 名，确认特性真实性与官方表述。
- 需要正式定义/专门文档页时，先抓 <docs-root>/llms.txt 索引拿准确页面 URL，再抓对应页面；不逐个猜测路径以避免 404。
- 本地已安装该软件时并行检查本地产物（插件目录、类型定义/d.ts 文件头），稳定性/早期访问声明常以原文形式存在于此。
- 用一手原文逐字引用回答待核实断言；来源与官方域名/仓库一致即停止，不再补做确认性搜索。

## Stop conditions
- 待核实断言已被官方一手原文逐字回答（如 changelog 行、类型定义头部声明、文档定义句）。
- 已取得特性定义加官方稳定性/承诺表述，覆盖用户『深入了解』所需的事实面。

## Verification
- 每条结论映射到一条一手原文引用；引用文本包含当初查询所用的精确 token，证明取到的是同一对象的权威记录而非同名词污染。
- 最终来源 URL 为官方域名或官方仓库 raw 路径，provenance 与查询对象一致；教程/新闻等转述页不作为断言依据。

## Counterexamples
- 主题大众化（安装入门、定价、入门教程）：搜索已直接命中官方文档深链或摘要含精确 token，前置判别不成立——沿搜索结果走即可，不绕道 changelog/llms.txt。
- 对象无公开仓库或官方文档（传闻、新闻事件）：一手产物不存在，搜索与可靠二手来源是唯一路径，本方法不适用。
- docs 站不提供 llms.txt 或等价索引：此时才允许有限次路径猜测或站内搜索，不把『先取索引』绝对化。
