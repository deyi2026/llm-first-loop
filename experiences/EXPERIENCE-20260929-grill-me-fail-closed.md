---
title: "grill_me 空返回根因是输入验证缺口而非\"过时先验\"——枚举式参数必须 fail-closed，且故障归因须先核代码"
scenario: "grill_me 传自定义 focus_areas 后静默返回 SUCCESS+第一层零问题；v2.1 提案曾将其归因为\"过时先验污染\"（R6 证据）"
root_cause: schema 无 enum 且运行时对未识别枚举值静默跳过（silent-success），测试缺负例
solution: "tools_skills.py:178 加 items.enum=[edge_cases,failure_modes,scale,security,ux]；运行时 recognized==0 → FAILURE 并列出合法值；补\"全部 unknown\"负例测试。对外部模型/自身给出的故障归因，先读实现代码再采纳为提案论据。当前性验证：grep -n \"focus_areas\" src/llm_loop/introspection/tools_skills.py 确认 178 行与 252-257 现状或修复态。"
evidence: "src/llm_loop/introspection/tools_skills.py:178（focus_areas 无 enum）、252-257（if area in _GRILL_QUESTIONS 静默跳过）、281-286（SUCCESS 返回）；tests/unit/test_tools_skills.py:89-98（仅合法值 security/scale 正例，无 unknown 负例）；本会话 2026-09-29 复现记录"
tags: [tool-contract, input-validation, fail-closed, attribution-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-29T21:42:34.520857+08:00"
updated_at: "2026-09-29T21:42:34.520857+08:00"
---

现象：grill_me 传入自定义 focus_areas 后返回 SUCCESS 但第一层零问题。第一层归因（v2.1 提案 R6）将其当作"过时先验污染"的证据；代码核验证明根因是输入验证缺口：schema 无 enum（tools_skills.py:178）且运行时对未知 area 静默跳过（252-257），全未知时仍 SUCCESS（281-286）。测试只有合法值正例（test_tools_skills.py:89-98）。两条教训：(1) 枚举式自由字符串参数必须 fail-closed——items.enum + recognized==0 时 FAILURE；(2) 对故障的语义归因（"这证明了 X 类风险"）必须先核代码再入提案，工具 bug 不得被抽象成论据，否则修复目标会错位（修 R6 治不了这个 bug）。当前性验证：grep -n "focus_areas" src/llm_loop/introspection/tools_skills.py —— 若 178 行 enum 仍缺失且 252-257 仍为静默跳过，则缺口仍在；修复后应见 items.enum 与 recognized==0 FAILURE 分支。复现：调用 grill_me 传 focus_areas=["nonexistent"]，修复前返回 SUCCESS+零问题，修复后应 FAILURE。