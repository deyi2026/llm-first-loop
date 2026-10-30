# 机械证据批采 manifest（proposal-only）

- 生成：scripts/qualification/method_mechanical_evidence.py collect，ran_at：2026-10-30T09:10:50+08:00
- 治理依据：docs/governance/card-lifecycle.md R3-bis（2026-10-30 修订：证据分流，使用优先）
- **本 manifest 不写库、不改卡**：脚本对 methods 目录无任何写路径；落地与回滚均由父会话执行。
- 选择口径：usage 账本非空 且 status=candidate；卡数：54
- 工具清单来源：src/llm_loop/tools/registry.py :: _COMPACT_TOOL_DESCRIPTIONS（56 项） + src/llm_loop/tools/builtin/*.py 模块名（41 项）；运行时动态注册的工具（如 method_manage）不在静态清单内（97 项）

## 汇总

- findings：3 条；判定分布：{'manual_review': 1, 'pass': 2}
  - local_path: {'pass': 2}
  - tool_existence: {'manual_review': 1}
- ready_to_land（verdict=fail 且证据可复跑）：0 条 / 0 张卡
- URL 待二次采样：0 条（间隔阈值 600s，状态文件 docs/governance/card-audit/2026-10-30-mechanical-evidence-pilot.url-samples.json）

## 逐卡发现

### method:admission-gated-command-run-verbatim-standalone-9ffd75920b0a（admission-gated-command-run-verbatim-standalone，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-19T07:49:24.886240+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-and-reuse-in-flight-validation-via-scheduler-record-2e1f5c1ceba3（attribute-and-reuse-in-flight-validation-via-scheduler-record，candidate；usage 2 条 {'applied': 2}，最近 2026-10-10T18:26:49.763134+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/perf 存在 | `test -e tests/perf` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-validation-run-via-structural-identity-before-reuse-e30bf0d78688（attribute-validation-run-via-structural-identity-before-reuse，candidate；usage 3 条 {'applied': 3}，最近 2026-10-10T18:26:50.163651+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-claimed-pending-work-via-result-artifacts-f180eb31a0fe（audit-claimed-pending-work-via-result-artifacts，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-10T21:58:48.727301+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-done-by-joining-plan-phase-table-with-vcs-topology-23d6a945eec7（audit-done-by-joining-plan-phase-table-with-vcs-topology，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T02:29:34.005499+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authority-gate-drift-map-before-lifecycle-plan-23f0e2d2ae69（authority-gate-drift-map-before-lifecycle-plan，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-28T08:53:05.220752+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-d5fce462ff6b（本地视频模型短片交付流水线（编剧→导演→生成→后期→独立审查），candidate；usage 1 条 {'applied': 1}，最近 2026-10-26T19:41:36.059365+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-desired-head-binding-before-restart-choose-update-2e3637e8aef7（check-desired-head-binding-before-restart-choose-update，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-13T02:00:11.035615+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:child-progress-from-settlement-receipt-not-stream-probes-3aa795a04639（child-progress-from-settlement-receipt-not-stream-probes，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-23T05:18:12.088618+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-diff-via-cited-primary-sources-before-generic-search-51bb939cc295（claim-diff-via-cited-primary-sources-before-generic-search，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-20T11:37:54.539783+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b（deferred-action-failure-layer-scoped-lifecycle-trace，candidate；usage 1 条 {'applied': 1}，最近 2026-10-07T21:19:37.941489+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:delegated-subagent-discipline-in-task-text-not-tool-description-77076544d5a7（delegated-subagent-discipline-in-task-text-not-tool-description，candidate；usage 3 条 {'applied': 3}，最近 2026-10-16T09:37:05.298661+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:destructive-replay-failure-shift-work-into-stable-paste-payload-67917b175573（destructive-replay-failure-shift-work-into-stable-paste-payload，candidate；usage 1 条 {'applied': 1}，最近 2026-10-18T22:51:51.489591+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:editor-model-authority-real-input-and-counter-invariants-7d9725013091（editor-model-authority-real-input-and-counter-invariants，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-18T22:51:51.573402+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-3249731118b4（exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-result，candidate；usage 2 条 {'applied': 2}，最近 2026-10-30T07:24:51.446970+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:family-containment-gate-before-batch-branch-merge-519261763620（family-containment-gate-before-batch-branch-merge，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T02:29:33.651360+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-attribution-on-shared-tree-with-active-foreign-writer-ef14c3fec208（gate-attribution-on-shared-tree-with-active-foreign-writer，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-26T07:22:38.148743+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-check-by-mechanical-state-not-memory-retrieval-e9f89cbf1205（gate-check-by-mechanical-state-not-memory-retrieval，candidate；usage 1 条 {'applied': 1}，最近 2026-10-20T16:40:55.391213+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:git-first-when-vcs-identifiers-are-named-9269c9624595（git-first-when-vcs-identifiers-are-named，candidate；usage 2 条 {'applied': 2}，最近 2026-10-17T02:29:33.812141+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-git-target-coordinates-before-location-sensitive-git-ops-aa0ebfc35d75（ground-git-target-coordinates-before-location-sensitive-git-ops，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T00:33:12.500581+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:index-miss-on-fresh-artifact-verify-disk-ground-truth-69d205734f31（index-miss-on-fresh-artifact-verify-disk-ground-truth，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T01:13:56.393210+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolation-preflight-before-trusting-gate-verdicts-6f1cd4e954c7（isolation-preflight-before-trusting-gate-verdicts，candidate；usage 2 条 {'applied': 2}，最近 2026-10-29T23:02:55.235575+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:literal-grep-and-source-scope-before-disputing-numbers-0595645fda7f（literal-grep-and-source-scope-before-disputing-numbers，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-21T20:31:39.392317+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-via-quoted-ui-literals-before-broad-filename-search-c867a42a91f8（locate-via-quoted-ui-literals-before-broad-filename-search，candidate；usage 1 条 {'applied': 1}，最近 2026-10-18T13:32:45.815602+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:max-blocking-wait-when-polling-background-subagents-d8b428b468c2（max-blocking-wait-when-polling-background-subagents，candidate；usage 3 条 {'applied': 3}，最近 2026-10-16T09:37:05.227979+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:max-wait-block-poll-and-interleave-parent-prep-for-long-subagents-c0aab429fa3f（max-wait-block-poll-and-interleave-parent-prep-for-long-subagents，candidate；usage 1 条 {'applied': 1}，最近 2026-10-16T09:37:05.153913+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mechanical-blind-eval-isolation-00c0648997ae（mechanical-blind-eval-isolation，candidate；usage 1 条 {'applied': 1}，最近 2026-10-05T23:28:40.990128+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 evals/instrument_qualification_v1/iq_R1_notes.md 存在 | `test -e evals/instrument_qualification_v1/iq_R1_notes.md` → `exit=0` | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `sha256sum` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:minimal-probe-before-full-payload-on-unverified-write-path-ba5bcd9406c0（minimal-probe-before-full-payload-on-unverified-write-path，candidate；usage 4 条 {'applied': 1, 'not_applicable': 3}，最近 2026-10-30T08:40:53.162144+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:multiplatform-publish-order-by-irreversibility-d9f5c7ea6b4d（multiplatform-publish-order-by-irreversibility，candidate；usage 2 条 {'applied': 1, 'not_applicable': 1}，最近 2026-10-20T13:43:20.566097+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:peer-claim-receipt-verification-with-variant-probe-resolution-e44e1db06594（peer-claim-receipt-verification-with-variant-probe-resolution，candidate；usage 1 条 {'applied': 1}，最近 2026-10-27T17:58:32.976118+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:pre-run-static-ratchets-before-freezing-fingerprint-bound-review-b9090ed45943（pre-run-static-ratchets-before-freezing-fingerprint-bound-review，candidate；usage 3 条 {'applied': 3}，最近 2026-10-30T07:24:50.930162+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:preclassify-record-kind-and-embed-currency-check-61032dc7e9bc（preclassify-record-kind-and-embed-currency-check，candidate；usage 1 条 {'applied': 1}，最近 2026-10-10T01:06:40.362772+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:preflight-reviewer-visible-delta-before-review-submission-12dd88f1e456（preflight-reviewer-visible-delta-before-review-submission，candidate；usage 1 条 {'applied': 1}，最近 2026-10-29T23:02:55.389918+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:prior-art-via-declared-sot-and-records-before-rule-authoring-a970cd148bfa（prior-art-via-declared-sot-and-records-before-rule-authoring，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T01:13:52.033297+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:probe-live-end-state-before-resuming-stale-failure-bd8bc0adafd0（probe-live-end-state-before-resuming-stale-failure，candidate；usage 1 条 {'applied': 1}，最近 2026-10-11T09:28:57.692446+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:receipt-state-first-verify-refs-not-tree-on-resume-adc543cfb7fd（receipt-state-first-verify-refs-not-tree-on-resume，candidate；usage 1 条 {'applied': 1}，最近 2026-10-19T07:49:24.619965+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:record-use-v3-1c1b05bfa2ee（record_use证据披露与评估纪律（v3·去强制降级），candidate；usage 2 条 {'adapted': 1, 'applied': 1}，最近 2026-10-23T08:57:40.007788+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:rederive-carried-scope-claims-before-design-d3984e4fc520（rederive-carried-scope-claims-before-design，candidate；usage 1 条 {'applied': 1}，最近 2026-10-20T20:54:20.641542+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:rehead-search-query-on-dictionary-degradation-8da50263deb1（rehead-search-query-on-dictionary-degradation，candidate；usage 1 条 {'applied': 1}，最近 2026-10-12T21:15:42.520497+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:rejection-reason-as-contract-diff-reissue-on-named-dimension-ec5de70cbb1c（rejection-reason-as-contract-diff-reissue-on-named-dimension，candidate；usage 4 条 {'adapted': 1, 'applied': 3}，最近 2026-10-26T21:04:58.189128+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:serial-single-file-edits-chained-on-write-receipt-precondition-af1a590dca78（serial-single-file-edits-chained-on-write-receipt-precondition，candidate；usage 2 条 {'applied': 2}，最近 2026-10-26T12:46:04.886735+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:serialize-cas-writes-by-chaining-snapshot-refs-65d014ca9b9a（serialize-cas-writes-by-chaining-snapshot-refs，candidate；usage 1 条 {'applied': 1}，最近 2026-09-30T19:41:17.327323+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verificat-83930d5efb0d（shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verification，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-26T07:22:38.729153+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:spawn-brief-context-budget-when-child-whitelist-lacks-offload-821400c1cede（spawn-brief-context-budget-when-child-whitelist-lacks-offload，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-23T05:18:12.183450+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:spot-verify-report-claims-at-pinned-primary-sources-d9f7bc5a0caa（spot-verify-report-claims-at-pinned-primary-sources，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-19T07:49:24.797818+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:subjective-feedback-rework-via-delivery-report-index-and-measured-disamb-58f9396ca6d5（subjective-feedback-rework-via-delivery-report-index-and-measured-disambiguation，candidate；usage 1 条 {'applied': 1}，最近 2026-10-26T21:14:31.967170+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:treat-derived-transcription-as-hypothesis-anchored-to-brief-3bc42539be4a（treat-derived-transcription-as-hypothesis-anchored-to-brief，candidate；usage 1 条 {'applied': 1}，最近 2026-10-21T20:31:39.224489+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:triage-gate-qualification-against-raw-review-verdict-and-authoritative-t-03ac6b83cfd7（triage-gate-qualification-against-raw-review-verdict-and-authoritative-truth，candidate；usage 3 条 {'applied': 2, 'not_applicable': 1}，最近 2026-10-30T07:24:51.281760+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:verify-async-terminal-state-via-action-record-before-attribution-ea34f423667f（verify-async-terminal-state-via-action-record-before-attribution，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-10T14:08:52.390468+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:verify-named-symbol-claims-via-live-tree-scoped-reads-dc2b42b80d1f（verify-named-symbol-claims-via-live-tree-scoped-reads，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-18T13:32:45.905104+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:verify-self-cited-evidence-list-before-discovery-bf6b94aa690e（verify-self-cited-evidence-list-before-discovery，candidate；usage 1 条 {'applied': 1}，最近 2026-10-21T20:31:39.308921+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:verify-sink-and-background-before-heavy-env-installs-f23d33455b3e（verify-sink-and-background-before-heavy-env-installs，candidate；usage 1 条 {'applied': 1}，最近 2026-10-23T13:27:35.084032+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:wip-ownership-by-freshness-not-history-fbad1497a281（wip-ownership-by-freshness-not-history，candidate；usage 1 条 {'applied': 1}，最近 2026-10-19T07:49:24.707861+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:write-precondition-token-before-first-edit-ad1f203fa6ef（write-precondition-token-before-first-edit，candidate；usage 1 条 {'applied': 1}，最近 2026-09-30T19:41:17.219588+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

## 应拦测试

每类判定的应拦输入实测见 `tests/test_method_mechanical_evidence.py`：URL 200 不判 fail、瞬态网络错误不判 fail、单次 404 不得 ready_to_land、存在的路径不得标记不存在、正文提及缺失不硬定罪、两次 404 间隔不足不采信、对 methods 目录零写入、输出路径落在 methods 目录内直接拒绝。

