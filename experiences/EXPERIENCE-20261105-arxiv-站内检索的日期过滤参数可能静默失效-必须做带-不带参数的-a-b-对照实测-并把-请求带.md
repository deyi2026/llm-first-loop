---
title: arXiv 站内检索的日期过滤参数可能静默失效：必须做带/不带参数的 A/B 对照实测，并把「请求带了参数」与「过滤生效」分开记账
scenario: LFL 推广班次的 arXiv 论文调研（本班 2026-11-05 午班 d62）：export.arxiv.org/api/query 接口全程返回 429（响应正文 Rate exceeded，个别重试连接超时），改走 arXiv 站内检索页 /search/ 取词条；请求里带了提交日期区间参数 date-filter_by=date_range & date-from_date=2026-10-22 & date-to_date=2026-11-05 & date-date_type=submitted_date，但结果集里仍含 10-16/10-18/10-19 提交的论文。
root_cause: arXiv 站内检索的 date-filter_by=date_range + date-date_type=submitted_date 参数在本班请求形态（searchtype=all + quoted boolean + order=-announced_date_first + size=50）下被服务端忽略，返回的是未按日期过滤的命中集；缺口在于把「请求里带了参数」当成了「过滤生效」，未做带/不带参数的对照实测。
solution: 做带/不带参数的同查询 A/B 对照：两次返回的条目总数（303）与首屏条目 ID 完全一致 → 判定日期过滤未生效，据此把正文口径从「按提交日期区间过滤，返回 29/303/241/120/24/87/359 条」改写为「7 组未按日期过滤的命中总数」，并如实登记 5 篇论文就在这些命中里、其中 4 篇早于区间起点、选题范围按关键词而非日期划定；API 限流时的合规降级路径＝arXiv 站内检索页 + 按 ID 直取 abs 页面（仍属 arXiv，未用通用搜索引擎取论文），限流与重试落 receipts/*_fetch.log，对照实测落两份 HTML 回执。
evidence: docs/promotion/receipts/d62research/_dfltest_withdate.html 与 _dfltest_nodate.html（带/不带 date-from_date=2026-10-22&date-to_date=2026-11-05 返回条数均为 303、首屏条目完全一致）；docs/promotion/receipts/d62research/arxiv_fetch.log（API 全程 429 Rate exceeded）；docs/promotion/receipts/d62research/axweb_hits.json（7 组命中数 29/303/241/120/24/87/359）；docs/promotion/20261105-lfl-daily-62.md 参考来源第 6 条（已按实测口径改写）；docs/promotion/STATUS-20261105-daily62.md
tags: [arxiv, 检索, 口径失实, 推广班次, A/B对照实测, R5]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-05T13:52:05.376183+08:00"
updated_at: "2026-11-05T13:52:05.376183+08:00"
---