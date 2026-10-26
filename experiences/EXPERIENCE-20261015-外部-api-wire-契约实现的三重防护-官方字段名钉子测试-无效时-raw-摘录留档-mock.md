---
title: 外部 API wire 契约实现的三重防护：官方字段名钉子测试 + 无效时 raw 摘录留档 + mock 链独立审查
scenario: 对接第三方结构化 API（TypeSafe Jev / OpenRouter Decisions API）时，wire 层实现按记忆/直觉读响应字段名，未经官方文档逐字段核对；Mock 与 fixture 由同一实现者生成，共享同一误读，定向测试全绿。
root_cause: ""
solution: "三重防护：(1) 对官方契约的每个值字段写\"旧键/误拼键必须显式 invalid\"的钉子测试（正反例成对，三题型覆盖）；(2) 判定无效时持久化 raw 原文的有限摘录（截断上限+标注），使诊断不必重跑；(3) Mock/fixture 不手写契约样本，或至少让独立审查者对照官方文档核对 mock 链与所有传输件（含本地测试路径）的字段名。契约字段名以\"官方文档+独立 OpenAPI 规范+一次真实响应\"三方一致为准。当前性验证：grep -n 'raw.get(\"choice\")' src/llm_loop/knowledge/jev/wire.py 应命中；pytest tests/unit/test_jev_wire.py 应 27 passed；R4 报告 matches 应为 6。"
evidence: DESIGN v0.8.9 附录 C（SHA d9ffb7f7…）；代码闸回执 data/audit/code_gates/RULE-AI-28-jev-wire-official-fields-20261015.md（两轮 REVISE→PASS）；R4 报告 outputs/jev-p1b-20261015/p1b_or_report_r4.json（6/6 valid、matches=6、usage unknown 按冻结口径）
tags: [external-api, wire-contract, field-name-pinning, mock-blindspot, raw-excerpt-persistence, jev]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T13:20:41.816853+08:00"
updated_at: "2026-10-15T13:20:41.816853+08:00"
supersedes: [EXPERIENCE-20261015-mock-与实现共享契约误读时-全绿测试不能证明-wire-契约正确-p1b-or-首轮-6-6-i]
---

R1（§11.6）真实外发 6/6 题 contract_invalid 的根因：wire 验证器读自造 answer 键，官方为 choice/score/noul；Mock 与 fixture 共享同一误读（同构盲区），88 个定向测试全绿仍无法拦截；原始响应只存 hash 未留档，导致 choice 值不可事后恢复、只能修复后重跑。R4 修复轮补齐的三重防护已验证：(1) 官方字段名钉子测试——仅存在旧键时必须显式 invalid（choice/score/noul 三题型各一对正反例）；(2) 无效时 raw answers 原文摘录持久化（cap 4096 截断标注），全 valid 不复制 payload；(3) 独立两轮代码闸审查抓出 mock 链与本地传输件残留旧键（修复不完整的典型形态）。R4 执行 6/6 valid、6/6 与冻结盲评标签一致。适用边界：任何"文档描述的契约 vs 实现读的键"存在人工转录环节的集成（API/schema/配置文件解析）；不适用于无自造中间层的透传场景。当前性验证：`grep -n 'raw.get("choice")' src/llm_loop/knowledge/jev/wire.py` 应命中 _validate_choice；`python3 -m pytest tests/unit/test_jev_wire.py -q` 应 27 passed；复现 R4 报告：`python3 -c "import json;print(json.load(open('outputs/jev-p1b-20261015/p1b_or_report_r4.json'))['reconciliation']['matches'])"` 应得 6。