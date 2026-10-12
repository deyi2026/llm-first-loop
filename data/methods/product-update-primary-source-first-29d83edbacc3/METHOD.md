---
method_id: product-update-primary-source-first-29d83edbacc3
name: product-update-primary-source-first
description: 产品功能更新类问题（某产品在某领域是否有更新、哪个版本引入），若用户已点名官方渠道（GitHub/官网），先直接抓官方 CHANGELOG 与官方 docs 页面，而不是先在通用搜索引擎做并行关键词枚举。通用搜索对版本化功能问题只会返回营销落地页、下载页和第三方教程。搜索降级为回退手段，仅在官方源 URL 无法推导或官方源无该功能时使用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:70:7b86b16fc946b1e37b48
evidence_refs: learning:learn:1499f14d724a
created_at: 2026-09-23T12:27:40.916015+00:00
updated_at: 2026-09-23T12:27:40.916015+00:00
---
## Trigger
用户询问某具体产品在某个功能领域是否有更新，且请求原文或上下文已指明权威一手来源（官方 GitHub 仓库、官方文档站）；或首轮通用搜索结果全部是落地页/第三方教程、不含功能级内容。

## Discriminator
两个当时已知事实：(1) 用户原话点名了 github 和官网渠道，即一手来源已被授权且官方 changelog/docs 的 URL 通常可直接从产品名推导；(2) 问题的本质是版本化事实（改了什么、何版本引入），权威答案只存在于官方版本化来源中，而非按热度排序的网页。

## Short path
- 直接抓官方仓库 raw CHANGELOG.md——未知量：该功能是否真实存在、何时引入（用户已点名 GitHub，无需发现）
- 定位官方 docs 站中该功能的专属文档页（docs 索引或 changelog 内的交叉引用）——未知量：功能语义与用法
- 对命中的 docs 页分页读至完整——未知量：能力描述是否覆盖全部要点
- 将答案中每个版本号与 changelog 条目逐一对齐——未知量：版本轨迹是否可溯源
- 功能语义与版本轨迹均来自官方来源且回答了用户问题，即停止，不再扩大搜索

## Stop conditions
- 功能存在性、语义描述、版本轨迹三项均由官方 changelog/docs 证实，足以回答用户
- 官方源明确显示无该功能条目——可据此回答'无'，或降级到搜索查 preview/beta/新闻渠道

## Verification
- 答案中每个版本相关 claim 可追溯到一条具体 changelog 条目
- 每个功能行为 claim 可追溯到官方 docs 原文，且该 docs 页已分页读完整
- 引用来源均为官方一手渠道，未混入第三方教程的未验证说法

## Counterexamples
- 用户要的是社区评价、使用体验或横向对比——官方文档无法回答，通用搜索/社区才是正路
- 产品没有公开仓库或官方文档站，URL 不可推导——必须先做发现式搜索定位来源
- 问的是尚未进入 changelog 的 breaking news 或泄露信息——官方版本化来源天然滞后，搜索可能更及时
- 问题本身是开放性调研（如'业界有哪些 workflow 方案'）而非特定产品事实——宽搜索是合理起点
