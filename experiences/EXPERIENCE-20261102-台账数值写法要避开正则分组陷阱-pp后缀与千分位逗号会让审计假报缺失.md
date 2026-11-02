---
title: 台账数值写法要避开正则分组陷阱——pp后缀与千分位逗号会让审计假报缺失
scenario: "LFL 推广的 R5 写前量化审计（正则抽正文数值 → 逐条对台账）出现假 MISSING：正文写「+24.24 个百分点」而台账写「+24.24pp」，正则把 pp 后缀当成词尾导致该数字不匹配；正文/台账里的「config.py 第 501、1139 行」被正则当成千分位分组「501,1139」当成一个数字 token，于是两个行号都匹配不上。两类写法让审计误报 13 处缺失。"
root_cause: ""
solution: 台账与正文的数值写法必须避开正则分组陷阱：① 不用英文单位后缀（pp/pct/pt 等紧贴数字），统一写「个百分点」；② 多值用中文顿号「、」分隔而不是半角逗号，避免被当成千分位；③ 审计脚本侧应对「数字＋单位」做白名单单位归一后再比对。改完复审：149 个数值 token、missing_count=0，且两项负向验证（删台账一行→必变 REVISE；台账数字全抹除→116 处 MISSING）都生效。
evidence: docs/promotion/STATUS-20261102-daily53.md 第四节（首轮 13 处 MISSING → 改写法后 149 token/0 MISSING，负向验证两项生效）；回执 receipts/daily53-r5-audit.json；台账 20261102-daily-53-sources.md。
tags: [audit, ledger, regex, promotion]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-02T13:37:46.807183+08:00"
updated_at: "2026-11-02T13:37:46.807183+08:00"
---