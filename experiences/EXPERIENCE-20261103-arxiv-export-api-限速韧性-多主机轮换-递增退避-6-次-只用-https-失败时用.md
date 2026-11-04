---
title: arXiv export API 限速韧性：多主机轮换 + 递增退避 ≥6 次，只用 https，失败时用已成功命中集且不用搜索引擎替代
scenario: 每日推广班次用 arXiv export API 做多查询论文调研时，单主机 + 固定短退避会被限速，导致部分查询整轮失败、当班候选面被压缩
root_cause: ""
solution: 抓取脚本用多主机轮换 + 递增退避 + ≥6 次尝试（只用 https），查询间隔 ≥6s；选题只从已成功查询的命中集里挑，失败如实记录，不用通用搜索引擎替代
evidence: receipts/d57research/arxiv_queries.json（5 条查询全部 ok，attempts=0）；docs/promotion/STATUS-20261103-daily56.md 第二节（q2/q3/q4 两次被限速拒绝）；docs/promotion/STATUS-20261103-daily57.md 第二节；脚本 docs/promotion/_d57_research.py
tags: [arxiv, 调研, 限速, 推广, 检索]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-03T20:19:41.386288+08:00"
updated_at: "2026-11-03T20:19:41.386288+08:00"
supersedes: [EXPERIENCE-20261031-arxiv-export-api-在本环境必须用-https-http-返回-0-字节]
---

【场景】每日推广班次用 arXiv export API 做论文调研（agent memory / self-evolution / tool security / agent safety 等 4–5 条查询）。

【已发生的失败】2026-11-03 午班 d56：查询脚本固定单主机 https://export.arxiv.org/api/query + 3 次重试（sleep 4s），q2/q3/q4 连续两轮被限速拒绝（HTTP 429 与 read timeout），当班论文全部退化成只用一个查询的命中集，查询面变窄且失败如实记录但结果受限。

【本班改法与实测】晚班 d57 把抓取脚本改为：3 个主机轮换（https://export.arxiv.org → https://arxiv.org/api 两路 https；http 一路按既有卡 EXPERIENCE-20261031-arxiv-export-api-在本环境必须用-https-http-返回-0-字节 不可用，已移除）+ 每查询最多 6 次尝试 + 递增退避（6 + 4×attempt 秒）+ 查询间隔 6s。实测 5 条查询全部首次成功（attempts=0），近两周命中 30/24/22/28/16 条，回执 receipts/d57research/arxiv_queries.json。

【运作规则】① arXiv export API 抓取脚本必须多主机轮换 + 递增退避 + ≥6 次尝试，且只用 https（http 在本环境返回 0 字节）；② 写稿前先跑一轮查询，若某条查询仍全失败，必须用已成功查询的命中集选题并在台账与 STATUS 里如实记录失败，绝不用通用搜索引擎替代取论文；③ 命中集要有余量（一条查询近两周 ≥15 条才够挑候选），否则宁可延后也不要用搜索结果凑论文。

【适用边界】本条只覆盖 arXiv export API 的限速韧性；论文内容是否被夸大由审稿与 Rule28 准入另管。