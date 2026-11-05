---
title: 图注 alt 内的方括号会破坏朴素 markdown 图片正则，导致收口计数假 FAIL——计数脚本须容错，写稿宜避免 alt 内方括号
scenario: "LFL 推广班次收口核对：沿用上一班脚本的图数/图注计数正则 !\[([^\]]+)\]\(([^)]+)\)，当某条图注 alt 内含方括号（本班图267 的「95% 置信区间 [-0.010, 0.014]」）时该图片不被计入，导致 md_img_count=3、caption_nonempty=3，CLOSEOUT 假 FAIL（图注在公网实读完整，未造成任何发布缺陷）。"
root_cause: "收口脚本沿用上一班的朴素正则 !\[([^\]]+)\]\(([^)]+)\)，其中 [^\]]+ 遇到 alt 内首个 ] 即终止匹配；未对「发布链路已正确、仅计数脚本漏计」这一区分做处理，于是把脚本缺陷误报成发布缺陷。"
solution: "计数正则改为容错匹配并以图片扩展名锚定（!\[(.*?)\]\(([^)]+\.(?:png|jpg|jpeg))\)，同时把「发布链路正确、仅计数脚本漏计」与「发布内容缺陷」分开判断——先实读公网图注全文再决定是否走编辑页补丁；写稿侧另加纪律：图注 alt 内避免使用方括号（本期已在 STATUS 跨班遗留登记）。"
evidence: "docs/promotion/receipts/daily62-closeout.json（首次 md_img_count=3 → CLOSEOUT_VERDICT=FAIL，修正正则后 md_img_count=4/caption_nonempty=4 → PASS）；docs/promotion/20261105-lfl-daily-62.md 第 41 行图267 alt 内含「95% 置信区间 [-0.010, 0.014]」；公网实读该图注完整（https://www.toutiao.com/item/7704557630991122978/，图267 图注全文含方括号）"
tags: [收口核对, 正则, markdown, 推广班次, 假FAIL]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-05T13:52:05.678719+08:00"
updated_at: "2026-11-05T13:52:05.678719+08:00"
---