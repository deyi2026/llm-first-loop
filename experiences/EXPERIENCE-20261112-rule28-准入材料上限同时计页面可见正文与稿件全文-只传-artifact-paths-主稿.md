---
title: "Rule28 准入材料上限同时计页面可见正文与稿件全文：只传 artifact_paths=[主稿]"
scenario: 文章发布前调用 review_admission(kind=article_publish) 被连续拒 3 次，reason_code=browser_page_review_cap_exceeded（78912/78000、78098/78000）
root_cause: 准入材料把「页面可见正文」与「稿件全文」两个来源同时计入同一 78000 字节预算，稿件越长越易触顶；传 manuscript_path + artifact_paths 时同一篇稿件被计入两次。
solution: "准入材料总字节上限 78000，同时计入宿主浏览器页面可见正文与稿件全文；manuscript_path 与 artifact_paths 同传会双重计入。改为只传 artifact_paths=[主稿 md]（不传 manuscript_path、不传图）即可放行，且内容审查不丢——图面与数值另由独立内容审稿子代理逐图核过。若仍超限，先确认页面是否已注入正文（编辑器正文 + 预览浮层会各存一份）。"
evidence: "本班 d79（2026-11-12）：第 1 次 start 报 78912>78000（带 4 图指纹 + manuscript_path）；第 2 次去掉图指纹仍 78098>78000；第 3 次只传 artifact_paths=[docs/promotion/20261112-lfl-daily-79.md] 被 accepted，宿主审查 child=subagent_ed24ef1349db PASS，candidate_sha256=08e92ca7…。回执 receipts/d79-admission.json。"
tags: [rule28, review_admission, article_publish, toutiao, 发布准入]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T12:43:39.539701+08:00"
updated_at: "2026-11-12T12:43:39.539701+08:00"
supersedes: [EXPERIENCE-20261111-rule28-文章类准入的-artifact-paths-不能放含-data-uri-内嵌图的粘贴]
---