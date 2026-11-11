---
title: R5 台账的出处括注必须与所引行原文一致——同一数值出现在多处要拆行分别登记
scenario: R5 伴生台账逐行登记正文可核数值时：同一数值在正文出现在多处，却在台账只登记一行，出处的括注写的是别处上下文却指向本行。
root_cause: ""
solution: 台账每个数值行都要满足「所引行的原文包含该括注」：同一数值出现在不同语境 → 拆成多行、分别按所在行给括注与出处；引用的文件必须能独立证明该事实（当日的回执优先于前一日的 STATUS）。d77 实测：「两个问题」拆成第 57 行（问了两个问题）与第 86 行（有没有被污染/被污染之后有多严重）两行；「当日 3 篇」改指当日早班核对回执而非前一日 STATUS。
evidence: 终轮审稿子代理 subagent_b215aa31779b 的第 10 条意见（行 310 括注上下文与所引行号错位、行 320 引用前一日 STATUS）；修正脚本 docs/promotion/_d77_fix_ledger_r7.py；台账 receipts/d77-audit.json、d77-r5-sweep.json（85 行 0 失败）
tags: [R5, 台账, 出处, 可核数值, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T13:54:07.289855+08:00"
updated_at: "2026-11-11T13:54:07.289855+08:00"
---