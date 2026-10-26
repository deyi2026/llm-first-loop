---
title: 图文发布 preflight 必须含话题标签断言：知乎话题在发布设置区，编辑器 gate 看不见，首发漏设只能事后编辑补救
scenario: 向知乎/头条等图文平台发布推广稿，任务规范要求 ≥1 个话题标签；发布脚本/预检清单容易只覆盖标题字数、图片数、声明勾选等硬项而漏掉话题标签（知乎编辑器的话题选择在「发布设置」区，不在正文流程中，编辑器 gate 检查天然看不见它）。
root_cause: ""
solution: "把「话题标签 ≥1」写进发布脚本的 preflight gate（与标题/h2/imgs/声明并列的断言项），在点击「发布」前强制校验；若平台 UI 在发布页无法设置话题，发布后立即走 /p/{id}/edit 补设并做双证核验（meta keywords + 渲染 Topic 元素）。当前性验证：下次发布前 grep 发布脚本应含 topic/tag 断言行。"
evidence: docs/promotion/receipts/20261019-daily21-zhihu.json（topic 字段与 process_defects_and_fixes D21-E）
tags: [知乎, 话题标签, 发布gate, preflight, 图文发布, 推广]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-19T21:03:55.183918+08:00"
updated_at: "2026-10-19T21:03:55.183918+08:00"
---

2026-10-19 晚班知乎发布第 21 期：预检清单检查了标题/字数/h2/imgs/图注/AI 声明/占位残留，唯独没查话题标签——发布成功后才发现违反任务规范「发布必须带至少 1 个 #话题标签」，被迫走 /p/{id}/edit 编辑页补设（scrollIntoView 点「添加话题」→ Input.insertText「人工智能」→ 点下拉候选 → 「更新」），并做 meta keywords+渲染元素双证核验。发布后编辑已发布内容是额外的不可逆风险窗口（编辑页误触正文可能损坏已发布稿件）。当前性验证：grep -n 'topic' docs/promotion/receipts/20261019-daily21-zhihu.json 应见 topic.added_via 与双证字段；重跑发布脚本时 gate 断言应包含话题标签非空检查。