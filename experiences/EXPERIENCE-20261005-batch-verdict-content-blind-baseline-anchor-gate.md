---
title: 批量人类裁定=内容盲基线：锚定补验必须设答卷区分度前置门
scenario: "IQ v1 人类锚补验（evals/instrument_qualification_v1/anchor/）：operator 通过会话批量指示\"全部 APPLY，理由：可用\"（web 端仅可预览无法编辑），预注册冻结门槛为一致率 ≥10/12。R1 子样 12 例中 9 例 APPLY，机械裁决得 9/12=HOLD。"
root_cause: ""
solution: "已按预注册如实裁决 HOLD 并在登记簿事件 #1 登记\"批量裁定、证据力不足\"；补救方向（已写入事件供后续预注册采用）：①答卷区分度前置门——全部 verdict 相同且 reason 逐字相同视为无效提交；②提交前展示各标签先验，声明\"恒选多数\"基线一致率，低于或等于基线的答卷自动判无证据力；③代填答卷时 ts 用指示原文时刻并在 provenance 中写明代填事实。当前性验证：cd evals/instrument_qualification_v1 && python3 -c \"import json;r=json.load(open('anchor/ANCHOR-RESULT.json'));print(r['verdict'],r['agreement'])\" 应输出 HOLD 9。"
evidence: "evals/instrument_qualification_v1/anchor/ANCHOR-RESULT.json（agreement=9/12, verdict=HOLD, per_case 三例 ✗）；anchor/ANCHOR-ANSWER.jsonl（12 例 reason 逐字相同\"可用\"）；evals/instrument_qualification_v1/iq_R1.jsonl（子样 9 APPLY/3 SKIP）；IQ-CTOR-v2-REGISTRY.md §4 事件 #1（证据力诊断）；commit dfdc4ca3a"
tags: [prereg, human-anchor, content-blind-baseline, iq-ctor-v2, evidence-weight]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-05T23:42:57.292371+08:00"
updated_at: "2026-10-05T23:42:57.292371+08:00"
---

人类锚/参照评者的预注册若只校验 verdict 合法性与 reason 非空，挡不住"全部 APPLY+逐字相同理由"的批量答卷：当子样多数标签恰为 APPLY 时，一致率会机械落在看似接近门槛的位置（本例 9/12 对 10/12 门），且数值与内容盲基线完全重合，却仍可能被误读为"人类基本一致、差一点通过"。诊断口诀：**算一遍"恒选多数标签策略"的期望一致率，若答卷一致率≤该基线，一致率信息量为零**。防再发：预注册加答卷区分度前置门（拒绝全同 verdict+逐字相同 reason 的提交），并在门槛表中把该基线列为无效解释区。当前性验证：cd evals/instrument_qualification_v1 && python3 -c "import json;r=json.load(open('anchor/ANCHOR-RESULT.json'));print(r['verdict'],r['agreement'])" 应输出 HOLD 9。