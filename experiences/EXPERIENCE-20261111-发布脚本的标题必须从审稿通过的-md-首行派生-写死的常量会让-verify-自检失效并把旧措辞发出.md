---
title: 发布脚本的标题必须从审稿通过的 md 首行派生——写死的常量会让 verify 自检失效并把旧措辞发出去
scenario: LFL 推广班次的发布脚本（_dNN_publish.py）里，标题是写死的字符串常量，编辑器自检 verify 只做「编辑器标题 == 脚本常量」的比对。d78（2026-11-11 晚班）脚本常量是早期草稿标题「README 一句注入：AI 助手照做率是代码的 2.6 倍」，而审稿通过的稿件首行已改成「README 一句注入：照做率是代码的 2.6 倍」——两者的差异不只是措辞，写死版本还带着审稿明确否掉的「AI 助手」泛化表述。verify 依然报 GATE PASS（因为它比的是脚本常量自己），漂移完全不会被自检发现。
root_cause: ""
solution: "规则：发布脚本的标题不得写死，必须从审稿通过的稿件 md 首行派生；verify 阶段要断言「编辑器里的标题 == md 首行标题」，而不是 == 脚本里的常量。做法：脚本里写 `TITLE = MD.read_text(encoding=\"utf-8\").split(\"\n\", 1)[0].lstrip(\"# \").strip()`，并 assert 长度 ≤30；publish 前用 `python3 -c \"import ...\"` 打印 TITLE 与 md 首行对比一次。当前性验证：跑 `python3 docs/promotion/_d78_publish.py title` 回执里的 TITLE_SET 字符串必须逐字等于 `head -1 docs/promotion/20261111-lfl-daily-78.md` 去掉「# 」后的内容。"
evidence: docs/promotion/receipts/d78-publish-session.json（TITLE_SET 回执为「README 一句注入：AI 助手照做率是代码的 2.6 倍」，与 docs/promotion/20261111-lfl-daily-78.md 首行「README 一句注入：照做率是代码的 2.6 倍」不一致）；订正见 docs/promotion/_d78_publish.py（TITLE 从 md 首行派生）
tags: [LFL推广, 发布脚本, 标题漂移, 自检盲区]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-11T20:31:58.127837+08:00"
updated_at: "2026-11-11T20:31:58.127837+08:00"
---