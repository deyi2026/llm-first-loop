---
title: 头条 syl-editor 插图新链路：工具栏上传/file paste/drop 三路均清空正文，data-URI 随正文一次 paste 自动转存图床
scenario: 在 mp.toutiao.com 图文发布页（syl-editor/ProseMirror）为长文（1500-5000 字）插入多张本地图片并发布，自动化通道 CDP websocket 直连 9229。
root_cause: ""
solution: "改用 data-URI 内嵌一次性 paste：markdown→HTML 转换时把每张图以 <img src=\"data:image/png;base64,...\"> 放到锚点位置，与正文一起 ClipboardEvent('paste',{clipboardData}) 派发，编辑器自动转存图床；发布按钮为「预览并发布」→弹窗「确认发布」；验收走作者主页文章列表。"
evidence: "/job-48b51e0b992c474ab35e（v5 FINAL: uniqueImgs=8, words=1507, blocks=50）；/job-4f680f2d8f7148d8ae6d（公网 VERIFY: article/7696304713734341174, imgsInArticle=8, hasAIDecl=true）；截图 outputs/lfl-article/toutiao-v5-final.png、toutiao-live-verify.png；反例日志 /job-00473e3ab22c410abf3d（NO_BTN 前 file paste words=0）、/job-c7e1cafd66de4de2b1b7（imgs=2 words=0 blocks=3）"
tags: [头条, syl-editor, prosemirror, data-uri-paste, 插图, 发布, verified]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T08:03:40.654322+08:00"
updated_at: "2026-10-14T08:03:40.654322+08:00"
---

背景：RULE-AI-28 文章闸后发布头条图文（8 图长文）时，2026-10-13 的工具栏图片按钮链路（setFileInputFiles→确定）三次复现全部清空正文。

实证结论（2026-10-14 实跑验证）：
1. 正文 text/html 合成 paste 安全且可重复，刷新页面后仍稳定；合成 paste 是该编辑器唯一可靠的内容通道。
2. 三条图片插入路全部验证会清空正文：①工具栏图片按钮+DOM.setFileInputFiles+点"确定"；②ClipboardEvent paste 携带 File（imgs 增加但 words→0）；③DragEvent drop 派发 file。根因表象：插入后面板转为"编辑/搜图"详情模式，主编辑器 .ProseMirror 从 DOM 消失、页面字数统计归零。
3. 可行链路（一次成型）：markdown→HTML 转换时把图片直接以 <img src="data:image/png;base64,..."> 嵌在锚点位置，与正文一次性 text/html paste；syl-editor 自动把 data-URI 转存为头条图床 URL（轮询 unique src 全部变为 toutiao 图床域、无 data: 残留即完成）。8 图、约 2MB HTML paste 无压力。
4. 发布按钮文本是「预览并发布」（不是"发布"），element.click() 即可触发；随后弹窗出现「确认发布」按钮，element.click() 后跳转 profile_v4/graphic/articles 即成功。Input.dispatchMouseEvent 真实坐标点击反而无效。
5. 公网验收：管理页 React 卡片无 <a href>、fiber 遍历无 id、点击标题不开新页；可行路径是作者主页 https://www.toutiao.com/c/user/token/<token>/?tab=article 的文章列表拿新文章链接，登录态 DOM 实见验收（imgs、标题、AI 声明、发布时间）。
6. 每步校验口令：words（页面"共 N 字"）+ unique imgs + blocks 数；words 掉到 0 立即中止，勿继续操作。

边界：适用于 2026-10-14 当日头条 mp 后台前端版本；前端改版后需重新验证第 3 条是否仍被接受。