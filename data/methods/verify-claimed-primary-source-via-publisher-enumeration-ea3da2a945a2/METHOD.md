---
method_id: verify-claimed-primary-source-via-publisher-enumeration-ea3da2a945a2
name: verify-claimed-primary-source-via-publisher-enumeration
description: 核实二手转述声称“某具名发布方有一篇原文”时，不要先用第三方学术/资讯索引做主题词宽搜（它们不收录该站自发布内容，主题词也过于弥散），而应一次性取该发布方的完整权威枚举（sitemap.xml 或分栏目索引），用声称中的低频判别 token（专名/具体数字/版本号）做精确匹配：token 缺失于完整枚举 + 最接近候选原文细节全不符 + 独立旁证错位 → 二手源证伪。本集摩擦：两次 Semantic Scholar 关键词变体搜索与精选落地页之后，才 grep 已拿到的 sitemap，并重复抓取同一 URL。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:6198b7b1-67ec-407c-8e94-f9f028f1f197:287:6054a31cabb60c291219
evidence_refs: learning:learn:a8b6d40be01d
created_at: 2026-10-13T21:53:04.106255+08:00
updated_at: 2026-10-13T21:53:04.106255+08:00
---
## Trigger
二手转述（新闻/摘要/引用）声称某具名发布方（厂商博客、官方工程站）存在一篇特定原文，需要核验原文是否存在、是否与声称细节匹配

## Discriminator
转述是否已点名发布方：已点名 → 该站的完整枚举（sitemap）是权威判定面，落地页只是精选子集；未点名/归属不明 → 第三方索引才是正确首跳。同时检查声称中是否含低频专名（系统代号、具体台数/金额、模型版本号）可作为对完整 slug 枚举的精确匹配键

## Short path
- 从二手声称抽取低频判别 token：专名（系统代号）、具体数字、模型版本号、日期
- 一次性取发布方完整枚举（sitemap.xml 或栏目索引，勿重复抓取），对判别 token 做 grep
- 命中或最接近的 1-2 个 slug → 逐页取原文，把声称的具体细节（数字/型号/场景）与原文逐项比对
- token 全缺失 + 最接近候选细节全不符 + 版本/时间线错位 → 判定二手源证伪，停止检索
- 可选：补一条独立旁证（如官方版本页时间线）加固证伪结论

## Stop conditions
- 完整权威枚举已测试、最接近候选原文已比对，且存在/证伪结论已有至少两条独立一致证据
- 声称的发布方归属本身不确定（可能发在 arXiv/GitHub/社交平台）→ 停止单站枚举，改用第三方索引
- 原文确已命中且细节逐项对应 → 立即转入引用，不再枚举其他候选

## Verification
- 确认枚举来源是完整 sitemap/全量索引而非精选落地页（检查返回是否为全站 URL 列表）
- 证伪需三线一致：专名缺失于完整枚举 + 最接近候选内容细节不符 + 独立旁证（版本时间线等）错位
- 命中时确认原文 URL 域名与声称归属方一致，且关键细节逐项对应而非仅标题相似

## Counterexamples
- 转述未点名发布方或归属不明（可能是 arXiv 论文、GitHub README、推文）→ 第三方学术索引/站内搜索才是正确首跳，单站 sitemap 枚举过早
- 转述中的专名是记者自造绰号或翻译产物，可能不出现在原题 → token 缺失不能单独定案，必须配合最接近候选的内容比对
- 发布方无公开 sitemap 或内容分散在多子域/多产品域 → 完整枚举不可得，需退化为栏目页+站内搜索+第三方索引的组合
