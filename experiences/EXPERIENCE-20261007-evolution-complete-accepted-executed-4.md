---
title: evolution_complete 登记前先查建议状态：accepted/executed 状态下调用必被拒（跨日复发 4 次）
scenario: "对演进建议调用 evolution_complete 登记完成，但未先核对建议当前状态；建议已处于 accepted 或 executed（非 executing）时工具确定性拒绝（[无需登记]）。跨日复发：2026-09-24 三次、2026-10-07 18:42 一次。"
root_cause: ""
solution: "把\"查建议当前状态\"固化为 evolution_complete 的前置步骤：先经 architecture_status（evolution 相关维度）或建议存储查询状态，仅 executing 才调用 evolution_complete；accepted/executed 状态的涉边界建议改用 CLI evolve-complete 由人工路径标记。同参数重试必然复现，不要重试。"
evidence: "exception_log: 2026-09-24T02:43:45 / 03:08:17 / 04:14:17 tool.evolution_complete tool_failure [无需登记]；2026-10-07T18:42:02 tool.evolution_complete tool_failure（event_stream session=ca02bdc1 同刻 tool_call 后接 failure）"
tags: [evolution_complete, tool-contract, 状态前置检查, 防重复登记]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-07T21:19:37.657161+08:00"
updated_at: "2026-10-07T21:19:37.657161+08:00"
---

exception_log 实证：2026-09-24 三次（EVO-20260924-8266b693 于 accepted 与 executed 状态各一次、EVO-20260924-62221fd4 于 accepted）+ 2026-10-07T18:42:02 再次发生。回执文本明确："仅 executing 状态需登记完成（防重复登记/乱登记）"，涉边界建议的人工标记走 CLI evolve-complete。