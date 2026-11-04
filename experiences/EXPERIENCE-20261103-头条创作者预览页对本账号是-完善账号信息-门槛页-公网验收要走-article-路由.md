---
title: 头条创作者预览页对本账号是「完善账号信息」门槛页，公网验收要走 /article/ 路由
scenario: 需要做头条文章的公网实见验收（标题逐字、图注、图片尺寸、AI 声明、标签）
root_cause: "创作者预览路由对本账号返回账号信息门槛页（不是文章内容），公网文章路由 /article/{id} 在审核通过后才渲染正文"
solution: "用已登录的 Chrome 经 CDP 打开 https://www.toutiao.com/article/{pgc_id}/ ，分段滚动触发图片懒加载后读取 img.syl-page-img 的 naturalWidth/naturalHeight 与本地 PNG 尺寸逐图比对；创作者预览页 profile_v4/graphic/preview 对本账号返回账号信息门槛页，不能当作验收依据。当前性验证：复现跑 `python3 docs/promotion/_d55_public_verify.py https://www.toutiao.com/article/7703755695833219611/` 应输出 title_match=true、dims_all_match=true、fig_captions_all_hit=true"
evidence: docs/promotion/receipts/20261103-daily55-public-verified.json（title_match=true、dims_all_match=true、fig_captions_all_hit=true）与 docs/promotion/receipts/daily55-closeout.json；创作者预览页抓取返回「请完善账号信息，解锁发布文章、视频等权益功能」
tags: [toutiao, public-verify, cdp, publish]
source:
  note: d55 早班实测
  work_unit_id: daily55-publish
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T09:57:07.041838+08:00"
updated_at: "2026-11-03T09:57:07.041838+08:00"
---