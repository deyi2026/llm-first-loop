---
title: 审稿意见给的「推断 vs 原文」判断必须自己回源核对；review_admission 需先清掉浏览器多余 page
scenario: 20261103 午班 d56 推广稿：独立审稿子代理判定 REVISE 9 项，其中一条称正文「事件图保留了全部公开事件」是本文推断、应改写；而发布前的 Rule28 准入（review_admission kind=article_publish）在浏览器有 3 个 page（发布页 + 两个 d55 旧文章页）时直接报 MultiPageAmbiguityError 并拒绝启动。
root_cause: ""
solution: "处置审阅意见前逐条回抓取件/源码核对：实查 arxiv_html_2610.34767v1.txt:1004 原文就是「Event Graph stays close to Raw Events despite containing all public events」，故保留正文原句并补台账出处行，而不是照抄审阅意见改错（改正文会引入事实错误）；台账里另两处确实指错的行号（:134→:130）才改。review_admission 报 MultiPageAmbiguityError 时，用 CDP /json/close/<targetId> 关掉与本次发布无关的旧标签页，只留发布页后重试即通过。"
evidence: "docs/promotion/STATUS-20261103-daily56.md 第六节与台账说明第 5 条；receipts/d56research/arxiv_html_2610.34767v1.txt:1004；review_admission 回执 MultiPageAmbiguityError（observed=3）→ 关页后 accepted=true"
tags: [推广班次, 审阅处置, Rule28, review_admission, CDP]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-03T13:43:05.852914+08:00"
updated_at: "2026-11-03T13:43:05.852914+08:00"
supersedes: [EXPERIENCE-20261102-review-admission-送审前必须先点预览让宿主观察到-确认发布-按钮-且-target]
---