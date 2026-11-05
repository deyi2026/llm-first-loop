---
title: 改稿后必须重新生成审稿包：下一轮审稿子代理读到旧包会误判「修订未落地」
scenario: LFL 推广班次的独立内容审稿多轮流程：第一轮审稿给 REVISE → 改稿 → 复跑落地复核。改稿后未重新生成审稿包（pkg1 = 主稿+台账），复跑子代理读到改稿前的旧包，把已落地的 13 条修订判成「未落地/半落地」，并据此给出 REVISE 与 P0/P1 计数；真实情况是第一轮那条 P0（curl 子进程外层超时被误标为 httpx 35 秒）已按源码改正。
root_cause: ""
solution: 改稿落地后、复跑落地复核前，必须重新生成审稿包（主稿+台账+对照表）与对照表的行号，并核对包内正文行号与现稿一致（对照表行号=包内行号−1 时要注明偏移）；若复跑结论与改稿记录矛盾，先核对审稿包是否过期，再判定是审稿误报还是真未落地。本班按此重生成包后，第四轮子代理对 13 条修订逐条判「已落地」，仅剩 1 条 P1（台账缺一行）。
evidence: docs/promotion/receipts/d63-review-fixes.md（对照表）与 d63-review-pkg1.md/pkg2.md 的重生成记录；第三轮子代理 subagent_43c235d9993c 结论（判定 11 条未落地）与第四轮 subagent_7e9be3fcf0ee 结论（13 条已落地）的差异；主稿 md sha 变更轨迹（a8077805… 前后）。
tags: [LFL推广, 审稿子代理, 审稿包, 落地复核, 误报]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-05T20:31:11.450432+08:00"
updated_at: "2026-11-05T20:31:11.450432+08:00"
supersedes: [EXPERIENCE-20261103-内容审稿子代理必须用精简审稿包-只读该包约束-否则会因上下文爆掉而失败收口]
---