---
title: arXiv export API 在本环境必须用 https（http 返回 0 字节）
scenario: 每日推广班次 arXiv 论文调研（export API 四查询：agent memory / self-evolving / tool security / agent safety，近 14 天窗口）
root_cause: ""
solution: "调研脚本统一使用 https://export.arxiv.org/api/query（不用 http://）；max_results=25、sortBy=submittedDate 降序；查询间隔 ≥3.5s；每查询带 3 次重试+落盘回执。"
evidence: "d45 回执 docs/promotion/receipts/d45research/arxiv_queries.json（ran_at 2026-10-31T08:06:01–08:06:14，四查询 ok=true，n_recent 25/21/13/18）；d44 回执 receipts/d44research/arxiv_q1-q4.xml（https 全成功）"
tags: [arxiv, 调研, https, 每日推广]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T08:38:35.846990+08:00"
updated_at: "2026-10-31T08:38:35.846990+08:00"
---

现象：本环境访问 arXiv export API（export.arxiv.org/api/query），http:// 返回 0 字节（d43 首跑实测），https:// 正常返回（d44 发现、d45 复用，连续两次验证）。写稿前调研脚本（_d45b_research.py 等）直接用 https://export.arxiv.org/api/query 即可，4 查询带 3.5s 间隔无 429。适用边界：仅本环境代理网络拓扑下观察；若换网络环境需重验。