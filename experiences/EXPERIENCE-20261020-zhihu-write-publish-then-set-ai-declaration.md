---
title: zhihu-write-publish-then-set-ai-declaration
scenario: 知乎专栏（zhuanlan.zhihu.com）发文：/write 编辑器填标题+正文+4 图+4 图注后点「发布」，与话题/AI 创作声明的设置时机
root_cause: ""
solution: "流程（2026-10-20 第 23 期实测验证）：① 在 https://zhuanlan.zhihu.com/p/{id}/edit 载入已存草稿，编辑器 50 块（正文 6352 非空白字）与可见正文稿逐字一致；② 编辑器内「文章话题」选「人工智能」——话题随草稿保存，reload 后仍在位；③ 点「发布」→ 页面直接跳到 /p/{id} 已发表页，**无发表前设置确认层**（与头条不同）；④ AI 创作声明（包含 AI 辅助创作 作者对内容负责）**发表前无法设置**，须回到 /p/{id}/edit → 发布设置 → 「无声明」下拉选「包含 AI 辅助创作 作者对内容负责」→ 点底部「更新」保存；⑤ 公网验收：登录态 DOM 读 .Post-RichTextContainer（去掉 noscript 后可见正文、figcaption、img.naturalWidth、h2 计数、meta 行「包含 AI 辅助创作」），未登录 UA 被知乎 403（与第 22 期同型），不要按 403 判失败。⑥ 2026-10-20 实测第 22 期的「部分 <h1> 被 Draft.js 降级为普通段落」缺陷未复现，8/8 小节均为 H2。"
evidence: docs/promotion/receipts/20261020-daily23-zhihu-published.json（登录态 DOM 验收：标题/正文 6359/4 图实载 1000×940|768|767|973/4 图注/8 H2/话题 1/AI 声明 meta 行）；docs/promotion/STATUS-20261020-daily23.md 追加段 D23-K
tags: [知乎, 专栏发布, 话题, AI创作声明, 浏览器自动化]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T15:11:37.357306+08:00"
updated_at: "2026-10-20T15:11:37.357306+08:00"
---