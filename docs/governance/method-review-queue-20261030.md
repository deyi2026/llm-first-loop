# Method 独立评审/机械通道队列 — 2026-10-30

口径（card-lifecycle.md R3-bis，2026-10-30 修订）：usage 账本非空且 status=candidate。
生成命令：`python3 scripts/qualification/method_mechanical_evidence.py queue --methods-dir data/methods --out docs/governance/method-review-queue-20261030.md`（proposal-only，不写 data/methods）。

- 卡数：54；账本引用但无卡目录/非 candidate 的 ref：8（见文末）

| method_ref | 标题 | usage 计数 | decision 分布 | 最近使用 |
|---|---|---|---|---|
| `method:rejection-reason-as-contract-diff-reissue-on-named-dimension-ec5de70cbb1c` | rejection-reason-as-contract-diff-reissue-on-named-dimension | 4 | adapted×1, applied×3 | 2026-10-26T21:04:58.189128+08:00 |
| `method:minimal-probe-before-full-payload-on-unverified-write-path-ba5bcd9406c0` | minimal-probe-before-full-payload-on-unverified-write-path | 4 | applied×1, not_applicable×3 | 2026-10-30T08:40:53.162144+08:00 |
| `method:attribute-validation-run-via-structural-identity-before-reuse-e30bf0d78688` | attribute-validation-run-via-structural-identity-before-reuse | 3 | applied×3 | 2026-10-10T18:26:50.163651+08:00 |
| `method:max-blocking-wait-when-polling-background-subagents-d8b428b468c2` | max-blocking-wait-when-polling-background-subagents | 3 | applied×3 | 2026-10-16T09:37:05.227979+08:00 |
| `method:delegated-subagent-discipline-in-task-text-not-tool-description-77076544d5a7` | delegated-subagent-discipline-in-task-text-not-tool-description | 3 | applied×3 | 2026-10-16T09:37:05.298661+08:00 |
| `method:pre-run-static-ratchets-before-freezing-fingerprint-bound-review-b9090ed45943` | pre-run-static-ratchets-before-freezing-fingerprint-bound-review | 3 | applied×3 | 2026-10-30T07:24:50.930162+08:00 |
| `method:triage-gate-qualification-against-raw-review-verdict-and-authoritative-t-03ac6b83cfd7` | triage-gate-qualification-against-raw-review-verdict-and-authoritative-truth | 3 | applied×2, not_applicable×1 | 2026-10-30T07:24:51.281760+08:00 |
| `method:attribute-and-reuse-in-flight-validation-via-scheduler-record-2e1f5c1ceba3` | attribute-and-reuse-in-flight-validation-via-scheduler-record | 2 | applied×2 | 2026-10-10T18:26:49.763134+08:00 |
| `method:git-first-when-vcs-identifiers-are-named-9269c9624595` | git-first-when-vcs-identifiers-are-named | 2 | applied×2 | 2026-10-17T02:29:33.812141+08:00 |
| `method:multiplatform-publish-order-by-irreversibility-d9f5c7ea6b4d` | multiplatform-publish-order-by-irreversibility | 2 | applied×1, not_applicable×1 | 2026-10-20T13:43:20.566097+08:00 |
| `method:record-use-v3-1c1b05bfa2ee` | record_use证据披露与评估纪律（v3·去强制降级） | 2 | adapted×1, applied×1 | 2026-10-23T08:57:40.007788+08:00 |
| `method:serial-single-file-edits-chained-on-write-receipt-precondition-af1a590dca78` | serial-single-file-edits-chained-on-write-receipt-precondition | 2 | applied×2 | 2026-10-26T12:46:04.886735+08:00 |
| `method:isolation-preflight-before-trusting-gate-verdicts-6f1cd4e954c7` | isolation-preflight-before-trusting-gate-verdicts | 2 | applied×2 | 2026-10-29T23:02:55.235575+08:00 |
| `method:exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-3249731118b4` | exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-result | 2 | applied×2 | 2026-10-30T07:24:51.446970+08:00 |
| `method:write-precondition-token-before-first-edit-ad1f203fa6ef` | write-precondition-token-before-first-edit | 1 | applied×1 | 2026-09-30T19:41:17.219588+08:00 |
| `method:serialize-cas-writes-by-chaining-snapshot-refs-65d014ca9b9a` | serialize-cas-writes-by-chaining-snapshot-refs | 1 | applied×1 | 2026-09-30T19:41:17.327323+08:00 |
| `method:mechanical-blind-eval-isolation-00c0648997ae` | mechanical-blind-eval-isolation | 1 | applied×1 | 2026-10-05T23:28:40.990128+08:00 |
| `method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b` | deferred-action-failure-layer-scoped-lifecycle-trace | 1 | applied×1 | 2026-10-07T21:19:37.941489+08:00 |
| `method:preclassify-record-kind-and-embed-currency-check-61032dc7e9bc` | preclassify-record-kind-and-embed-currency-check | 1 | applied×1 | 2026-10-10T01:06:40.362772+08:00 |
| `method:verify-async-terminal-state-via-action-record-before-attribution-ea34f423667f` | verify-async-terminal-state-via-action-record-before-attribution | 1 | adapted×1 | 2026-10-10T14:08:52.390468+08:00 |
| `method:audit-claimed-pending-work-via-result-artifacts-f180eb31a0fe` | audit-claimed-pending-work-via-result-artifacts | 1 | adapted×1 | 2026-10-10T21:58:48.727301+08:00 |
| `method:probe-live-end-state-before-resuming-stale-failure-bd8bc0adafd0` | probe-live-end-state-before-resuming-stale-failure | 1 | applied×1 | 2026-10-11T09:28:57.692446+08:00 |
| `method:rehead-search-query-on-dictionary-degradation-8da50263deb1` | rehead-search-query-on-dictionary-degradation | 1 | applied×1 | 2026-10-12T21:15:42.520497+08:00 |
| `method:check-desired-head-binding-before-restart-choose-update-2e3637e8aef7` | check-desired-head-binding-before-restart-choose-update | 1 | not_applicable×1 | 2026-10-13T02:00:11.035615+08:00 |
| `method:max-wait-block-poll-and-interleave-parent-prep-for-long-subagents-c0aab429fa3f` | max-wait-block-poll-and-interleave-parent-prep-for-long-subagents | 1 | applied×1 | 2026-10-16T09:37:05.153913+08:00 |
| `method:ground-git-target-coordinates-before-location-sensitive-git-ops-aa0ebfc35d75` | ground-git-target-coordinates-before-location-sensitive-git-ops | 1 | applied×1 | 2026-10-17T00:33:12.500581+08:00 |
| `method:prior-art-via-declared-sot-and-records-before-rule-authoring-a970cd148bfa` | prior-art-via-declared-sot-and-records-before-rule-authoring | 1 | applied×1 | 2026-10-17T01:13:52.033297+08:00 |
| `method:index-miss-on-fresh-artifact-verify-disk-ground-truth-69d205734f31` | index-miss-on-fresh-artifact-verify-disk-ground-truth | 1 | applied×1 | 2026-10-17T01:13:56.393210+08:00 |
| `method:family-containment-gate-before-batch-branch-merge-519261763620` | family-containment-gate-before-batch-branch-merge | 1 | applied×1 | 2026-10-17T02:29:33.651360+08:00 |
| `method:audit-done-by-joining-plan-phase-table-with-vcs-topology-23d6a945eec7` | audit-done-by-joining-plan-phase-table-with-vcs-topology | 1 | applied×1 | 2026-10-17T02:29:34.005499+08:00 |
| `method:locate-via-quoted-ui-literals-before-broad-filename-search-c867a42a91f8` | locate-via-quoted-ui-literals-before-broad-filename-search | 1 | applied×1 | 2026-10-18T13:32:45.815602+08:00 |
| `method:verify-named-symbol-claims-via-live-tree-scoped-reads-dc2b42b80d1f` | verify-named-symbol-claims-via-live-tree-scoped-reads | 1 | adapted×1 | 2026-10-18T13:32:45.905104+08:00 |
| `method:destructive-replay-failure-shift-work-into-stable-paste-payload-67917b175573` | destructive-replay-failure-shift-work-into-stable-paste-payload | 1 | applied×1 | 2026-10-18T22:51:51.489591+08:00 |
| `method:editor-model-authority-real-input-and-counter-invariants-7d9725013091` | editor-model-authority-real-input-and-counter-invariants | 1 | adapted×1 | 2026-10-18T22:51:51.573402+08:00 |
| `method:receipt-state-first-verify-refs-not-tree-on-resume-adc543cfb7fd` | receipt-state-first-verify-refs-not-tree-on-resume | 1 | applied×1 | 2026-10-19T07:49:24.619965+08:00 |
| `method:wip-ownership-by-freshness-not-history-fbad1497a281` | wip-ownership-by-freshness-not-history | 1 | applied×1 | 2026-10-19T07:49:24.707861+08:00 |
| `method:spot-verify-report-claims-at-pinned-primary-sources-d9f7bc5a0caa` | spot-verify-report-claims-at-pinned-primary-sources | 1 | not_applicable×1 | 2026-10-19T07:49:24.797818+08:00 |
| `method:admission-gated-command-run-verbatim-standalone-9ffd75920b0a` | admission-gated-command-run-verbatim-standalone | 1 | not_applicable×1 | 2026-10-19T07:49:24.886240+08:00 |
| `method:claim-diff-via-cited-primary-sources-before-generic-search-51bb939cc295` | claim-diff-via-cited-primary-sources-before-generic-search | 1 | adapted×1 | 2026-10-20T11:37:54.539783+08:00 |
| `method:gate-check-by-mechanical-state-not-memory-retrieval-e9f89cbf1205` | gate-check-by-mechanical-state-not-memory-retrieval | 1 | applied×1 | 2026-10-20T16:40:55.391213+08:00 |
| `method:rederive-carried-scope-claims-before-design-d3984e4fc520` | rederive-carried-scope-claims-before-design | 1 | applied×1 | 2026-10-20T20:54:20.641542+08:00 |
| `method:treat-derived-transcription-as-hypothesis-anchored-to-brief-3bc42539be4a` | treat-derived-transcription-as-hypothesis-anchored-to-brief | 1 | applied×1 | 2026-10-21T20:31:39.224489+08:00 |
| `method:verify-self-cited-evidence-list-before-discovery-bf6b94aa690e` | verify-self-cited-evidence-list-before-discovery | 1 | applied×1 | 2026-10-21T20:31:39.308921+08:00 |
| `method:literal-grep-and-source-scope-before-disputing-numbers-0595645fda7f` | literal-grep-and-source-scope-before-disputing-numbers | 1 | adapted×1 | 2026-10-21T20:31:39.392317+08:00 |
| `method:child-progress-from-settlement-receipt-not-stream-probes-3aa795a04639` | child-progress-from-settlement-receipt-not-stream-probes | 1 | not_applicable×1 | 2026-10-23T05:18:12.088618+08:00 |
| `method:spawn-brief-context-budget-when-child-whitelist-lacks-offload-821400c1cede` | spawn-brief-context-budget-when-child-whitelist-lacks-offload | 1 | not_applicable×1 | 2026-10-23T05:18:12.183450+08:00 |
| `method:verify-sink-and-background-before-heavy-env-installs-f23d33455b3e` | verify-sink-and-background-before-heavy-env-installs | 1 | applied×1 | 2026-10-23T13:27:35.084032+08:00 |
| `method:gate-attribution-on-shared-tree-with-active-foreign-writer-ef14c3fec208` | gate-attribution-on-shared-tree-with-active-foreign-writer | 1 | not_applicable×1 | 2026-10-26T07:22:38.148743+08:00 |
| `method:shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verificat-83930d5efb0d` | shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verification | 1 | not_applicable×1 | 2026-10-26T07:22:38.729153+08:00 |
| `method:candidate-d5fce462ff6b` | 本地视频模型短片交付流水线（编剧→导演→生成→后期→独立审查） | 1 | applied×1 | 2026-10-26T19:41:36.059365+08:00 |
| `method:subjective-feedback-rework-via-delivery-report-index-and-measured-disamb-58f9396ca6d5` | subjective-feedback-rework-via-delivery-report-index-and-measured-disambiguation | 1 | applied×1 | 2026-10-26T21:14:31.967170+08:00 |
| `method:peer-claim-receipt-verification-with-variant-probe-resolution-e44e1db06594` | peer-claim-receipt-verification-with-variant-probe-resolution | 1 | applied×1 | 2026-10-27T17:58:32.976118+08:00 |
| `method:authority-gate-drift-map-before-lifecycle-plan-23f0e2d2ae69` | authority-gate-drift-map-before-lifecycle-plan | 1 | adapted×1 | 2026-10-28T08:53:05.220752+08:00 |
| `method:preflight-reviewer-visible-delta-before-review-submission-12dd88f1e456` | preflight-reviewer-visible-delta-before-review-submission | 1 | applied×1 | 2026-10-29T23:02:55.389918+08:00 |

## 未入队引用（账本有、卡不在或非 candidate）

- `method:candidate-a80acb208b99`：status=hold
- `method:locate-project-env-before-symptom-workarounds-f7dd29f1718b`：status=hold
- `method:method-repo-api-discovery`：no_card_dir
- `method:method-root-cause`：no_card_dir
- `method:method-self-distill`：no_card_dir
- `method:r9-gate-breakdown-triage-47132c4c89f8`：status=hold
- `method:resume-continuation-via-named-provenance-and-git-delta-948a229d7f50`：status=active
- `method:self-execute-review-contract-on-degenerate-tool-output-c1088a737f27`：status=qualified

