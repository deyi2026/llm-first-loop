---
method_id: url-metadata-first-recon-before-broad-search-67fa9687e919
name: url-metadata-first-recon-before-broad-search
description: 当用户给出具体 URL 且首次抓取只返回标题/meta/壳页时，优先把该 URL 当作权威对象：用 title/meta 消歧，直接抓原始 HTML 和它引用的 JS/API，再沿 provenance 探测公开数据。只有需要外部背景或 provenance 断裂时才做宽搜索。避免用模糊站名搜索导致大量无关结果。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:852f577d-611a-4433-bd5a-e818387f9e1a:5:134b96ab3f4d5910d32d
evidence_refs: learning:learn:e5f25020b688
created_at: 2026-09-26T06:09:16.122622+00:00
updated_at: 2026-09-26T06:09:16.122622+00:00
---
## Trigger
用户给出具体 URL，询问项目是什么/能否做；首次抓取只返回标题、meta 或代理/壳页提示，正文缺失。

## Discriminator
同一 URL 的标题/描述已把对象限定为某个在线产品，且缺失正文来自 SPA/代理/提取限制；此时宽泛 web search 会因名称碰撞引入无关结果。

## Short path
- 先用已抓到的 title/meta 判断对象类别，不再用站点名做宽搜索。
- 对同一 URL 直接获取原始 HTML/静态资源，确认是否为 SPA 壳。
- 若 HTML 指向 JS bundle/manifest/API，沿这些引用抓取并提取 endpoint、配置、公开状态。
- 只读探测公开 endpoint 和外部市场/链上数据，验证产品与收益模型。
- 当已能回答可行性、收益来源和风险时停止，不继续枚举无关资料。

## Stop conditions
- 已从同一 URL 及其引用资源获得足够事实回答用户问题。
- 宽搜索仅用于补充外部背景，且结果与目标 URL 的 title/meta 一致。
- 继续抓取只会增加无关候选或重复确认。

## Verification
- 最终结论中的关键事实能追溯到同一 URL、其 JS/API 或权威外部数据。
- 没有把名称碰撞的搜索结果当作目标项目事实。
- 对 SPA/代理导致的正文缺失，用原始 HTML 或 bundle 证据替代。

## Counterexamples
- URL 本身未知或可能是钓鱼/重定向，需要先搜索信誉和归属。
- title/meta 与用户目标无关，真正问题需要外部新闻、监管或社区信息。
- 页面已完整包含目标正文，直接分析即可，无需抓 JS/API。
