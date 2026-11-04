---
title: 发布回执顶层 md_sha/html_sha 若不随修订刷新，就无法证明「发布的=被准入的」——每次 paste 必须把被注入内容的 sha 写进 log 条目
scenario: 2026-11-04 自我检查：d58 头条稿 P1 修订后重贴发布，但发布回执 receipts/daily58-toutiao-local.json 顶层 md_sha=982fe437…、html_sha=7910ed37… 仍停留在修订前指纹（982fe437 正是两份内容审稿回执 verdict=REVISE 时审的版本）；而实际被注入编辑器并发布的是修订后主稿（当前 md sha=817ac904，与宿主准入回执 frozen_md_sha=817ac904 一致），磁盘上被粘贴的 receipts/daily58-paste.html 实际 sha=1d5aff87…，也与回执顶层 html_sha 不符。回执 log 里 tab_opened 之后的 pasted/verified/previewed/submitted 条目根本不携带 md_sha，所以从回执自身无法重建「粘了什么」。公网实读证明发布内容确实是修订版（P1 修订句命中、旧句不存在），CLOSEOUT PASS——即产物正确但审计链断裂。
root_cause: 回执的顶层 sha 字段在脚本里于「首次 paste」阶段赋值，之后 clear→重贴→submitted 阶段没有重新赋值，而阶段条目又不带 sha；于是回执的顶层指纹锚定的是第一版而不是最终发布版。
solution: ① 回执写入侧：每次 paste/verify 阶段条目内必须写入被注入内容的实测 sha256（含 html），submitted 条目写最终稿 sha；顶层字段随最后一次 submit 刷新，不要只在首贴赋值。② 收尾断言：发布前断言「回执 submitted 的 md_sha == 准入回执 frozen_md_sha」，不等即判 FAIL，不许只靠编辑器字符数与公网实读来兜底。③ 判定口径：正文/公网读数证明「内容对」，回执 sha 证明「产物与被审/被准入对象同一份」，两者缺一不可——用前者替代后者是审计链断裂。
evidence: 实测（2026-11-04）：python 读 receipts/daily58-toutiao-local.json → top-level md_sha=982fe4370cdf38ba、html_sha=7910ed3743560f71；同目录 receipts/daily58-paste.html 实测 sha256=1d5aff87a4f7a46b…；docs/promotion/20261104-lfl-daily-58.md 实测 sha256=817ac9040c396ced…；receipts/daily58-admission.json frozen_md_sha=817ac904…、candidate_sha256=00e60ff9…、qualification=PASS、kind=article_publish；两份内容审稿回执 reviewed_md_sha256_at_review=982fe437…、verdict=REVISE；回执 log 的 phase 序列 tab_opened→pasted→title_set→ai_declared→verified→previewed→cleared→pasted→title_set→ai_declared→verified→previewed→submitted，其中第二条 paste 起各条目无 md_sha 键。
tags: [发布回执, RULE-AI-28, 审计链, sha, 修订重贴, 自我检查]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T10:22:43.371844+08:00"
updated_at: "2026-11-04T10:22:43.371844+08:00"
---