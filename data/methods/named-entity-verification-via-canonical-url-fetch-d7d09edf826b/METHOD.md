---
method_id: named-entity-verification-via-canonical-url-fetch-d7d09edf826b
name: named-entity-verification-via-canonical-url-fetch
description: 核验具名项目/平台/政策的事实（依赖、版本现状、条款）时，若权威入口 URL 在动手前已可由既有知识确定（GitHub org/repo、官方 rules/docs 路径），直接构造并抓取该 URL，跳过通用关键词搜索。两个机械判别信号：(1) 目标专名在全部搜索结果的标题/URL 中零出现；(2) 换词重试返回与上一轮完全相同的结果集——说明后端把查询坍缩到了通用主导词（如把稀有专名 Terminal-Bench 当成 Windows Terminal）。对被验证码/权限挡住的权威页，最多再做一次含专名的精确检索，仍无实体命中即放弃该渠道，显式标注未核验，并让最终建议不依赖该未核验条款或给出绕行方案。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b08a5a88-4c62-47f9-84ed-c3cb191c061d:72:23cb755c576d14977433
evidence_refs: learning:learn:5b66e610e33b
created_at: 2026-10-14T20:05:59.088329+08:00
updated_at: 2026-10-14T20:05:59.088329+08:00
---
## Trigger
回答前需要核验关于某个具名实体（具体 benchmark/框架/平台政策）的事实性断言，且该实体的权威入口地址（repo、官方规则页、docs 路径）属于可从既有知识直接构造的确定性信息

## Discriminator
动手前已具备的判别事实：验证目标的 canonical URL 可直接写出（本集后续 fetch 成功使用的 repo URL 从未由任何搜索结果给出，证明其来自先验知识而非检索）；且首轮搜索结果中目标专名在标题/URL 零出现、换词重试返回逐字相同的结果集——这两点当时已足以判定关键词搜索通道对该实体失效

## Short path
- 列出待核验未知量；对每个未知量先问：权威入口 URL 是否已可由既有知识直接构造？可构造则记录该 URL
- 直接抓取 canonical URL，不发起通用关键词搜索；尤其避免把稀有专名与 install/docker/benchmark 等高频通用词混进同一查询（通用词会成为后端的主导匹配项）
- 抓取成功：从原文提取事实即停；抓取被 bot 检查/权限挡住：最多一次带专名的精确检索（site: 限定或全短语），结果仍无实体命中则判定该渠道不可达
- 不可达的未知量在答案中显式标注为未核验假设，并调整建议使其不 hinge 在该假设上（或提供不经过该条款的替代路线）
- 每个未知量落定（已核验或已标注）后立即停止取证，进入作答

## Stop conditions
- 每个未知量要么已被权威来源原文核验，要么已显式标注未核验并说明其对结论的影响
- 同一未知量的搜索重试不超过一次，且仅当换词后结果集发生变化时才允许继续搜索分支
- 一旦观察到'专名零出现 + canonical URL 已知'或'两轮查询返回相同结果集'，立即终止搜索分支转直接抓取

## Verification
- 确认所抓页面的 URL/标题与目标实体精确匹配，而非同名泛化实体（如 Windows Terminal ≠ Terminal-Bench）
- 最终回答中已核验事实与未核验假设分开陈述，未核验项附带官方获取途径或不依赖它的替代方案

## Counterexamples
- 实体无已知 canonical URL（新项目、不确定 org/名称拼写）——搜索发现是正确的第一步，直接猜 URL 反而绕远
- 待核验事实分散在论坛/issue/多人实测报告中，无单一权威页面——需要搜索与聚合，只抓一个官方 URL 会漏信息
- 权威页在登录墙/区域限制后而镜像或快照可达——先搜索找可达副本是更短路径
