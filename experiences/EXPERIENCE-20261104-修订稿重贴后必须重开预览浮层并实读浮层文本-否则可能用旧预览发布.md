---
title: 修订稿重贴后必须重开预览浮层并实读浮层文本，否则可能用旧预览发布
scenario: 头条图文发布：稿件因审稿 P1 修订后，在编辑器里 clear + 重新 paste，但此前打开的「预览并发布」浮层还开着，直接点「确认发布」有可能是拿旧预览提交
root_cause: ""
solution: 顺序必须是：① 编辑器 clear（chars=0）→ 重新 paste → 重新设标题 → 重新确认 AI 声明 → VERIFY GATE PASS；② 点「返回编辑」关闭旧浮层，再重新点「预览并发布」；③ 实读预览浮层可见文本，确认它包含本轮修订后的关键句且不含旧句；④ 只有第③步通过才允许点「确认发布」。
evidence: docs/promotion/receipts/daily58-manuscript-page.txt（重贴后重新抽取的页面可见正文）、docs/promotion/receipts/daily58-toutiao-local.json（VERIFY GATE PASS 记录）、docs/promotion/receipts/20261104-daily58-public-body.json（公网正文 has_fix=true、has_old=false）
tags: [头条发布, 预览浮层, 修订稿, 发布流程]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T09:20:55.736526+08:00"
updated_at: "2026-11-04T09:20:55.736526+08:00"
---

修订稿重贴后必须重开预览浮层并实读浮层文本。当前性验证：重贴后点「预览并发布」，再实读浮层 innerText，应同时包含修订句「与工具实现版本或哈希校验相关的命中 0 处」与「模型上下文里看不出变化」，且不含旧句「全仓库检索」；否则不得点「确认发布」。