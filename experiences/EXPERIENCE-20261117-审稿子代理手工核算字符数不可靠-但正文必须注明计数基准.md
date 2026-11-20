---
title: 审稿子代理手工核算字符数不可靠，但正文必须注明计数基准
scenario: "d93 正文写「摘要正文 1,371 字符」，R2-A 审稿子代理逐句手工核算得约 1,350 并判 P2a，要求重算或注明计数基准。实际程序 len() 为 1,371（Python len 对 Unicode 字符计数，含标点与空格，不含首尾空白），人工逐字核算偏差约 20 字符。"
root_cause: ""
solution: 字符数一律以程序 len() 为准并在正文/台账注明计数基准（如「按 Python len() 计，含标点与空格，不含首尾空白」）；当审稿意见与程序回执冲突时，用程序回执复核并在 STATUS 里如实登记该条不成立及其依据，而不是按人工核算改数。
evidence: 回执 docs/promotion/receipts/d93research/arxiv-candidates-verify.json 的 summary 字段（len=1371）；R2-A 子代理判 P2a 要求注明基准；处置见 docs/promotion/_d93_apply_r2a.py 与 _d93_apply_r2a3.py（正文两处 + 台账一处加注基准）。
tags: [推广班次, 审稿, 计数基准]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-17T09:26:35.813115+08:00"
updated_at: "2026-11-17T09:26:35.813115+08:00"
---