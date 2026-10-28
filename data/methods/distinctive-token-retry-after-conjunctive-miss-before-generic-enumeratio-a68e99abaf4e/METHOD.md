---
method_id: distinctive-token-retry-after-conjunctive-miss-before-generic-enumeratio-a68e99abaf4e
name: distinctive-token-retry-after-conjunctive-miss-before-generic-enumeration
description: 文档/语义索引对多词合取查询未命中时，把 miss 当作查询过约束的证据而非主题缺席：从第一步查询里已含的最稀有 token（项目专名/缩写）做一次文件名检索锚定工件目录，再读 README 沿交叉引用定点展开；不要用通用词做宽文件名枚举——含 vendored 依赖的 repo 会全部命中 site-packages 噪声，也不要对同一检索工具连续换通用词重试。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:3722:c9ac44a95cde3c319fed
evidence_refs: learning:learn:b13b8ed6ef2b
created_at: 2026-10-19T17:21:06.739981+08:00
updated_at: 2026-10-19T17:21:06.739981+08:00
---
## Trigger
在仓库内定位任务权威工件（需求文档/评测套件）的起点：文档或语义索引对多词合取查询返回未命中，回执明确点名失败的查询串，且尚未拿到任何具体工件路径。

## Discriminator
两条当时已知事实：(1) miss 回执里失败的是一个多词 AND 查询——合取未命中推不出其中稀有词未出现，且该稀有 token（如项目缩写）就在第一步自己的查询串里；(2) 改用通用词（version/需求/评测一类）做文件名检索，在含 .venv/site-packages 的 repo 必然被依赖文件淹没（本例 40/40 命中全为 site-packages）。

## Short path
- 视 miss 为查询过约束：从任务语汇/原查询中提取最稀有 token，做一次文件名检索（本例 rsi 一次即锚定 evals/methodcard_rsi_v1 整个套件目录）；未知量：权威工件在哪个目录。
- ls 该目录并读 README/入口文档；未知量：工件地图与互相引用的子文档清单。
- 沿 README 交叉引用与同日期 sibling 文档定点读取（需求分析、触发匹配表、pilot 报告）；对搜索结果显示缺少目录前缀的条目，先用一次目录枚举确认前缀再拼路径。
- 对报告中每条会改结论的声明落到原始 byproduct 核对（未评分记录重新评分、MDE 算术、判分器语义）。
- 每个『必要改动』都映射到一条已被证据违反的事实后，停止发现，进入写作。

## Stop conditions
- 一次稀有 token 检索已锚定权威目录且其 README 覆盖任务主题；
- 所有被引用子文档已按交叉引用读完，无新引用产生；
- 待核对声明全部有 file/数据落点。

## Verification
- 每次检索回执核对命中来源：是否全部来自依赖目录（site-packages/.venv）→ 是则换稀有 token；
- 最终所读文档标题/首段确实包含任务稀有 token；
- 未对同一检索工具用通用词做第二次以上换参重试。

## Counterexamples
- 单词查询本身就 miss（非合取）→ 不是过约束问题，应换工具类（目录树/问用户）而非换词重试；
- 任务语汇全是通用词、无专名缩写 → 无稀有 token 可用，改目录结构导航；
- 无 vendored 依赖的小 repo → 通用词文件名检索成本低、不会淹没，可直接用；
- 索引回执明确声明只覆盖某子集（如仅 docs 标题）而目标在代码/数据里 → 对该索引重试单词无意义，直接走文件名/内容检索。
