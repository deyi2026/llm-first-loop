---
title: review_admission 文章闸：送审稿须按页面渲染态生成（删粗体内容+120字符折行）
scenario: "用 review_admission(kind=article_publish) 审查\"掘金/知乎专栏类 Markdown 编辑器\"里已填好的稿件时，闸门报 manuscript_page_text_mismatch，逐轮试稿分数 0.72→0.74→0.82→0.85→0.88 始终过不了 0.9 阈值"
root_cause: ""
solution: "送审稿不能是 Markdown 源，也不能是简单剥离标记的版本。实测 Host 侧读取的是\"渲染后可见文本\"，其规则是：(1) `**...**` 包裹的内容被整段删除（不是保留文字、只删标记），(2) `## ` 标题标记消失只留标题文字，(3) 表格行 `| a | b |` 保留竖线形态（未转成单元格文本），(4) 图片行呈现为 alt 文本（不含 `![]()` 与 URL），(5) 长段落按 120 字符软换行切分。按这五条规则生成送审稿后页面比对通过，闸门签发 PASS。配套：target_name 必须是页面上真实可见的发布按钮标签（如「发布」），且需要先把浏览器 Host 换绑到该编辑器页（target_id 来自 browser_perceive 页面清单），否则 target_name 恒报 publication_target_name_required。"
evidence: "evidence://v1/16e9ba1d97c433a34f42e3eb9369df03f1e62f4ce3401408ae75aa15220802c6（受理回执）；evidence://v1/72f7e0aa33b539d0934d2f16935a663c927b708e9c0e14308a319a851581bb51（PASS，稿件 SHA acc3c314…）；evidence://v1/c1ce275c682de8a5e54fa6a1ee551e4e2b1b8e1a7c74d5cc3a3f2c1a6c0a9a1（逐轮 match_ratio 0.72/0.74/0.82/0.85/0.88 的 mismatch 回执）"
tags: [rule-ai-28, review_admission, article_publish, 掘金, 送审稿形态, 页面比对]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T18:00:24.498574+08:00"
updated_at: "2026-10-20T18:00:24.498574+08:00"
supersedes: [EXPERIENCE-20261020-review-admission-文章发表闸门用法-先换绑-按钮标签作-target-preview]
---