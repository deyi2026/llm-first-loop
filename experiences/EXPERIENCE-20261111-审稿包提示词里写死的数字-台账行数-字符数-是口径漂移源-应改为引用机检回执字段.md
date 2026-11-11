---
title: 审稿包提示词里写死的数字（台账行数/字符数）是口径漂移源——应改为引用机检回执字段
scenario: "LFL 推广班次的多轮独立审稿：把「正文非空白字符 8,120」「台账 78 行」这类随改稿/补台账而变的量写进审稿包核对清单。"
root_cause: ""
solution: 核对清单里凡是会随产物变化的量，一律引用机检回执字段（如 build.md_nonws / audit.n_ledger_rows），不写死数字；若清单必须自带数字，则在每次 build/补台账后同步订正，并在审稿任务书里显式提示「清单中的行数/字符数以本包回执为准」。d77 实测：台账 76→78→84→85 行、md_nonws 8231 漂移了 3 次，每次都要人工订正清单，多跑了 3 轮 A2。
evidence: "docs/promotion/_d77_reviewpkg.py（清单第 12 条原写「台账 78 行 / 正文非空白字符 8,120」）、_d77_fix_pkg_rowcount2.py、_d77_fix_pkg_rowcount3.py；终轮审稿意见见 receipts/d77-review-pkg-a2.md 与 STATUS-20261111-daily77.md 第八节教训 ③"
tags: [审稿子代理, 审稿包, 提示词, 漂移, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T13:54:02.297663+08:00"
updated_at: "2026-11-11T13:54:02.297663+08:00"
---