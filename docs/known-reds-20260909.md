# 已知红清单（Known Reds Registry）

维护日期：2026-10-13 ｜ 维护约定：本清单是「测试分层」防复发机制的一部分（见 `docs/subsystem-disposition-20260909.md` §4）。
预存在红不是放任，而是显式登记的现实约束：每项必须走「修复 或 显式接受」二选一，禁止用扩基线的方式让红卫兵变绿。

各节结论仅适用于其注明的候选、时间和执行环境。历史基线「残留 = 0」不代表当前全量测试全绿；外部报告中的失败也须在当前环境复核后再归因。Skipped 表示未验证，不是部署资格或安全门禁通过。

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

## 3. 2026-10-13 macOS 环境差异复核（R1–R3）

复核者：本轮维护执行者；处置负责人：仓库维护者；复核环境：LFL MCP Console、macOS 26.5.1 arm64、Python 3.13.13。
候选基线：`main@3af8213fa6aea5acc2cf4e632e22a6c31a31cca5` 加当时暂存的 Phase4 源码/测试改动，在隔离 worktree 固定验证。
源 index tree：`0ee9001cfeb9a0a9d50a19d9bbaf9513bc9eb6bb`；继承补丁 SHA-256：`53eb8f2a4b76dd9946c00efe8b1d4c446a7a625b4cec7b62698c0581c238f4d2`。
本节不为其他暂存改动背书，也不产生发布/重启资格。

定向基线命令（默认排除 real_llm）：

```bash
python -m pytest tests/phase4/test_m2_inflight_interrupt.py::test_d_gate_conservative_matrix tests/unit/test_assurance_p1_process_reviewer.py tests/unit/test_task_budget_operator_mailbox.py tests/unit/test_static_diagnostic_gate.py tests/integration/test_browser_semantic_guard_e2e.py tests/integration/test_browser_dispatch_settle_e2e.py -q --tb=short --junitxml=data/r123-baseline.xml
```

执行时使用项目 `.venv`，工作目录为该隔离候选。结果：**44 passed / 5 errors，exit=1**。原始 JUnit 位于候选 `data/r123-baseline.xml`，SHA-256：`5081efdafaed55a54c181d0a18d8d8819db11b1038b322e5f8c868679724cab0`；它是本地验收证据，不是公开能力分数。

| 复核面 | 当前结果 | 归因与处置 |
|---|---|---|
| `test_d_gate_conservative_matrix` | 1 passed | 当前候选已先构造 engine、后注册纯 sleep 工具；外部报告中的 UnboundLocalError 在此候选未复现。保留该回归用例，不推断历史代码闸是否执行 |
| `test_assurance_p1_process_reviewer.py` | 10 passed | 当前环境真实 sandbox-exec 用例通过；`(version 1) (allow default)` + true 探针 exit=0。外部报告的沙箱失败不应泛化为 macOS 全局不可用，不增加 skip 或放宽安全断言 |
| `test_task_budget_operator_mailbox.py` | 12 passed | 当前环境 chmod 0o2750 后观测值仍为 0o2750；外部报告的 setgid 失败未复现。单 UID 单测仍不替代真实多 UID 部署资格 |
| `test_static_diagnostic_gate.py` | 17 passed | 当前候选缓存不可写负例及其他诊断门测试通过；不登记为当前已确认源码缺陷 |
| `test_browser_dispatch_settle_e2e.py` | 4 passed | 当前环境使用可发现的浏览器完成真实 E2E；该结果只覆盖此文件 |
| `test_browser_semantic_guard_e2e.py` | 5 setup errors | Playwright 返回的默认缓存 executable_path 对应文件不存在；原 fixture 在 Popen 前未检查文件。按文件已声明的可选浏览器契约补存在性检查，缺失时准确 skipped；既有 CDP 未就绪分支也会 skipped，均表示未验证，不代表浏览器资格通过 |

语义守卫的 5 个错误节点：

- `test_e1_guard_pass_exempts_version_mismatch`
- `test_e2_neighborhood_change_is_rejected_without_execution`
- `test_e3_overlay_occlusion_is_rejected`
- `test_e4_detached_node_is_rejected`
- `test_e5_password_value_never_persists_in_plaintext`

复核条件：候选源码、Python、浏览器路径/缓存、执行宿主或权限改变时重跑受影响文件。浏览器功能资格验收必须在已安装浏览器的指定环境执行，并核实相关用例实际运行；缺少依赖或全部 skipped 应记为前置条件不足，不能声称资格通过。没有本轮 CI 运行证据时，不宣称「Ubuntu CI 全绿」。

### 全量门禁补充观察：保守矩阵时序竞争

本轮第一次 `scripts/ci_gate.sh` 的并行全量：**1 failed / 8747 passed / 146 skipped**；失败节点为 `tests/phase4/test_m2_inflight_interrupt.py::test_d_gate_conservative_matrix`，在副作用 settle 后期望 gate=True，实际 False。该文件随后按既有 D-B2-09 流程串行复核 **6 passed**，ci_gate 最终 exit=0；这不等于并行全量零失败，也不能据此宣称已确定根因。

处置：登记观察并修复测试的生命周期前提。原 fixture 只用固定 5 秒 sleep 保活，未确认工具进入在途就 enqueue，存在与前置队列消费或 run 结束竞争的窗口。改为 entered/release 事件同步，确认工具进入在途后执行原断言，finally 释放工具，并恢复临时修改的 run-generation context。全部保守矩阵断言保留；不增加永久 flaky 豁免、不修改生产门禁或历史基线。最终结果另见本轮验证回执。
