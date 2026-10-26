---
title: article_publish 闸门：target_name=页面真实发布目标，先注入后开闸
scenario: 定时推广任务发布头条图文第 26 期，走 RULE-AI-28 article_publish 闸门
root_cause: ""
solution: 先注入+开确认层+显式 target_id 换绑，target_name 填页面上真实发布目标控件文本（如「确认发布」），再启动闸门
evidence: docs/promotion/receipts/20261021-daily26-toutiao-submitted.json（含 gate 段与提交回执）；STATUS-20261021-daily26.md D26-C；失败回执见本会话 review_admission 两次 publication_target_name_required + 一次 MultiPageAmbiguityError
tags: [review_admission, article_publish, RULE-AI-28, 头条发布, 闸门]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T13:41:59.589976+08:00"
updated_at: "2026-10-21T13:41:59.589976+08:00"
---

RULE-AI-28 的 review_admission kind=article_publish 语义：target_name 必须是"页面上真实的发布目标控件文本"（如头条确认层的「确认发布」），而不是平台名或自由描述；且闸门要审"页面可见正文 vs 稿件"，所以调用顺序必须是：①完成正文/标题/声明注入 ②点开发布确认层（使目标控件存在于页面）③浏览器多 tab 时先 browser_perceive 显式 target_id 换绑到发布页 ④再 review_admission start。否则分别得到 publication_target_name_required（两次，target_name 填「toutiao/今日头条…」均被拒）与 MultiPageAmbiguityError（observed=5 pages）。本集第 26 期头条发布：按此顺序第三次启动即 accepted，reviewer PASS 后单击确认层 span（非 button 元素，DOM TreeWalker 按文本定位）单次提交成功。

## 核验记录
- 2026-10-22：receipts/20261021-daily26-toutiao-submitted.json 存在且含 gate 段（kind/target/qualification/candidate_sha256/child_id/pre_gate_independent_review 六键）；STATUS-20261021-daily26.md 命中 D26-C → 成立
