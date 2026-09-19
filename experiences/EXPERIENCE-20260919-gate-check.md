---
title: "汇报 gate 前必须逐 check 核对远端回执，不得以单一自检结果外推\"唯一失败原因\""
scenario: "PR #44（分支 fleet-reclaim-fence-20260919）在 ac7fc204d 时有两个失败检查：A.5 manifest 缺失 与 门禁（pyright）。向用户汇报时只看了 A.5 相关失败，陈述\"gate FAIL 的唯一原因是缺 manifest\"并承诺\"远端重跑预期通过\"。push manifest 提交 5e4b2a74d 后 A.5 转 SUCCESS，但门禁仍 FAILURE（runner.py:780 pyright），该错误在 ac7fc204d 的 check-runs 中本来就存在。"
root_cause: "把\"A.5 gate 自检 PASS\"过度泛化为\"远端重跑预期通过\"；未对 ac7fc204d 的全部 check-runs 逐项核对就断言唯一失败原因，属于 declaration 未先验证。"
solution: "汇报 gate 前必须枚举该 SHA 的全部 check-runs（gh api commits/<sha>/check-runs）并对每个 failing check 归因到 changed set；\"唯一原因\"类全称断言只允许在逐项核对后给出。本地自检复刻哪个 check 就只对哪个 check 下结论，不得外推到整个 gate。"
evidence: "2026-09-19 gh api check-runs@ac7fc204d 显示 门禁 failure×2（07:30:10Z、07:30:57Z），当时却向用户陈述\"gate FAIL 的唯一原因是缺 manifest\"；push 5e4b2a74d 后 A.5 转 SUCCESS 而门禁仍 FAILURE（pyright runner.py:780），证明先前归因遗漏。"
tags: [gate, honesty, declaration-verification, ci, pr]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T15:41:40.526820+08:00"
updated_at: "2026-09-19T15:41:40.526820+08:00"
---

在 PR gate 场景，"本地自检复刻了远端 gate" 若只复刻了其中一个 check（如 A.5 presence/coverage），不得表述为"gate FAIL 的唯一原因是 X"。汇报 gate 结论前应逐 check 列出远端回执（gh api commits/<sha>/check-runs），把每个 failing check 与 changed set 做归因（是否本分支引入）。本次若在推送前查过 ac7fc204d 的 check-runs，即可发现门禁既有失败，把"manifest 修复"与"pyright 修复"作为两个独立决策一次性呈报，省一轮往返。