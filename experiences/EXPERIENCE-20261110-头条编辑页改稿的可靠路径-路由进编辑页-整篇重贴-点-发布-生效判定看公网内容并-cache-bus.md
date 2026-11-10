---
title: 头条编辑页改稿的可靠路径：路由进编辑页→整篇重贴→点「发布」；生效判定看公网内容并 cache-bust 重抓
scenario: 头条图文发布后需要改稿（文字级或图面级），走作品管理页「修改」→ 编辑页 → 发布修改的链路。
root_cause: ""
solution: "(1) 作品管理页的「修改」是 React 事件，坐标点击无效 → 直接用路由 https://mp.toutiao.com/profile_v4/graphic/publish?from=edit&pgc_id={PGC_ID} 打开编辑页；(2) 编辑页里不要用「选中旧图→粘贴新图」替换图片（实测变成插入：img 节点 8→10、图序错乱），改走整篇重贴：清空编辑器 → ClipboardEvent('paste') 注入含 data-URI 新图的完整 HTML → 原生 setter 设标题 → 勾 AI 声明 → 自检 chars/imgs/captions/tag/empty_h1；(3) 编辑页的主按钮文案是「发布」，发布页浮层里才是「确认发布」，宿主准入 target_name 要按所在页取值；(4) 提交修改后作品管理页卡片仍显示「已发布」（旧版状态）、「审核中」页签为空，不能用它判断修改是否生效；(5) 判据是公网内容本身，且公网图有缓存滞后——同一 URL 09:08 读到旧版、09:10:47 加 cache-bust 参数重抓已是新版，故必须 cache-bust 重抓并做内容级（read_image）比对，不能只看尺寸。当前性验证（仓库根执行）：python3 -I docs/promotion/_d76_public_img_check.py \"https://www.toutiao.com/item/7706331302030492194/?_=$(date +%s)\" 应得 4 张 pub_fig*.png 且尺寸为 1000×1454/1251/1058/1407；read_image pub_fig0.png 应可见「论文进一步指出」。"
evidence: "docs/promotion/STATUS-20261110-daily76.md 第六节 6.2/6.3 与第九节第 2/3 条；receipts/20261110-daily76-public-verified.json（09:12:21，39 关键句全命中、4 图尺寸全等）；receipts/d76-poll2.log（09:06:58 卡片仍显示已发布）；receipts/pub_fig0.png（09:08 抓取为旧版「本文作者说」，09:10:47 cache-bust 后为新版）"
tags: [头条, 修改发布, CDP, 缓存, 验收]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T09:14:10.029114+08:00"
updated_at: "2026-11-10T09:14:10.029114+08:00"
supersedes: [EXPERIENCE-20261106-头条已发布文案的文字级修订-作品管理页-修改-from-edit-编辑页-range-真选区-inp, EXPERIENCE-20261110-图面口径与正文口径之间没有机检-改正文-改图注后必须同步回绘图脚本并逐张视觉验排, EXPERIENCE-20261103-头条创作者预览页对本账号是-完善账号信息-门槛页-公网验收要走-article-路由]
---