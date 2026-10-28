---
method_id: canonical-outlink-before-search-or-slug-guess-5883a7cd9e59
name: canonical-outlink-before-search-or-slug-guess
description: 为具名项目定位官方一手来源（发布公告、权威文档、规范原文）时，若项目自身的 canonical artifact（repo 主页、raw README、官网首页）已在手或仅一跳之遥、且正文中含指向该来源的显式出站引用（如 'Read the announcement' 类链接），应先用一步确定性动作把该引用解析成精确 URL（fetch raw README 抽取 href）再直接访问；不要先猜博客 slug，也不要先跑搜索引擎。短缩写项目名在搜索引擎极易整页撞入无关领域，撞名结果是切换回一手 artifact 的信号，而不是继续改写 query 的理由。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:4:6b4e70d85fc64ff7c328
evidence_refs: learning:learn:bfa19ac53ef0
created_at: 2026-10-21T11:02:52.011775+08:00
updated_at: 2026-10-21T11:02:52.011775+08:00
---
## Trigger
需要为某个具名项目/工具找到官方一手来源，而该项目的权威页面（repo 页或 README）已经抓取在上下文中，或可以用一次确定性 fetch 获得。

## Discriminator
已抓取的 canonical 页面正文中出现了指向目标来源的显式出站引用（链接文本存在，即使 extract 未显示 href，raw README 一步即可还原）；以及搜索结果整页落入与目标完全无关的同名异义领域——后者证明搜索通道对该查询已退化。

## Short path
- 抓项目 canonical 页面（repo 主页）；未知量：目标一手来源是否被项目自身显式引用？
- 若正文含公告/文档类显式链接但抽取文本未带 href，fetch raw README（raw 源）从 markdown 还原精确 URL；未知量：链接的确切目标是什么？
- 直接 fetch 该精确 URL，核对发布方/域名与项目官方一致；未知量：这是否即所需官方来源？
- 一致即停止一切检索，转入阅读分析。

## Stop conditions
- 已从 canonical artifact 的显式出站链接取得目标来源，且发布方/域名与项目官方一致
- canonical artifact（含 raw README）确无任何指向目标来源的引用——此时才允许搜索引擎或多源检索

## Verification
- 最终 URL 的出处是项目自身 repo/README 的链接，而非搜索结果排名或人工猜测的 slug
- 抓到的页面作者/发布方可核对（官方博客且文中点名该项目），内容与引用语境吻合

## Counterexamples
- 出站链接由前端 JS 渲染、raw README 也不含该 href——出站边断裂，退回搜索/站内检索是合理路径
- 用户要的是第三方评测、历史版本对比等项目官方不会自引用的来源——不能只沿官方出站边
- 手头页面是转载镜像而非 canonical 源，其链接可能过期——应换 raw canonical README 而非沿镜像链接
- 目标本身是宽调查（多来源交叉）而非定位单一官方原文——搜索引擎仍是必要补充
