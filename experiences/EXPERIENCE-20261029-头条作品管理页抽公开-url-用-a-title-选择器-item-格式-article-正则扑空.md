---
title: 头条作品管理页抽公开 URL 用 a.title 选择器（/item/ 格式，article 正则扑空）
scenario: LFL 每日推广晚班收口：需从头条作品管理页列表抽取当日已发文章的公开 URL 做公网实见验收（标题/大图/图注核对），列表行链接非标准 article 格式导致常规正则扫描扑空。
root_cause: ""
solution: "用 document.querySelectorAll('a.title') 直接取标题链接元素（href 为 /item/{id}/?enter_from=... 格式），不要用 article/\d+ 正则扫 href；抽到后即可新 tab 打开该 URL 做滚动验收，页面会自动跳 /article/{id}/。"
evidence: "docs/promotion/receipts/d42research/d41_url2.json（10 条列表全命中实跑回执，2026-10-29 20:04 CST）；上一班扑空对照 docs/promotion/receipts/d41research/d40_url.json（{\"links\":[],\"all\":[]}）"
tags: [头条, 公网验收, CDP, 作品管理页, 链接抽取]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-29T20:15:29.211038+08:00"
updated_at: "2026-10-29T20:15:29.211038+08:00"
---

场景：头条 mp.toutiao.com 作品管理页（profile_v4/graphic/articles）需要从列表行抽某篇已发布文章的公开页 URL 做公网验收。已知坑：列表行链接的 href 是 /item/{id}/?enter_from=mp_group_management 格式，用正则 toutiao\.com/article/\d+ 扫全部 <a> 会一无所获（上一班 d40_url.json 实测为空后被迫绕路）。正确做法：Runtime.evaluate 里 document.querySelectorAll('a.title') 直取标题链接元素，href 字段即公开页 URL（www.toutiao.com/item/{id}/），innerText 即标题可同时校验匹配。公开页打开后会 301 到 /article/{id}/ 格式，两种都算同一文章。