---
title: 「文件多少行」只能用 wc -l 一个口径：Python split 会多算 1 行，改一处要同步正文+台账+回执并重跑构建与抽检
scenario: "LFL 推广 d92 晚班（2026-11-16）：正文写「规则文件 docs/ai_rules.md 共 716 行」，台账同步写 716，回执 receipts/d92research/lfl_readings.json 记 ai_rules_lines=716——数字来自 Python 的 len(text.split(\"\n\"))。台账抽检脚本用 wc -l 实开同一文件得 715（文件以换行结尾，split 会多出一个空元素），判 FAIL「实开=715 台账=716」。一处口径错，导致正文 2 处、台账 1 处、回执 1 处要改，稿子 sha256 变化、HTML 需重建、审稿包需重新生成。"
root_cause: ""
solution: 凡对外表述「某文件多少行」，只认一个口径：wc -l（去尾换行计数）。写稿时直接取 wc -l 的输出填进正文/台账/回执，不要用 Python 的 split 计数；抽检脚本与写稿脚本必须调用同一条命令。已用 split 计数写进三处的，改完要重跑构建 → 审计 → 抽检三道机检（改了正文就要重跑 HTML 构建，sha256 变了审稿包也要重新生成）。当前性验证：改完后跑 `wc -l docs/ai_rules.md` 应得 715，且 `grep -c '715 行' docs/promotion/20261116-lfl-daily-92.md` 应为 2、`grep -c '716 行'` 应为 0；再跑 `python3 _d92_spotcheck.py` 应得 fails 0。
evidence: d92 台账抽检 receipts/d92-spotcheck.json 判 FAIL（实开=715 台账=716）→ 改为 wc -l 口径（正文 2 处、台账 1 处、回执 lfl_readings.json 1 处）→ 重跑 build/audit/spotcheck 后 PASS（checks 37 fails 0）
tags: [LFL推广, 台账审计, 行数口径, wc-l, d92]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T20:21:45.628093+08:00"
updated_at: "2026-11-16T20:21:45.628093+08:00"
---