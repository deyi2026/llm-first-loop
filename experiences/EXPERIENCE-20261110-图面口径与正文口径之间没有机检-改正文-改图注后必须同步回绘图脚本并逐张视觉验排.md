---
title: 图面口径与正文口径之间没有机检：改正文/改图注后必须同步回绘图脚本并逐张视觉验排
scenario: 头条图文已发布后改正文里的数字/归属/方向表述，或改正文的图注 alt；同时要更新配图里的同一处文案。
root_cause: ""
solution: "把「图面口径 ↔ 正文口径」当作独立一层检查：(1) 改完正文或图注后，凡涉及数字/归属/方向的句子必须同步回绘图脚本重出 PNG；(2) 出图后逐张 read_image 视觉验排，不能只依赖 caption check（它只核「图注 alt ↔ 图上文案」对应与像素越界，不核图面口径）；(3) 改图后重跑 caption check + 逐张 read_image；(4) 头条编辑页改图不要用「选中旧图→粘贴新图」（会变成插入、图序错乱），改走整篇重贴：clear → paste 完整正文 → 标题 → AI 声明 → 自检；(5) 改稿后重开一轮审稿并重做宿主准入；(6) 上线判定看公网内容而非作品管理页卡片状态，公网读取有缓存滞后，需加 cache-bust 参数重抓再做内容级比对。当前性验证（仓库根执行）：python3 -I docs/promotion/_d76_caption_check.py 应得 CAPTION CHECK PASS；grep -n \"论文进一步指出\|每 token 约折\" docs/promotion/figures/_d76.py 应命中 2 处；python3 -I docs/promotion/_d76_public_img_check.py \"https://www.toutiao.com/item/7706331302030492194/?_=$(date +%s)\" 应下载 4 张 pub_fig*.png，其中 pub_fig0.png 经 read_image 可见「论文进一步指出」、pub_fig3.png 可见「每 token 约折 0.6 个字符」。"
evidence: "docs/promotion/STATUS-20261110-daily76.md 第六节 6.2/6.3；receipts/d76-caption-check.json（08:51:36 caption check PASS 但未覆盖图面口径）；receipts/d76-closeout.json（CLOSEOUT_VERDICT=PASS）；receipts/pub_fig0.png、pub_fig3.png（09:10:47 cache-bust 重抓后 read_image 复核）"
tags: [头条, 配图, 图注, 审稿, 修改发布, 内容一致性]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T09:14:08.561154+08:00"
updated_at: "2026-11-10T09:14:08.561154+08:00"
---