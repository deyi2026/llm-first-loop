---
title: 代码闸：静态棘轮必须在冻结审查指纹前跑绿，否则 PASS 回执必然失效并多花一轮重审+全量
scenario: 修改 tests/ 或 scripts/ 后走代码闸：独立审查先 PASS，全量测试随后才暴露仓库静态诊断棘轮门禁把新增 ruff 诊断判为 DENY，修复改指纹使原 PASS 失效
root_cause: 审查候选冻结前未先跑绿全量链中的静态棘轮段（ruff F401 属新增诊断），静态失败暴露在审查 PASS 之后 → 修复改指纹 → PASS 回执失效 → 需重审 + 重跑全量
solution: 改代码类任务：先把 ruff check <改动文件> 与 scripts/check_static_diagnostics.py --tool ruff 在本树跑绿，再冻结被审产物指纹送独立审查，审查 PASS 后才跑全量测试；全量中暴露的静态段失败须用同一门禁入口复验
evidence: "evidence://v1/64c9a2bfacdf47291c3d6c47ec6f84a936782b395bacc16d4a90c389322b5060（全量测试 1 failed/9683 passed，失败项为 static_diagnostic_gate 单测）；evidence://v1/fc1cac005577187e50f4ccd5b3de0425addbc5e6cc3e3a42943c045ebc944a65（BLOCK NEW x1: tests/test_method_candidate_qualification_harness.py F401 `pytest` imported but unused）；evidence://v1/257ccd6bbaedafa0159c12d28046a13a2c734edf685a687577105ba19edc70a9（删除未使用导入的 diff）；evidence://v1/b7921719ff7fd67ab945519eb9397adf4dc4f60b35a33ac137320b0bb15c2552（ruff All checks passed / harness 22 passed / gate 单测 1 passed）；evidence://v1/157a51658f7c0013c3a4073e31809ff69ff936126522749552746a33c226189f（新指纹下独立审查子代理 PASS）"
tags: [代码闸, RULE-AI-28, 静态棘轮, ruff, 指纹失效, 审查顺序]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T07:11:27.136686+08:00"
updated_at: "2026-10-30T07:11:27.136686+08:00"
supersedes: [EXPERIENCE-20261020-提交前静态检查须双棘轮全跑-动态-getattr-调用返回值须-isinstance-收窄]
---

场景：代码闸（RULE-AI-28(1)）先跑了独立审查并拿到 PASS，之后才跑全量测试；全量测试里仓库静态诊断棘轮门禁的单测失败，根因是本轮**新增**测试文件里一处未使用导入（import pytest）触发 ruff F401，门禁把『新增诊断』判为 DENY（BLOCK NEW + BLOCK CHANGED FILE）→ tests/unit/test_static_diagnostic_gate.py::test_unwritable_analyzer_cache_env_does_not_crash_main 失败。

结果与成本：修复（删未使用导入）改变了被审产物指纹 → 首轮 PASS 回执对当前指纹失效 → 必须重新窄复审（独立子代理 glm-5.3，子代理 id subagent_330333532341）+ 重跑全量测试 ≈ 多花一轮完整审查与一轮 12 分钟全量。

根因：审查与全量测试串行时，全量链里最便宜、最确定性的静态段（ruff / scripts/check_static_diagnostics.py）没有在冻结审查候选之前先跑绿；静态失败暴露在 PASS 之后，必然改指纹、必然让 PASS 失效。

解法（顺序纪律）：改 src/ tests/ scripts/ tools/ webui/ 的任务 → 先在本树把便宜确定性静态段跑绿（ruff check <改动文件>、scripts/check_static_diagnostics.py --tool ruff）→ 再冻结指纹送独立审查 → 再放行全量测试。全量测试里出现的静态段失败按同一入口重跑复验，不要只修单点断言。

反例：只修那一个单测断言、或在审查 PASS 之后才跑 ruff，都会让『审查回执覆盖当前产物』这条规则失效。

同源方法卡：method:pre-run-static-ratchets-before-freezing-fingerprint-bound-review-b9090ed45943（candidate，本轮 applied/helped）。