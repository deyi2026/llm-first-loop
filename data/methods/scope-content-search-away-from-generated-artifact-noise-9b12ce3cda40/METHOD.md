---
method_id: scope-content-search-away-from-generated-artifact-noise-9b12ce3cda40
name: scope-content-search-away-from-generated-artifact-noise
description: 仓库内存在机器生成的二进制产物（浏览器 profile、Cache_Data/ScriptCache、构建输出）时，全仓内容搜索会返回看似相关（含 HTTP 头、关键词）实为乱码的命中。一旦某次搜索的命中路径/字节已把这类生成产物识别为一个噪声类，后续搜索应限定 authored 源（src/docs/scripts/experiences）或直接读已定位的权威文件，而不是重跑同类宽查询。搜索类、命中路径形态相同且未被结论引用的重复搜索是零信息成本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4dca8b27-b04e-4081-8690-f0d58c85ec34:49:a2c01af44ba64e34431e
evidence_refs: learning:learn:2ea0ef83ebf5
created_at: 2026-10-05T21:09:39.745801+08:00
updated_at: 2026-10-05T21:09:39.745801+08:00
---
## Trigger
任务要核对 authored 代码/文档的现状（行为、配置、安全头等），而全仓内容搜索的命中被生成产物路径（如 chrome-profile/Default/{Cache_Data,Service Worker/ScriptCache}）中的二进制乱码占据；且此前一次同概念搜索已证明 scoped 到源码目录能得到唯一干净命中。

## Discriminator
命中路径属于生成产物目录且正文为乱码/嵌入协议头（HTTP 头、protobuffer 字节）= 噪声类，不是 authored 证据。本集第 5 次搜索已暴露该噪声类（evals/*/chrome-profile 二进制命中），第 6 次同概念搜索在 src/ 得到唯一干净命中（auth_routes.py:110）——这两个事实当时已足以判定：再跑同类宽查询只会重复噪声。第 7 次搜索果然返回同噪声类且未被最终答案引用。

## Short path
- 把待核对维度先分类：authored 行为/配置（查 src/docs/scripts/experiences）vs 生成产物内部内容（才进入 chrome-profile/cache/build 目录）。
- authored 维度用 scoped 搜索或直接读已定位文件；本集第 6 次搜索证明 scoped 到 src/ 一击命中目标。
- 一旦搜索结果被生成产物噪声占据，不重跑同类宽查询（第 7 次重复了第 5 次噪声且零贡献）；改为收紧 scope 或读已定位文件。
- 每条现状结论挂上 authored provenance 后即停止搜索，进入综合输出。

## Stop conditions
- 每个要写进结论的维度都有指向 authored 文件/记录的引用
- 剩余未知量只存在于生成产物内部，且任务不要求它们
- 继续搜索只能再命中同一噪声类路径

## Verification
- 最终答案中每条"我们的现状"都有 authored 路径/行号引用（如 docs/*.md、src/*.py:110、experiences/*.md）
- 引用集合中不包含 Cache_Data/ScriptCache/chrome-profile 类路径，除非任务目标就是 artifact 内容本身
- 无"搜索参数与上一次几乎相同、命中路径形态相同、结论未引用"的调用

## Counterexamples
- 任务目标就是生成产物内容本身（分析 eval 运行时浏览器缓存了什么、审计 recorded payload、replay 录制）——此时这些命中是权威目标而非噪声，scoped-away 反而错误。
- 仓库无已知生成产物污染且完全不知道目标在哪——先宽搜索是正确的发现策略，过早限定 src/ 会漏掉 docs/scripts/experiences 里的答案。
- 宽搜索的非噪声命中已足够回答问题（如本集第 6 次的单条 src/ 命中）——直接使用即可，不需要先 scope 再重搜一遍。
