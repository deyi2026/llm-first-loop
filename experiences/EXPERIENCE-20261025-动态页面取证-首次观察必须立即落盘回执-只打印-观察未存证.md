---
title: 动态页面取证：首次观察必须立即落盘回执，只打印=观察未存证
scenario: LFL 推广 d37（2026-10-25）：从头条 trending 话题页取证写蹭事件稿。首抓脚本只 print 不落盘；重抓落盘时「相关内容」已动态轮换，首抓里的行情转述段消失，回执链断裂，正文/图注/台账被迫删除该数据并重写相关段落。
root_cause: 动态页面（话题页相关内容/评论）每次加载轮换；首抓未落盘使观察成为不可再现的一次性终端输出；写稿时把未存证数据当已存证引用。
solution: "动态页（话题页/评论区/相关内容流）取证脚本必须当次落盘回执：JS 侧取 body.innerText 全文（折叠空行后存 flat 字段不截断）+ captured_at UTC 时间戳；正文只用有落盘回执支撑的数据；审稿对台账时以回执文件为唯一真值。观察时间标注以回执 captured_at/mtime 为准，不用「08:xx」模糊区间。"
evidence: "docs/promotion/receipts/20261025-d37-trend-full.json（captured_at 00:25:51Z，body_len 6054，Bloom 段缺失）；docs/promotion/20261025-lfl-daily-37.md v3（Bloom 数据全删，grep 双零）；docs/promotion/20261025-daily-37-sources.md v3（变更记录）；审稿回执 subagent_4c2ed9ad5615（P0-3「台账行6 出处不实」）与 subagent_11c8a000aee1（N1 时间标注）"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T08:42:59.500482+08:00"
updated_at: "2026-10-25T08:42:59.500482+08:00"
---

场景：从头条 trending 话题页（或任何动态轮换内容页：评论区、相关内容流）取证用于发布稿。首抓脚本只 print 不落盘；写稿用了首抓终端输出里的数据（某美股公司财报反差数字）；审稿要求对台账时重抓落盘，页面「相关内容」已轮换，首抓数据消失，回执链断裂，正文被迫删数据重写。

规则：
1. 动态页面第一次观察就必须落盘回执（页面文本+captured_at），「终端打印过」不构成审计链——打印输出不进 Evidence、不可复核、不可恢复。
2. 正文引用转述数据前，先确认其所在回执已落盘；没有落盘回执的数据一律不进正文，宁可删句。
3. 重抓动态页 ≠ 复核：内容轮换后旧观察不可再现，只能引用已落盘的那次。
4. 抓取脚本落盘字段要含完整正文（flat 全文），不要只存 head 前 N 字符——len 与 head 实长不一致即回执质量缺陷，审稿会打回。