---
title: 配图编号在同一工作区会被并发任务抢占：开工先查占用，改号必须改生成脚本并重跑
scenario: "LFL 推广 d86 晚班（2026-11-14）：本班按 d85 的下一个连续号段用了 fig366-fig369，而同日 14:33 另一个并发任务（20261114-lfl-feature-01.md）已占用 fig366-fig369，PNG 文件名与正文图号双重冲突。随后改号脚本只改了主稿、台账、绘图脚本这三个「产物」，没改台账的生成脚本 _d86_ledger.py；重跑生成脚本后，台账里刚改好的图号被覆盖回旧值，数字台账审计判 REVISE（missing_numeric=[370,373]）。"
root_cause: 把「改号」当成一次性文本操作，忽略了产物是由脚本再生成的（改产物不改生成脚本 = 下一次重跑就被覆盖回去）；且开工时没有预置「同一工作区并发任务会占用连续资源号段」的占用检查。
solution: "三步：①开工先 ls img/ 查已用的最大 fig 号与当日其它任务占用的号段，冲突就顺延到未占用段；②批量改号后必须同时改「产物」和「生成该产物的脚本」，并重跑生成脚本；③重跑后做双重断言——grep 旧号段在产物中零命中 + 数字台账审计 missing_numeric=[]（本班据此修到 PASS）。"
evidence: "docs/promotion/_d86_renumber.py（改号产物）、docs/promotion/_d86_ledger.py（生成脚本，曾被漏改）、docs/promotion/_d86_fix_ledger2.py（修复）、docs/promotion/receipts/d86-audit.json（missing_numeric 由 [370,373] 修到 []）、docs/promotion/img/ 与 docs/promotion/20261114-lfl-feature-01.md（并发任务占用 fig366-369 的实证）"
tags: [推广, 配图编号, 并发任务, 派生脚本, d86]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T20:19:42.728510+08:00"
updated_at: "2026-11-14T20:19:42.728510+08:00"
---