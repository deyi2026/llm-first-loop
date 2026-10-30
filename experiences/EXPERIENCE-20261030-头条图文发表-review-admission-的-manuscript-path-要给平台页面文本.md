---
title: 头条图文发表：review_admission 的 manuscript_path 要给平台页面文本，不能给 markdown 源稿
scenario: 为今日头条图文稿走发表前独立审查闸（review_admission kind=article_publish）时，第一次用 markdown 源稿当 manuscript_path 被拒，改用平台页面文本文件后放行。
root_cause: ""
solution: "manuscript_path 传平台页面文本文件（编辑器 DOM 抽取的发布正文纯文本），markdown 与配图走 artifact_paths；浏览器先换绑编辑器 tab、预览浮层出\"确认发布\"按钮后再 start，随后 status 取 PASS 资格，最后才点击确认发布。"
evidence: "实证：2026-10-30 本稿首次 review_admission start 传 manuscript_path=docs/promotion/20261030-lfl-memt-compare.md → 拒绝 manuscript_page_text_mismatch{\"match_ratio\":0.617,\"threshold\":0.9,\"unmatched_sample\":[\"![图185｜...](img/fig185-two-memory-routes.png)\",\"| 型号 | 骨干 | ...\"]}；改为传 receipts/memt-compare-manuscript-page.txt → accepted:true，status 返回 qualification=PASS（child_id subagent_6a0d341e5a9d）。回执：docs/promotion/receipts/memt-compare-admission.json、memt-compare-manuscript-page.txt、memt-compare-issue-review-r1.json、r2.json。"
tags: [toutiao, publish, review_admission, manuscript_path, RULE-AI-28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T12:59:17.815605+08:00"
updated_at: "2026-10-30T12:59:17.815605+08:00"
---

今日头条图文稿发表前置闸（review_admission, kind=article_publish）的正确入参：manuscript_path 必须指向"平台页面文本文件"（docs/promotion/receipts/<issue>-manuscript-page.txt，由发布脚本 pageman 阶段从编辑器 .ProseMirror 抽取并落盘），而不是 markdown 源稿；markdown 源稿与配图放进 artifact_paths（绝对路径）供 sha 冻结。先把浏览器 host 换绑到编辑器 tab、点"预览并发布"让"确认发布"按钮出现，再 start，再 status 取资格。