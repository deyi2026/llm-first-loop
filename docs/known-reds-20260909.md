# 已知红清单（Known Reds Registry）

维护日期：2026-09-09 ｜ 维护约定：本清单是「测试分层」防复发机制的一部分（见 `docs/subsystem-disposition-20260909.md` §4）。
预存在红不是放任，而是显式登记的现实约束：每项必须走「修复 或 显式接受」二选一，禁止用扩基线的方式让红卫兵变绿。

## 1. origin/main 基线预存红（8 项，2026-09-09 复核）

来源：origin/main 全量跑（存档 `/tmp/lfl-main-baseline-reds.txt`，已迁入本文件）。
复核结论（fix/restart-useful-continuity 线，2026-09-09 定向重跑）：**7 项转绿（exit=0），1 项退役，残留 = 0**。

| # | 测试 | 状态（2026-09-09） |
|---|---|---|
| 1 | tests/unit/test_err1210_session_isolation.py::TestTwoSessionInterleaving::test_interleaved_a1_to_a6 | 已退役：类在当前树不存在；宿主文件现役 2 测试全绿 |
| 2 | tests/unit/test_evidence_phase7_gate.py::test_r0_12_non_target_guardrails_and_no_provider_policy | 定向重跑绿 |
| 3 | tests/unit/test_evidence_r2_runner.py::test_r2_b0_is_observational_and_dry_demonstrates_repeat | 定向重跑绿 |
| 4 | tests/unit/test_evidence_r2_runner.py::test_r2_e1_reusable_dry_uses_hydration_without_source_repeat | 定向重跑绿 |
| 5 | tests/unit/test_evidence_r2_runner.py::test_r2_f6_dry_refreshes_once_then_hydrates_new_evidence | 定向重跑绿 |
| 6 | tests/unit/test_evidence_r2_runner.py::test_r2_frozen_scorer_passes_dry_contract_shape | 定向重跑绿 |
| 7 | tests/unit/test_evidence_r2_runner.py::test_r2_invalid_evidence_ref_is_tool_failure_not_infra | 定向重跑绿 |
| 8 | tests/unit/test_s2_fixture.py::test_s2_matrix_is_balanced_and_secondary_sample_stratified | 定向重跑绿 |

## 2. HEAD 预存红（4 项，working_set 投影）

来源：增量2 终验（r4 全量 + 七片并行双口径一致，2026-09-09 17:31，4816 passed / 4 failed / 23 skipped）。
定性：测试文件 `tests/unit/test_tool_working_set_projection.py` 于 2026-09-07 落盘于本地 fix 线（不在 origin/main）；
其被测实现 `src/llm_loop/.../episode_history.py` 未被增量2 diff 触碰，与增量2 无因果。**处置待定：修复 或 显式接受，二选一。**

| # | 测试 | 定性 |
|---|---|---|
| 1 | tests/unit/test_tool_working_set_projection.py::test_working_set_receipt_compacts_only_older_exposed_group | HEAD 预存红 |
| 2 | tests/unit/test_tool_working_set_projection.py::test_working_set_stats_report_only_mechanical_projection_facts | HEAD 预存红 |
| 3 | tests/unit/test_tool_working_set_projection.py::test_working_set_stats_expose_incomplete_batch_without_folding | HEAD 预存红 |
| 4 | tests/unit/test_tool_working_set_projection.py::test_working_set_receipt_exposes_mechanical_origin_not_task_judgment | HEAD 预存红 |
