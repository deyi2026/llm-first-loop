---
title: 正文写出的方法名必须与实际执行的方法逐字一致
scenario: LFL 推广 d72 晚班（2026-11-08）：正文第十节写「（`wc -l` 共 4754 行）」「（`wc -l` 共 972 行）」「（`wc -l` 共 2338 行）」标注三个源文件的行数口径，而真实回执 receipts/d72-lfl-static-readings.json 里 commands 记录的执行命令是 python3 `pathlib.Path(p).read_text(encoding='utf-8').splitlines()` 逐行计数——数值相同、工具名不同。第三轮独立审稿子代理抓为 P2：「正文标 wc -l，回执实为 python splitlines 计数，方法名不符」。
root_cause: 正文的方法名是从「习惯写法」落笔的，没有回读回执里的 commands 字段核对实际执行的那条命令；两者数值恰好相等，所以量化审计与全量实开 sweep 都没能发现，只有独立审稿读到了命令原文才抓住。
solution: 正文/图注里凡出现方法名（wc -l、splitlines、AST、find、git log --oneline 等），必须回读真实回执里实际执行的那条命令再落笔；不一致时改正文或改回执表述，不能凭印象写；拿不准就不写方法名，只写数值与出处文件路径。审稿包里的回执 JSON 与正文要同源于同一份 commands 字段，不能各写各的。
evidence: docs/promotion/receipts/d72-review-pkg.md（第三节之一回执 JSON 的 commands 字段）；审稿第三轮子代理 subagent_8125cb41ea6b 的 P2 结论；修订后回执字段已改为 line_counts + line_counts_method，正文改为「按行计数共 N 行」。
tags: [LFL推广, 口径一致, 方法名, 审稿P2, d72]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-08T20:35:50.742475+08:00"
updated_at: "2026-11-08T20:35:50.742475+08:00"
---