---
title: 头条公开页验收数图前必须先滚动触发懒加载，否则只见缩略图易误判图文缺失
scenario: 图文平台公网验收：发布后登录态浏览器读取公开页，核对正文图片数与图注数是否与发布 VERIFY GATE 一致。今日头条公开页大图与 figcaption 为懒加载，页面 ready 后立即统计只见缩略图（3 张 300×300），极易误判「正文大图缺失/图注丢失」为发布事故并触发不必要的补丁流程。2026-10-23 晚班验收 d32（item/7699733549465551411）实发：不滚动只数到 3 张 300×300，滚动到底后 4 张 1000 宽大图（820/812/700/780）与 4 条图 137-140 图注全部出现。
root_cause: ""
solution: "公开页数图/图注前先逐屏滚动触发懒加载（window.scrollTo(0, k*900) 循环 6-8 次、每次 sleep ≥1s），再统计 img 的 naturalWidth>200 过滤结果与 figcaption/「图NNN｜」文本节点；若仍少于预期，先在同一浏览器对另一篇已验收稿做同法对照（排除页面结构差异），再判定是否真缺失。标签类节点另注意：头条公开页不渲染 #话题# 为独立可检索节点（三稿一致），话题标签以发布时编辑器 VERIFY GATE 实测为准，不据公开页缺失反推标签丢失。"
evidence: "docs/promotion/receipts/20261023-daily32-public-verified.json（big_imgs 4 张 1000 宽实见记录）；/tmp/_d33_pub32.py 输出 IMGS: [[300,300]×3]（未滚动）vs /tmp/_d33_pub32c.py 输出 IMGS_BIG: [[300,300],[1000,820],[1000,812],[1000,700],[1000,780],...]（滚动后），观测时间 2026-10-23 20:05-20:08"
tags: [promotion, toutiao, public-verify, lazyload, acceptance]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T20:19:27.944094+08:00"
updated_at: "2026-10-23T20:19:27.944094+08:00"
supersedes: [EXPERIENCE-20261020-头条图文首发-知乎-掘金已发文章定点修订同步-2026-10-20-三平台同一篇]
---

今日头条公开页（/item/{id}/ 重定向 /article/{id}/）正文大图与 figcaption 图注走懒加载：页面加载完成后立即 querySelectorAll('img') 过滤 naturalWidth>200 只见 3 张 300×300 缩略图（封面/头像类），4 张正文大图（1000×820 等）与「图NNN｜」图注需 window.scrollTo 逐屏滚动 6-8 次（每次间隔约 1s）后才进入 DOM/naturalWidth 生效。验收脚本：/tmp/_d33_pub32.py（未滚动，误判 3 图）与 /tmp/_d33_pub32c.py（滚动后实见 4 大图+4 图注）输出对比；对照脚本 /tmp/_d33_pub31tag.py 对 d31/governed 两稿同法复核。d32 验收回执 docs/promotion/receipts/20261023-daily32-public-verified.json。