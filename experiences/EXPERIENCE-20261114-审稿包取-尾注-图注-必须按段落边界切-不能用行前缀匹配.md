---
title: 审稿包取「尾注/图注」必须按段落边界切，不能用行前缀匹配
scenario: LFL 推广 d86 晚班 R2 审稿包生成：用 l.startswith('- **') 抽取尾注，结果把正文里的 8 条 bullet（如 §二 的「- **抓取规模**：…」）混进尾注段，同时漏掉 4 条不以 '- **' 开头、而是「- 普通文字」开头的尾注——审稿包里的「尾注全文」既不完整也不干净（第一版取到 24 条含正文条目、修正后取到 12 条漏 4 条，最终按段落边界切出 16 条才与正文一致）。
root_cause: 用行内容前缀（'- **'）当作段落边界；而尾注条目的书写形式本身不统一（有的以加粗开头、有的不以），前缀正则与段落语义不是一回事。
solution: "审稿包抽取任何「非正文段」都按 Markdown 段落边界定位：先定位标题行（如 '## 尾注'），再取其后的行直到下一个标题或文末；不要用行前缀正则代替段落边界。生成后必须做计数核对：尾注条数 == 正文该段实际条数、图注条数 == 正文图片行数，两项不符就停止送审。"
evidence: docs/promotion/_d86_reviewpkg2.py（tail 取段逻辑三次修正）、docs/promotion/_d86_fixpkg2b.py 与 _d86_fixpkg2c.py（两次修正）、docs/promotion/receipts/d86-review-pkg-R2.md（最终尾注 16 条，与正文一致）、docs/promotion/20261114-lfl-daily-86.md（正文实际尾注 16 条）
tags: [推广, 审稿包, 覆盖缺口, 非正文段, d86]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T20:19:43.870797+08:00"
updated_at: "2026-11-14T20:19:43.870797+08:00"
---