---
title: 台账出处列引用回执字段时，字段值必须逐字等于回执原值；派生计算要写成算式，不能冒充字段值
scenario: "LFL 推广班次的 R5 伴生台账（docs/promotion/YYYYMMDD-daily-NN-sources.md）里，出处列引用机器回执的字段来支撑正文数值。d78（2026-11-11 晚班）台账写「call_module_count=5，实际调用点 6 处 = 直接调用 5 + 别名调用 1」与「neutralize_reference_frame.call_count=1」，而回执 d78-lfl-readings3.json 里的字段原值是 call_module_count=4（直接调用所在 4 个模块，别名调用的 trace_isolation.py 不在其中）与 call_count=2（:18 是 import 名字行、:112 才是真调用）。台账把「派生算出来的 5」「派生算出来的 1」写成了回执字段值。独立审稿（A2 包）据此给出 P1：字段值必须逐字等于回执里的值。"
root_cause: ""
solution: "规则：台账出处列引用回执字段时，字段值必须逐字等于回执里的值；派生计算必须写成算式而不是冒充字段值。做法：把派生量与字段值分两处写——字段原值单独引用（如 call_module_count=4、call_count=2），派生结论在同一格里用算式说明来源（如「call_module_count=4 = 直接调用所在的 4 个模块，另加别名调用的 trace_isolation.py，合计 5 个模块；调用点 6 处 = 直接调用 5 + 别名调用 1」）。台账生成脚本里对每个引用字段，优先用「字段名=值」原样串接，派生量一律带「=」算式前缀。当前性验证：跑 `python3 docs/promotion/_d78_ledger.py && python3 docs/promotion/_d78_audit.py` 应得 rows 96 / verdict PASS；`grep -c \"call_module_count=4\" docs/promotion/20261111-daily-78-sources.md` 应为 1、`grep -c \"call_count=2\" docs/promotion/20261111-daily-78-sources.md` 应为 2。"
evidence: docs/promotion/receipts/d78-lfl-readings3.json（call_module_count=4、neutralize_reference_frame.call_count=2）与 docs/promotion/20261111-daily-78-sources.md 台账行（曾写 call_module_count=5、call_count=1）；第 3 轮 A2 审稿子代理 subagent_962ff044da49 判 P1；订正见同台账与 _d78_ledger.py
tags: [LFL推广, R5台账, 审稿P1, 回执字段, 派生值]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-11T20:31:29.929004+08:00"
updated_at: "2026-11-11T20:31:29.929004+08:00"
---