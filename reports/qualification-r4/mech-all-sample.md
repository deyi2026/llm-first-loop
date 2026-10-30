# 机械证据批采 manifest（proposal-only）

> **入库形态说明（内容零删减）**：本文件原为 `mech-all-sample.md`（676921 B / 10,161 行）。因 review_admission 的单路径 git 输出上限（400 KB），整份无法入库，**按 `### method:<id>` 小节边界拆为两部分**：本文件为第 1 部分（第 1 部分以完整小节收尾），余下部分见 `mech-all-sample.part2.md`。除本行说明外，原始头部元信息（生成命令 / ran_at / 汇总）与全部卡片发现**逐字未改**。

- 生成：scripts/qualification/method_mechanical_evidence.py collect，ran_at：2026-10-30T12:57:39+08:00
- 治理依据：docs/governance/card-lifecycle.md R3-bis（2026-10-30 修订：证据分流，使用优先）
- **本 manifest 不写库、不改卡**：脚本对 methods 目录无任何写路径；落地与回滚均由父会话执行。
- 选择口径：显式卡清单；卡数：1641
- 工具清单来源：src/llm_loop/tools/registry.py :: _COMPACT_TOOL_DESCRIPTIONS（56 项） + src/llm_loop/tools/builtin/*.py 模块名（42 项）；运行时动态注册的工具（如 method_manage）不在静态清单内（98 项）

## 汇总

- findings：175 条；判定分布：{'fail': 1, 'manual_review': 79, 'no_verdict': 1, 'pass': 94}
  - local_path: {'fail': 1, 'manual_review': 56, 'pass': 89}
  - tool_existence: {'manual_review': 23, 'pass': 5}
  - url: {'no_verdict': 1}
- ready_to_land（verdict=fail 且证据可复跑）：1 条 / 1 张卡
- URL 待二次采样：0 条（间隔阈值 600s，状态文件 reports/qualification-r4/mech-all-sample.url-samples.json）

## 逐卡发现

### method:a-b-environment-before-preexisting-baseline-b4cda1c9bdee（a-b-environment-before-preexisting-baseline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:absence-check-via-definition-site-then-vcs-history-4a2c300a684f（absence-check-via-definition-site-then-vcs-history，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:absence-claim-probe-by-term-decomposition-b574233f4f9a（absence-claim-probe-by-term-decomposition，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:absence-proof-store-coverage-then-conclude-f0f333894129（absence-proof-store-coverage-then-conclude，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:acceptance-coverage-gate-before-completion-transition-bf181dfbfef1（acceptance-coverage-gate-before-completion-transition，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:act-on-in-context-provenance-not-re-discovery-searches-26a2361824c5（act-on-in-context-provenance-not-re-discovery-searches，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:act-on-out-of-band-notification-via-exact-id-record-hydration-978e53da7a53（act-on-out-of-band-notification-via-exact-id-record-hydration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:act-on-provenance-rich-record-hit-receipt-verifies-ca3c9572705a（act-on-provenance-rich-record-hit-receipt-verifies，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:activation-gate-first-when-reviewing-reuse-existing-pipeline-c3852342964e（activation-gate-first-when-reviewing-reuse-existing-pipeline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:activation-proof-via-path-exclusive-runtime-artifact-7820b3887881（activation-proof-via-path-exclusive-runtime-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:address-named-commit-before-store-search-containment-gate-d6fee67cfe40（address-named-commit-before-store-search-containment-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-absence-claims-by-consumer-channel-not-agent-visibility-ab7519f6304b（adjudicate-absence-claims-by-consumer-channel-not-agent-visibility，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-artifact-behavior-at-definition-not-generative-oracle-96f39a8947d7（adjudicate-artifact-behavior-at-definition-not-generative-oracle，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-contradicted-action-via-execution-receipt-cc18383a0df7（adjudicate-contradicted-action-via-execution-receipt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-from-alert-payload-audit-claims-before-write-855b2b6f199a（adjudicate-from-alert-payload-audit-claims-before-write，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-governance-staleness-claim-by-line-diff-and-sync-pairing-1e2622fcd0e2（adjudicate-governance-staleness-claim-by-line-diff-and-sync-pairing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-handover-identity-claims-before-prescribed-actions-b885d6cb2739（adjudicate-handover-identity-claims-before-prescribed-actions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-metric-divergence-at-producer-semantics-f4ef6fba25bb（adjudicate-metric-divergence-at-producer-semantics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-prior-claims-via-definition-surface-not-keyword-discovery-b840be51dc0e（adjudicate-prior-claims-via-definition-surface-not-keyword-discovery，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 evals/docs/experiences 存在 | `test -e evals/docs/experiences` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-proposal-by-verifying-self-cited-anchors-against-current-arti-0707b8da16b5（adjudicate-proposal-by-verifying-self-cited-anchors-against-current-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-rule-instance-by-counterfactual-not-enforcement-firing-36ae88c1469d（adjudicate-rule-instance-by-counterfactual-not-enforcement-firing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-rule-vs-implementation-actor-conflict-via-mediating-entry-da13286ccfa9（adjudicate-rule-vs-implementation-actor-conflict-via-mediating-entry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-trigger-by-decision-quadruple-count-independent-instances-6ca90ac8e10c（adjudicate-trigger-by-decision-quadruple-count-independent-instances，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-undecided-branch-conflict-by-main-touchpoint-state-4ae079d12857（adjudicate-undecided-branch-conflict-by-main-touchpoint-state，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-unowned-worktree-diff-before-delivery-advice-487f13f3884e（adjudicate-unowned-worktree-diff-before-delivery-advice，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adjudicate-version-pinned-claims-via-describe-certificate-and-tag-anchor-a49a1c027ef8（adjudicate-version-pinned-claims-via-describe-certificate-and-tag-anchor，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:admission-child-poll-namespace-matched-calls-5ef17849c1f7（admission-child-poll-namespace-matched-calls，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:admission-deny-despite-pass-stabilize-drifting-snapshot-reissue-929c91de164e（admission-deny-despite-pass-stabilize-drifting-snapshot-reissue，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:admission-gated-command-run-verbatim-standalone-9ffd75920b0a（admission-gated-command-run-verbatim-standalone，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-19T07:49:24.886240+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:adversarial-cross-review-before-high-stakes-output-8a3f221d3646（adversarial-cross-review-before-high-stakes-output，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:advisory-vs-blocking-precheck-mismatch-under-single-shot-authorization-37ce1c56ba2f（advisory-vs-blocking-precheck-mismatch-under-single-shot-authorization，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:affect-complaint-proxy-metrics-structural-preclusion-29681675730c（affect-complaint-proxy-metrics-structural-preclusion，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:agent-report-audit-claim-class-triage-verbatim-citation-4318ac62173a（agent-report-audit-claim-class-triage-verbatim-citation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:alias-safe-patch-with-sentinel-flip-before-trusting-zero-delta-de1cc40ff018（alias-safe-patch-with-sentinel-flip-before-trusting-zero-delta，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:alien-literal-polluter-hunt-fceef795e7c0（alien-literal-polluter-hunt，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:align-repo-advice-with-recorded-decisions-first-0973b39f2d2e（align-repo-advice-with-recorded-decisions-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:align-session-gap-with-restart-timestamps-before-broad-search-73202fbb57ff（align-session-gap-with-restart-timestamps-before-broad-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:allowlist-names-from-authoritative-definition-not-summary-28a550ac5cac（allowlist-names-from-authoritative-definition-not-summary，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ambient-env-differential-probe-on-self-hosting-runtime-review-c64e81b40446（ambient-env-differential-probe-on-self-hosting-runtime-review，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ambiguous-timeout-verify-landed-before-rerun-2fad1c47ee54（ambiguous-timeout-verify-landed-before-rerun，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anaphora-artifact-first-context-recovery-42e2e7649585（anaphora-artifact-first-context-recovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anatomy-triage-failed-gated-oneshot-then-readonly-aftermath-399722b02df3（anatomy-triage-failed-gated-oneshot-then-readonly-aftermath，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-and-derive-environment-parameters-8d332b7db8e5（anchor-and-derive-environment-parameters，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-and-tail-retrieval-on-truncated-ordered-ci-logs-64a37bedf123（anchor-and-tail-retrieval-on-truncated-ordered-ci-logs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-artifact-discovery-on-restored-state-workspace-field-5372dff228a6（anchor-artifact-discovery-on-restored-state-workspace-field，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-background-job-polling-to-duration-prior-1dfd748c4afb（anchor-background-job-polling-to-duration-prior，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-complete-gate-query-before-remote-mutation-f3e6129501ef（anchor-complete-gate-query-before-remote-mutation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-content-search-on-observed-literal-tokens-8d7925c691d2（anchor-content-search-on-observed-literal-tokens，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop 存在 | `test -e src/llm_loop` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-declared-worktree-root-before-commands-695487311c0e（anchor-declared-worktree-root-before-commands，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-directive-timestamp-diff-authoritative-concurrent-records-31393cedac00（anchor-directive-timestamp-diff-authoritative-concurrent-records，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-driven-reads-from-authoritative-record-2da4c04b01dc（anchor-driven-reads-from-authoritative-record，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-evidence-to-instance-lifecycle-window-fffe781df7d0（anchor-evidence-to-instance-lifecycle-window，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-fingerprint-admission-on-committed-worktree-not-shared-main-tree-afc57d918076（anchor-fingerprint-admission-on-committed-worktree-not-shared-main-tree，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-first-claim-audit-81071f5c9dc1（anchor-first-claim-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-history-sweep-before-cross-branch-reproduction-f37203595eca（anchor-history-sweep-before-cross-branch-reproduction，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-index-for-positional-unknowns-not-repeat-reads-72e11512f200（anchor-index-for-positional-unknowns-not-repeat-reads，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-mutation-target-to-registry-id-not-narrative-e10041e28500（anchor-mutation-target-to-registry-id-not-narrative，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-narrow-wiring-at-construction-site-7f3ff30de391（anchor-narrow-wiring-at-construction-site，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 src/xx/runtime 存在 | `test -e src/xx/runtime` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-new-ops-rule-in-governed-tool-dryrun-baseline-69fccbd61697（anchor-new-ops-rule-in-governed-tool-dryrun-baseline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-next-step-advice-on-frozen-plan-branch-order-ae7d27a852e4（anchor-next-step-advice-on-frozen-plan-branch-order，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-on-self-report-then-probe-gaps-003c0af478b6（anchor-on-self-report-then-probe-gaps，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-on-unique-identifier-to-find-mechanism-ae14900fecb5（anchor-on-unique-identifier-to-find-mechanism，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/files 存在 | `test -e docs/files` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-process-verification-on-deployment-identity-1a2a8ee84ad1（anchor-process-verification-on-deployment-identity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-quoted-ui-label-to-its-data-source-4ae2f64ced6c（anchor-quoted-ui-label-to-its-data-source，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-reused-gate-assertions-to-cross-issue-stable-markers-43b62f6c15e5（anchor-reused-gate-assertions-to-cross-issue-stable-markers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-sufficiency-stop-959b50a21a4c（anchor-sufficiency-stop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-token-content-search-to-scope-test-regression-before-local-edit-14b054335f59（anchor-token-content-search-to-scope-test-regression-before-local-edit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-unprovenanced-env-params-by-direct-observation-94d543a1f9dd（anchor-unprovenanced-env-params-by-direct-observation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-vague-status-on-freshest-conclusion-artifact-06146068f19e（anchor-vague-status-on-freshest-conclusion-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-verification-over-narrative-recovery-73fa76a07438（anchor-verification-over-narrative-recovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-work-counts-to-typed-event-ledger-7aa18c13204d（anchor-work-counts-to-typed-event-ledger，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-workdir-params-to-current-session-receipt-paths-91256589a15c（anchor-workdir-params-to-current-session-receipt-paths，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchor-workspace-root-via-shell-before-path-parameterized-calls-696685bfda7f（anchor-workspace-root-via-shell-before-path-parameterized-calls，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/ai_rules.md 存在 | `test -e docs/ai_rules.md` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anchored-grep-and-symbol-existence-first-for-named-contract-verification-384210dfcc3c（anchored-grep-and-symbol-existence-first-for-named-contract-verification，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/scripts/worktree 存在 | `test -e docs/scripts/worktree` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:anonymous-verify-release-via-user-path-with-robust-curl-7f25f29313bd（anonymous-verify-release-via-user-path-with-robust-curl，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:answer-go-no-go-status-from-pipeline-attestation-artifacts-0292317a876f（answer-go-no-go-status-from-pipeline-attestation-artifacts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:answer-terse-ref-from-authoritative-goal-record-bound-recovery-f5a3ce3d72c2（answer-terse-ref-from-authoritative-goal-record-bound-recovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:api-key-file-handoff-verify-value-lineage-not-just-path-d0f9577f4b90（api-key-file-handoff-verify-value-lineage-not-just-path，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:app-behavior-trace-live-tree-before-broad-search-1fe8ad32d916（app-behavior-trace-live-tree-before-broad-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:arithmetic-preverdict-then-load-bearing-first-verification-801d60f8fa7a（arithmetic-preverdict-then-load-bearing-first-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:artifact-anchored-state-first-pending-status-check-12f850a64cd2（artifact-anchored-state-first-pending-status-check，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:artifact-first-retrieval-then-discriminating-delta-probe-3bd8fd455a48（artifact-first-retrieval-then-discriminating-delta-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:artifact-provenance-forensics-for-similarity-influence-challenges-d051a439ba9c（artifact-provenance-forensics-for-similarity-influence-challenges，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf（artifact-symbol-lineage-before-mechanism-reading，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:assertions-as-spec-first-for-behavior-edits-c1f836aa31cd（assertions-as-spec-first-for-behavior-edits，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit/test_evaluator.py 存在 | `test -e tests/unit/test_evaluator.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:async-action-terminal-ledger-first-7f9a435b6e99（async-action-terminal-ledger-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:async-receipt-not-outcome-check-action-record-fix-named-blocker-129c637edfb9（async-receipt-not-outcome-check-action-record-fix-named-blocker，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb（async-wait-on-pipeline-conclusion-not-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:atomic-re-resolve-and-act-on-silent-hit-bfe6811182f1（atomic-re-resolve-and-act-on-silent-hit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attach-command-when-gate-released-break-intent-spin-51ace52774ed（attach-command-when-gate-released-break-intent-spin，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attach-feasibility-gate-then-authoritative-config-42e640eda0c3（attach-feasibility-gate-then-authoritative-config，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-and-reuse-in-flight-validation-via-scheduler-record-2e1f5c1ceba3（attribute-and-reuse-in-flight-validation-via-scheduler-record，candidate；usage 2 条 {'applied': 2}，最近 2026-10-10T18:26:49.763134+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/perf 存在 | `test -e tests/perf` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-artifact-via-unique-token-before-impl-deep-read-28d50e49311f（attribute-artifact-via-unique-token-before-impl-deep-read，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-cause-and-consumer-census-before-conditional-disable-c9d77348e196（attribute-cause-and-consumer-census-before-conditional-disable，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-degradation-to-per-round-prefix-producers-3f8e96b65171（attribute-degradation-to-per-round-prefix-producers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-delegate-work-by-action-log-not-ambient-mtime-eae61bb181a2（attribute-delegate-work-by-action-log-not-ambient-mtime，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-delegation-failure-via-receipt-and-cross-session-scope-31ba83df00f2（attribute-delegation-failure-via-receipt-and-cross-session-scope，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-error-to-named-token-verify-silent-mutation-via-ledger-57bb1af8d03a（attribute-error-to-named-token-verify-silent-mutation-via-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-gate-failures-before-deep-dive-b541c0704b8e（attribute-gate-failures-before-deep-dive，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-health-alarm-to-owning-instance-via-per-instance-telemetry-d3a0cd006bc4（attribute-health-alarm-to-owning-instance-via-per-instance-telemetry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-masked-test-failure-via-inner-exception-type-15b70f722c9c（attribute-masked-test-failure-via-inner-exception-type，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-own-job-status-by-durable-receipt-not-ambient-process-28a05ddde0fb（attribute-own-job-status-by-durable-receipt-not-ambient-process，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/perf 存在 | `test -e tests/perf` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-run-origin-via-session-record-not-action-logs-f9106ca09382（attribute-run-origin-via-session-record-not-action-logs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-scan-block-to-pushed-delta-vs-scanner-fallback-087a17f015ef（attribute-scan-block-to-pushed-delta-vs-scanner-fallback，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-served-build-by-hashed-asset-name-before-local-binding-compare-2a5475cb9a50（attribute-served-build-by-hashed-asset-name-before-local-binding-compare，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc（attribute-suite-failures-via-touched-set-and-clean-head-worktree，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-unexpected-snapshot-delta-via-timestamp-and-own-action-invento-e31596a71b59（attribute-unexpected-snapshot-delta-via-timestamp-and-own-action-inventory，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:attribute-validation-run-via-structural-identity-before-reuse-e30bf0d78688（attribute-validation-run-via-structural-identity-before-reuse，candidate；usage 3 条 {'applied': 3}，最近 2026-10-10T18:26:50.163651+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-card-library-by-recent-failure-receipt-diff-3d0c0a5f7284（audit-card-library-by-recent-failure-receipt-diff，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-change-completion-across-written-verified-live-layers-08d83466d403（audit-change-completion-across-written-verified-live-layers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-claimed-pending-work-via-result-artifacts-f180eb31a0fe（audit-claimed-pending-work-via-result-artifacts，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-10T21:58:48.727301+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6（audit-closure-via-transition-event-receipts-not-artifact-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-context-token-leaks-across-rejection-early-returns-fe7c8efd74ed（audit-context-token-leaks-across-rejection-early-returns，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-done-by-joining-plan-phase-table-with-vcs-topology-23d6a945eec7（audit-done-by-joining-plan-phase-table-with-vcs-topology，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T02:29:34.005499+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary-340f7604d311（audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-judge-run-metadata-and-rule-wiring-before-acting-on-blocking-verdi-c469c8be7c51（audit-judge-run-metadata-and-rule-wiring-before-acting-on-blocking-verdict，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-judge-vocab-vs-real-failures-decouple-batch-axis-via-checkpoints-ffd98d454e97（audit-judge-vocab-vs-real-failures-decouple-batch-axis-via-checkpoints，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-ledger-first-when-unverified-handoff-claims-pending-op-9d5a377043e0（audit-ledger-first-when-unverified-handoff-claims-pending-op，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-own-write-probe-footprint-before-state-criteria-fdf92764045f（audit-own-write-probe-footprint-before-state-criteria，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-receipt-identity-before-chasing-reported-failures-d82a836d9dda（audit-receipt-identity-before-chasing-reported-failures，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-report-by-resolving-cited-pointers-4cbbd66a7689（audit-report-by-resolving-cited-pointers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-upstream-delta-and-supersession-before-stale-base-gate-work-8bb7f0cd77d1（audit-upstream-delta-and-supersession-before-stale-base-gate-work，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:audit-warm-state-from-receipt-before-rediscovery-1e16e716d8fc（audit-warm-state-from-receipt-before-rediscovery，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:author-index-cards-point-to-maintained-sources-from-rendered-field-347d22998d9c（author-index-cards-point-to-maintained-sources-from-rendered-field，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authoritative-artifact-first-then-live-contract-probe-6867db304150（authoritative-artifact-first-then-live-contract-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authoritative-completion-before-reexecute-nonidempotent-action-a4c98eec8017（authoritative-completion-before-reexecute-nonidempotent-action，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authoritative-parser-first-for-record-statistics-ca68b260488d（authoritative-parser-first-for-record-statistics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authoritative-record-first-when-preview-truncated-0155675ee421（authoritative-record-first-when-preview-truncated，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authority-contract-before-managed-mutation-62e4436f179e（authority-contract-before-managed-mutation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:authority-gate-drift-map-before-lifecycle-plan-23f0e2d2ae69（authority-gate-drift-map-before-lifecycle-plan，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-28T08:53:05.220752+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:background-first-delegation-for-minutes-scale-subtasks-8dfe01ae386e（background-first-delegation-for-minutes-scale-subtasks，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bare-citation-anchor-not-path-guess-c0caae461a97（bare-citation-anchor-not-path-guess，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bare-id-state-reconcile-before-transition-retry-588019de930e（bare-id-state-reconcile-before-transition-retry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:base-commit-counterfactual-attribution-for-sandbox-gate-failures-bce9c5881a8f（base-commit-counterfactual-attribution-for-sandbox-gate-failures，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:batch-complete-required-fields-on-parameter-rejection-71b35b88bd44（batch-complete-required-fields-on-parameter-rejection，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:batch-triage-unmerged-branches-by-structural-partition-766a3a87953d（batch-triage-unmerged-branches-by-structural-partition，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:behavior-lock-tests-derive-fixtures-from-callee-body-guards-73499161b3db（behavior-lock-tests-derive-fixtures-from-callee-body-guards，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:behavioral-baseline-comparison-when-transport-telemetry-says-success-ec959912a876（behavioral-baseline-comparison-when-transport-telemetry-says-success，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:benign-shape-probe-mints-guard-receipt-then-literal-code-docs-721f96a39665（benign-shape-probe-mints-guard-receipt-then-literal-code-docs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:binary-intervention-sufficiency-gate-7631f80e335c（binary-intervention-sufficiency-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:binary-upgrade-risk-probe-hygiene-c0a63cb1a0fa（binary-upgrade-risk-probe-hygiene，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bind-gate-verdict-scope-to-true-delta-before-consuming-pass-f1449caafaf4（bind-gate-verdict-scope-to-true-delta-before-consuming-pass，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bind-next-action-params-to-receipt-template-29fa06caacb9（bind-next-action-params-to-receipt-template，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bind-tree-reading-gates-to-artifact-ref-worktree-ece00051f244（bind-tree-reading-gates-to-artifact-ref-worktree，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bind-ui-target-via-snapshot-structural-anchors-before-name-retries-or-pa-84e46791605c（bind-ui-target-via-snapshot-structural-anchors-before-name-retries-or-page-pivots，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7（binding-drift-preflight-before-gated-service-mutation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:binding-identity-gate-before-destructive-ops-9e1d9ef8f671（binding-identity-gate-before-destructive-ops，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:binding-verify-config-first-probe-86ba90942add（binding-verify-config-first-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:blind-judge-via-inlined-inputs-and-mechanical-zero-tool-verification-e604f428f826（blind-judge-via-inlined-inputs-and-mechanical-zero-tool-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:block-wait-gated-child-verdict-and-front-load-independent-prep-b5a824bf8b8f（block-wait-gated-child-verdict-and-front-load-independent-prep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bound-verification-output-to-survive-truncation-5879c1e4cca7（bound-verification-output-to-survive-truncation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:boundary-delta-audit-via-recorded-per-request-fingerprints-f42fb4c4e6c3（boundary-delta-audit-via-recorded-per-request-fingerprints，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:boundary-probe-runtime-claims-conflicting-with-code-defaults-d58bd93cebdd（boundary-probe-runtime-claims-conflicting-with-code-defaults，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-blocking-polls-honor-wait-and-cap-on-async-child-862e9ccee3bd（bounded-blocking-polls-honor-wait-and-cap-on-async-child，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-blocking-wait-over-busy-repoll-b706e228900c（bounded-blocking-wait-over-busy-repoll，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00（bounded-chunk-write-verify-for-long-file-artifacts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-probe-before-blocking-retry-e3e7b0a91b65（bounded-probe-before-blocking-retry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-retry-then-handoff-when-next-command-fully-determined-da0782bf009c（bounded-retry-then-handoff-when-next-command-fully-determined，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bounded-wait-probe-not-echo-f0cde4eefa61（bounded-wait-probe-not-echo，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bracket-full-gate-with-side-effect-restore-and-blob-reverify-a9016082bc6c（bracket-full-gate-with-side-effect-restore-and-blob-reverify，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:branch-on-failure-receipt-class-not-retry-ladders-b84477792d2c（branch-on-failure-receipt-class-not-retry-ladders，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:branch-scoped-push-binding-resolution-over-bare-git-push-probe-44e6d87bdce4（branch-scoped-push-binding-resolution-over-bare-git-push-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:break-stall-on-repeated-unresolved-mirror-47860ebcaa44（break-stall-on-repeated-unresolved-mirror，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:budget-named-gate-rejection-recover-accounting-then-split-verified-units-29dee38d72a8（budget-named-gate-rejection-recover-accounting-then-split-verified-units，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bulk-edit-from-displayed-literal-anchor-free-per-surface-verify-95849638b2f5（bulk-edit-from-displayed-literal-anchor-free-per-surface-verify，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:bypass-shell-guard-metachar-scan-via-placeholder-staging-944cb2a5ad72（bypass-shell-guard-metachar-scan-via-placeholder-staging，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:calibrate-paged-read-coordinates-from-first-response-3972af26dbdd（calibrate-paged-read-coordinates-from-first-response，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-1f35d0228ab0（沙箱能力失败先归因通道层：权限预检+替代通道探针再定进程方案，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-a80acb208b99（会话级知识层双向同步（开局检索·使用裁决·收尾结算），hold；usage 1 条 {'applied': 1}，最近 2026-10-14T08:06:19.348698+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `record_qualification` | （成员检查/人工项，无命令输出） | false |
| tool_existence | pass（断言成立，非证据） | 正文以反引号提及工具/命令 `save_experience` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `save_candidate` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-aa0d6b3be4d9（历史归因：先匹配时间范围与机制签名，再换检索来源，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-d04bd939ef69（本环境怎么搜（检索顺序与引用纪律），candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| tool_existence | pass（断言成立，非证据） | 正文以反引号提及工具/命令 `search_records` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `sched-ffe3746a` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `sched-2a53c151` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-d5fce462ff6b（本地视频模型短片交付流水线（编剧→导演→生成→后期→独立审查），candidate；usage 1 条 {'applied': 1}，最近 2026-10-26T19:41:36.059365+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:candidate-qualification-channel-pack-independent-review-verdict-writebac-bbe0ef1d21dc（candidate-qualification-channel-pack-independent-review-verdict-writeback，candidate；usage 2 条 {'adapted': 1, 'applied': 1}，最近 2026-10-30T10:53:16.460702+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 scripts/qualification/method_candidate_qualification.py 存在 | `test -e scripts/qualification/method_candidate_qualification.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/test_method_candidate_qualification_harness.py 存在 | `test -e tests/test_method_candidate_qualification_harness.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:canonical-outlink-before-search-or-slug-guess-5883a7cd9e59（canonical-outlink-before-search-or-slug-guess，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:canonical-source-fetch-first-escape-degraded-keyword-search-channel-2ab461cf54b2（canonical-source-fetch-first-escape-degraded-keyword-search-channel，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:canonical-source-first-when-paper-identifiers-known-fc63b2749443（canonical-source-first-when-paper-identifiers-known，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:canonical-vendor-url-first-for-fact-verification-b5ad79cf8413（canonical-vendor-url-first-for-fact-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cap-delegated-child-input-by-contract-not-segment-size-76fd07467873（cap-delegated-child-input-by-contract-not-segment-size，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capability-catalog-first-for-existence-claims-671f3cfe5de8（capability-catalog-first-for-existence-claims，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capability-oracle-is-the-real-operation-not-the-permission-bit-616a2c522aae（capability-oracle-is-the-real-operation-not-the-permission-bit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capability-precheck-before-control-verbs-e457317541c2（capability-precheck-before-control-verbs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capability-surface-vs-callsite-diff-fdc1f150874a（capability-surface-vs-callsite-diff，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capability-verdict-registry-schema-firstparty-scope-7f028740bd57（capability-verdict-registry-schema-firstparty-scope，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:capped-view-receipt-retarget-span-or-advance-on-visible-anchor-2682e5752b1c（capped-view-receipt-retarget-span-or-advance-on-visible-anchor，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cas-zero-current-conflict-means-store-path-mismatch-9e82e969dbdb（cas-zero-current-conflict-means-store-path-mismatch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cat-heredoc-static-write-downgrade-on-interpreter-heredoc-hardblock-18d17f5a594d（cat-heredoc-static-write-downgrade-on-interpreter-heredoc-hardblock，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:catchall-unavailable-label-read-child-terminal-output-then-budget-arithm-23d844e1b280（catchall-unavailable-label-read-child-terminal-output-then-budget-arithmetic，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:census-authoritative-store-before-citing-registry-stats-cc832842dcbc（census-authoritative-store-before-citing-registry-stats，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:chain-write-receipt-ref-for-same-file-edits-f8272f8a4618（chain-write-receipt-ref-for-same-file-edits，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:chained-timeout-stage-triage-then-authoritative-fallback-0377f5544852（chained-timeout-stage-triage-then-authoritative-fallback，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:char-offset-bisect-hydration-on-truncated-singleline-json-receipt-2446d8264426（char-offset-bisect-hydration-on-truncated-singleline-json-receipt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cheapest-falsifier-per-claim-before-design-freeze-1c77a2b54393（cheapest-falsifier-per-claim-before-design-freeze，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-completion-gate-before-polling-detached-action-13436a62132d（check-completion-gate-before-polling-detached-action，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-desired-head-binding-before-restart-choose-update-2e3637e8aef7（check-desired-head-binding-before-restart-choose-update，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-13T02:00:11.035615+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-focus-activation-before-blaming-synthetic-input-method-f97ddba62e8b（check-focus-activation-before-blaming-synthetic-input-method，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-gate-preconditions-before-dispatch-announce-only-after-receipt-40cb7836dbc7（check-gate-preconditions-before-dispatch-announce-only-after-receipt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-prior-rejection-receipt-before-explaining-or-retrying-61e708c56bfa（check-prior-rejection-receipt-before-explaining-or-retrying，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `llm_loop` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-process-ancestry-before-self-hosted-restart-dcb6384374dc（check-process-ancestry-before-self-hosted-restart，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-receipt-declared-coverage-before-refetch-0515f46044e5（check-receipt-declared-coverage-before-refetch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-rule-precondition-before-gated-completion-f26936021525（check-rule-precondition-before-gated-completion，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-two-way-version-divergence-before-restart-activation-93287eb2884a（check-two-way-version-divergence-before-restart-activation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:check-unknown-version-delta-before-mechanism-tracing-f82bbba9d65b（check-unknown-version-delta-before-mechanism-tracing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:checkpoint-at-green-when-workspace-shows-external-writers-b1c19f52c02d（checkpoint-at-green-when-workspace-shows-external-writers，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/core/tool_execution_journal.py 存在 | `test -e src/llm_loop/core/tool_execution_journal.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:child-id-c0edbb4e93c1（审查回执命名必须嵌入 child_id 防覆盖，active；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 docs/promotion/receipts/20261018-daily18-publish.json 存在 | `test -e docs/promotion/receipts/20261018-daily18-publish.json` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 docs/promotion/receipts/20261018-daily18-toutiao-local.json 存在 | `test -e docs/promotion/receipts/20261018-daily18-toutiao-local.json` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/promotion/receipts 存在 | `test -e docs/promotion/receipts` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:child-progress-from-settlement-receipt-not-stream-probes-3aa795a04639（child-progress-from-settlement-receipt-not-stream-probes，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-23T05:18:12.088618+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:child-scope-observation-and-receipt-defined-blocking-wait-0a165af93052（child-scope-observation-and-receipt-defined-blocking-wait，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:chromeless-capture-attribute-session-layer-via-control-app-0e8d34da0d08（chromeless-capture-attribute-session-layer-via-control-app，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ci-failure-log-first-when-failing-run-matches-local-head-ad031a0d7dae（ci-failure-log-first-when-failing-run-matches-local-head，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ci-push-failure-attribution-via-ref-tip-timestamp-and-exact-sha-repro-d6f6eb7d49b9（ci-push-failure-attribution-via-ref-tip-timestamp-and-exact-sha-repro，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:citation-id-lookup-before-fuzzy-web-rediscovery-038657a70874（citation-id-lookup-before-fuzzy-web-rediscovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:citation-path-resolution-exact-search-before-guess-50770b6534eb（citation-path-resolution-exact-search-before-guess，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-audit-resolve-embedded-record-pointers-directly-e1cbfa1977d0（claim-audit-resolve-embedded-record-pointers-directly，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-by-claim-authoritative-state-audit-6785f55f3b95（claim-by-claim-authoritative-state-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-diff-via-cited-primary-sources-before-generic-search-51bb939cc295（claim-diff-via-cited-primary-sources-before-generic-search，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-20T11:37:54.539783+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-literal-anchored-two-sided-verification-337b9ae43101（claim-literal-anchored-two-sided-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-provenance-receipt-binding-a3085fab0abc（claim-provenance-receipt-binding，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-to-artifact-verification-before-broad-forensics-aa4b58adf096（claim-to-artifact-verification-before-broad-forensics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:claim-to-receipt-reconcile-via-mtime-and-per-claim-grep-0a5adf76eb6d（claim-to-receipt-reconcile-via-mtime-and-per-claim-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-batch-cherrypick-stops-empty-vs-conflict-verify-by-stat-06f486a790e9（classify-batch-cherrypick-stops-empty-vs-conflict-verify-by-stat，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-cancelled-child-mutations-from-receipt-trace-before-redispatch-b5fb4ae4209e（classify-cancelled-child-mutations-from-receipt-trace-before-redispatch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-child-run-failure-then-resegment-delegated-scope-6b0c4093fef1（classify-child-run-failure-then-resegment-delegated-scope，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-dep-missing-errors-by-interpreter-differential-probe-28934bce0162（classify-dep-missing-errors-by-interpreter-differential-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-errno-write-denial-as-environment-before-code-triage-32e51ee0e266（classify-errno-write-denial-as-environment-before-code-triage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-error-string-origin-before-source-grep-c8eda09a9111（classify-error-string-origin-before-source-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-failure-stage-from-output-before-adopting-correction-remedy-aad732109179（classify-failure-stage-from-output-before-adopting-correction-remedy，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-flaky-vs-regression-before-widening-timing-margins-beb005793c65（classify-flaky-vs-regression-before-widening-timing-margins，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-key-roles-and-collision-test-before-precedence-fix-53e3ecb25e5d（classify-key-roles-and-collision-test-before-precedence-fix，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-named-gate-rejection-structural-vs-addressable-before-retry-ebdecbb3cd6a（classify-named-gate-rejection-structural-vs-addressable-before-retry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-named-sha-vs-fetched-main-then-partition-port-ef40148b4bf9（classify-named-sha-vs-fetched-main-then-partition-port，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-once-then-fallback-on-tool-timeout-85db740be139（classify-once-then-fallback-on-tool-timeout，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-pinned-gate-intent-before-semantics-edit-a2b25e5bc0c2（classify-pinned-gate-intent-before-semantics-edit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-prior-error-staleness-vs-verification-via-baseline-delta-6a917efcdb10（classify-prior-error-staleness-vs-verification-via-baseline-delta，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-receipt-vs-findings-report-recover-via-producer-transcript-2dce871101f6（classify-receipt-vs-findings-report-recover-via-producer-transcript，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-store-manifest-and-assert-coverage-before-scanning-05a1e53133d7（classify-store-manifest-and-assert-coverage-before-scanning，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-unique-content-before-destructive-cleanup-f2d371d616d7（classify-unique-content-before-destructive-cleanup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:classify-unknowns-before-discovery-dont-rederive-in-hand-frame-4d24ca86764c（classify-unknowns-before-discovery-dont-rederive-in-hand-frame，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:clean-process-differential-before-live-chain-audit-12542dbbcabe（clean-process-differential-before-live-chain-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:clean-tree-per-gate-boundary-under-concurrent-writers-bfda48ecb3bd（clean-tree-per-gate-boundary-under-concurrent-writers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:clean-tree-plus-receipt-implies-committed-adjudicate-before-redo-9c0e77e4702a（clean-tree-plus-receipt-implies-committed-adjudicate-before-redo，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:clone-first-for-bulk-repo-ingestion-63c81319e94c（clone-first-for-bulk-repo-ingestion，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-channel-on-deterministic-self-describing-failure-36bd486e20c1（close-channel-on-deterministic-self-describing-failure，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-full-defect-list-before-recheck-b05eaa027921（close-full-defect-list-before-recheck，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-named-loose-ends-via-owning-guard-first-9684842ebd1a（close-named-loose-ends-via-owning-guard-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-on-proven-content-equivalence-and-split-blocked-identity-70bfd78c6e13（close-on-proven-content-equivalence-and-split-blocked-identity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-receipt-prescribed-verification-before-gated-actions-459644e802f8（close-receipt-prescribed-verification-before-gated-actions，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:close-truncated-assertion-diff-via-held-receipts-not-bespoke-import-harn-2a59d9bf9897（close-truncated-assertion-diff-via-held-receipts-not-bespoke-import-harness，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:closed-checklist-from-grep-before-constant-migration-4e8579ec9715（closed-checklist-from-grep-before-constant-migration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:closure-declaration-plus-route-definition-for-absence-questions-764ba82a2c3a（closure-declaration-plus-route-definition-for-absence-questions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cluster-and-attribute-uncommitted-delta-before-tree-wide-gate-e9f243b3ad03（cluster-and-attribute-uncommitted-delta-before-tree-wide-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:code-nav-reuse-confirmed-paths-1e7e58c0f083（code-nav-reuse-confirmed-paths，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:collapse-mirror-polluted-search-onto-live-tree-paths-54e0423a4a5b（collapse-mirror-polluted-search-onto-live-tree-paths，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:collect-turn-bound-child-before-turn-end-0ccce4ae9927（collect-turn-bound-child-before-turn-end，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:commit-provenance-before-pattern-guessing-83624ca57d8d（commit-provenance-before-pattern-guessing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:complete-failure-inventory-before-root-cause-ce230cde7fa6（complete-failure-inventory-before-root-cause，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:complete-range-hydration-before-durable-transcription-1e8c784264df（complete-range-hydration-before-durable-transcription，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:complete-truncated-record-via-id-then-read-embedded-anchors-69deb757880b（complete-truncated-record-via-id-then-read-embedded-anchors，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:complete-verdict-conjuncts-cross-source-then-stop-polling-ff69d5578759（complete-verdict-conjuncts-cross-source-then-stop-polling，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:completed-goal-followup-via-goal-artifact-index-and-commit-ledger-710964863eab（completed-goal-followup-via-goal-artifact-index-and-commit-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:completion-status-via-running-line-provenance-3f8b365d9793（completion-status-via-running-line-provenance，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:component-default-lookup-via-source-constant-chain-fc7cc626c012（component-default-lookup-via-source-constant-chain，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:compound-timeout-bounded-local-probe-first-8a88098e84bd（compound-timeout-bounded-local-probe-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:compute-per-edge-clearance-from-generator-geometry-before-scalar-retune-79c94bf29cad（compute-per-edge-clearance-from-generator-geometry-before-scalar-retune，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:concurrent-writer-divergence-pin-verified-commit-not-contested-tree-7a43dab46eeb（concurrent-writer-divergence-pin-verified-commit-not-contested-tree，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:concurrent-writer-immune-certification-f4ee4b85ffbc（concurrent-writer-immune-certification，candidate；usage 2 条 {'applied': 2}，最近 2026-10-30T11:50:26.136183+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:config-audit-trilogy-closure-279f2f545da4（config-audit-trilogy-closure，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:config-mismatch-resolution-chain-before-repo-search-e57b1fdeb8f9（config-mismatch-resolution-chain-before-repo-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:config-switch-triage-via-effective-chain-d270de3a5f73（config-switch-triage-via-effective-chain，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:config-why-via-referenced-design-doc-plus-code-default-29dd04a03941（config-why-via-referenced-design-doc-plus-code-default，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:confirm-flow-completion-is-not-success-readback-action-ledger-4685afc76f85（confirm-flow-completion-is-not-success-readback-action-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:connect-then-drop-correlate-session-type-with-capture-log-a9bd53cdf7a1（connect-then-drop-correlate-session-type-with-capture-log，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:connection-refused-resolve-actual-port-via-pid-socket-table-a77a0862065a（connection-refused-resolve-actual-port-via-pid-socket-table，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consult-artifact-repair-history-before-reproposing-change-20f25d77c4e0（consult-artifact-repair-history-before-reproposing-change，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consult-human-disposition-register-before-mechanical-batch-delete-e2d999fc935d（consult-human-disposition-register-before-mechanical-batch-delete，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/governance 存在 | `test -e docs/governance` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consume-authoritative-hits-before-parallel-discovery-f28827831140（consume-authoritative-hits-before-parallel-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consume-failure-scope-before-broad-fetch-f6c25a77e480（consume-failure-scope-before-broad-fetch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consume-miss-receipt-index-before-broad-enumeration-2956cfd5c488（consume-miss-receipt-index-before-broad-enumeration，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/records 存在 | `test -e docs/records` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consume-miss-suggestions-before-requery-or-broad-sweep-67621e7ad7ab（consume-miss-suggestions-before-requery-or-broad-sweep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:consumer-blast-radius-by-causal-token-not-rendered-string-cb9589eabf22（consumer-blast-radius-by-causal-token-not-rendered-string，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 scripts/ci_gate.sh 存在 | `test -e scripts/ci_gate.sh` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:content-anchor-scan-then-request-locator-579a415b0406（content-anchor-scan-then-request-locator，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:content-digest-equivalence-over-identity-reproduction-e1ad1f052b50（content-digest-equivalence-over-identity-reproduction，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:content-supersession-accounting-before-destructive-stash-drop-01e0a9517c49（content-supersession-accounting-before-destructive-stash-drop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:content-targeted-lookup-in-identified-container-e43f6719d939（content-targeted-lookup-in-identified-container，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:continuation-opens-cited-design-doc-before-corpus-search-15d915f867fd（continuation-opens-cited-design-doc-before-corpus-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:continue-subject-matched-truncated-read-before-lateral-evidence-sampling-7444afc88878（continue-subject-matched-truncated-read-before-lateral-evidence-sampling，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:continue-truncated-receipt-via-range-pointer-or-blob-identity-c99bd6d36f11（continue-truncated-receipt-via-range-pointer-or-blob-identity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:contract-check-before-automation-channel-switch-4149c372219c（contract-check-before-automation-channel-switch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:contract-misreading-repair-align-official-evidence-protect-frozen-surfac-9071ef2074eb（contract-misreading-repair-align-official-evidence-protect-frozen-surfaces，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 src/tests/fixtures 存在 | `test -e src/tests/fixtures` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:contract-preflight-before-gated-exec-and-layer-matched-fallback-c46df4d99bfb（contract-preflight-before-gated-exec-and-layer-matched-fallback，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:control-plane-record-before-broad-probe-3fccf9490882（control-plane-record-before-broad-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:convention-named-tool-failfast-error-names-deps-abd3e3c1ab7d（convention-named-tool-failfast-error-names-deps，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:convention-path-probe-before-broad-find-in-mirror-snapshot-repos-581d7fcd7f0c（convention-path-probe-before-broad-find-in-mirror-snapshot-repos，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/promotion 存在 | `test -e docs/promotion` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:converge-restart-scope-to-desired-binding-71d6275727ce（converge-restart-scope-to-desired-binding，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:converged-spec-literal-anchors-delimit-touch-surface-59f37d7da6fc（converged-spec-literal-anchors-delimit-touch-surface，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:convergent-action-on-visible-head-not-history-paging-fc60d9e36ae3（convergent-action-on-visible-head-not-history-paging，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:conversion-fidelity-via-same-source-text-baseline-b057c777d3cc（conversion-fidelity-via-same-source-text-baseline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:copy-observed-identifier-verbatim-and-diff-on-path-miss-42045cf8b965（copy-observed-identifier-verbatim-and-diff-on-path-miss，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/DESIGN-20261009-plugin-ecosystem-integration.md 存在 | `test -e docs/DESIGN-20261009-plugin-ecosystem-integration.md` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:count-closure-reconcile-and-fresh-check-before-accepting-gate-claims-ee8ea5d95b27（count-closure-reconcile-and-fresh-check-before-accepting-gate-claims，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:coverage-audit-then-net-delta-persist-31140201928e（coverage-audit-then-net-delta-persist，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:coverage-diff-then-persist-net-increment-61723f64dc5f（coverage-diff-then-persist-net-increment，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:crash-resume-ledger-tail-reconcile-and-child-terminal-audit-e37ce4248223（crash-resume-ledger-tail-reconcile-and-child-terminal-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:criteria-coverage-gap-audit-and-post-change-topology-dedup-7c0be2018a64（criteria-coverage-gap-audit-and-post-change-topology-dedup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:criterion-direction-check-via-insource-known-label-examples-887bb093553a（criterion-direction-check-via-insource-known-label-examples，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-axis-liveness-verify-before-peer-takeover-7cbabce569a8（cross-axis-liveness-verify-before-peer-takeover，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-merge-test-failure-fixture-vs-new-gate-951e932c8902（cross-merge-test-failure-fixture-vs-new-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-platform-republish-from-frozen-master-per-newest-receipt-contract-adc68f36932a（cross-platform-republish-from-frozen-master-per-newest-receipt-contract，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-receipt-contradiction-pivot-when-search-returns-no-match-d7022c44200f（cross-receipt-contradiction-pivot-when-search-returns-no-match，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-round-facts-verify-at-persistent-authority-7cf79924a62c（cross-round-facts-verify-at-persistent-authority，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-secret-inventory-with-file-routes-first-in-security-review-75c5860c1f57（cross-secret-inventory-with-file-routes-first-in-security-review，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cross-tab-category-x-truncation-before-quoting-aggregate-rate-3bbf627d308f（cross-tab-category-x-truncation-before-quoting-aggregate-rate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:current-state-from-live-authority-not-history-paging-989ce02cadb5（current-state-from-live-authority-not-history-paging，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:current-state-snapshot-first-per-service-restart-effect-verdict-8418f9c7749d（current-state-snapshot-first-per-service-restart-effect-verdict，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| tool_existence | pass（断言成立，非证据） | 正文以反引号提及工具/命令 `service_control` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:cwd-self-report-before-assumed-workspace-path-581b31a62204（cwd-self-report-before-assumed-workspace-path，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:daemon-class-service-restart-use-managed-background-start-e52557730673（daemon-class-service-restart-use-managed-background-start，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:daemon-cpu-input-workload-correlation-before-producer-hunt-5942367b0347（daemon-cpu-input-workload-correlation-before-producer-hunt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:daemon-log-stage-triage-baa9e20016ae（daemon-log-stage-triage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dead-param-liveness-adjudicate-per-forward-edge-to-terminal-consumer-a40d4b25e1eb（dead-param-liveness-adjudicate-per-forward-edge-to-terminal-consumer，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dead-port-owner-via-tunnel-pairing-and-proxy-ppid-e5ccf36660b5（dead-port-owner-via-tunnel-pairing-and-proxy-ppid，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decide-on-findings-from-original-receipt-not-self-paraphrase-53bc4b86b1f4（decide-on-findings-from-original-receipt-not-self-paraphrase，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decisive-gate-probe-over-channel-enumeration-51b54c35c8ad（decisive-gate-probe-over-channel-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:declaration-dispatch-mismatch-stop-loss-handoff-f2bfcd7bdb57（declaration-dispatch-mismatch-stop-loss-handoff，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:declaration-receipt-audit-as-status-authority-for-vague-past-work-querie-e378cc4d948a（declaration-receipt-audit-as-status-authority-for-vague-past-work-queries，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decode-validator-rejection-into-single-structural-repair-b63129f3e4bd（decode-validator-rejection-into-single-structural-repair，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decompose-aggregate-metric-to-source-entries-227204de7b9a（decompose-aggregate-metric-to-source-entries，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decompose-question-to-named-keywords-then-range-hydrate-30e8f455ddcc（decompose-question-to-named-keywords-then-range-hydrate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decompose-round-burn-by-outcome-before-attribution-bfbbda673001（decompose-round-burn-by-outcome-before-attribution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:decompose-stale-version-string-before-deploy-forensics-98b6b67b0224（decompose-stale-version-string-before-deploy-forensics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dedup-key-collapsibility-check-before-trusting-group-counts-996a2953f0cc（dedup-key-collapsibility-check-before-trusting-group-counts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dedupe-artifact-reads-against-in-context-coverage-pointers-0082d7e2b12a（dedupe-artifact-reads-against-in-context-coverage-pointers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:defer-async-action-verification-via-single-wakeup-6b488fda4817（defer-async-action-verification-via-single-wakeup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:defer-shared-store-schema-migration-until-old-writer-exit-d438adc4236f（defer-shared-store-schema-migration-until-old-writer-exit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deferred-action-failure-layer-scoped-lifecycle-trace-8d89b644a17d（deferred-action-failure-layer-scoped-lifecycle-trace，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit/test_schedule_restart_recovery.py 存在 | `test -e tests/unit/test_schedule_restart_recovery.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/core/loop/engine.py 存在 | `test -e src/llm_loop/core/loop/engine.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/core/schedule_delivery.py 存在 | `test -e src/llm_loop/core/schedule_delivery.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/introspection/status.py 存在 | `test -e src/llm_loop/introspection/status.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/factory.py 存在 | `test -e src/llm_loop/factory.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b（deferred-action-failure-layer-scoped-lifecycle-trace，candidate；usage 1 条 {'applied': 1}，最近 2026-10-07T21:19:37.941489+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deferred-wakeup-verify-async-action-terminal-states-e9c597e4c1e4（deferred-wakeup-verify-async-action-terminal-states，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:definitive-failure-swap-source-not-restart-discovery-5abed48afb10（definitive-failure-swap-source-not-restart-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:definitive-negative-on-named-artifact-pivot-to-workline-root-8ca160398394（definitive-negative-on-named-artifact-pivot-to-workline-root，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:definitive-negative-receipt-closes-fallback-branch-c1fe458f6e76（definitive-negative-receipt-closes-fallback-branch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:definitive-path-failure-resolve-env-anchor-before-discovery-5d232889e078（definitive-path-failure-resolve-env-anchor-before-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:degenerate-search-pivot-to-canonical-artifact-grep-8ba478947434（degenerate-search-pivot-to-canonical-artifact-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:degraded-search-fallback-unverified-not-absent-e7fa27de3105（degraded-search-fallback-unverified-not-absent，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:delegated-subagent-discipline-in-task-text-not-tool-description-77076544d5a7（delegated-subagent-discipline-in-task-text-not-tool-description，candidate；usage 3 条 {'applied': 3}，最近 2026-10-16T09:37:05.298661+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deletion-audit-scope-live-tree-and-bypass-exclusivity-b0979e7f27b1（deletion-audit-scope-live-tree-and-bypass-exclusivity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:denial-signature-records-first-b749e7b81591（denial-signature-records-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deploy-acceptance-follow-change-identity-b334d83e67f1（deploy-acceptance-follow-change-identity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deploy-hook-runs-as-pusher-gate-on-served-artifact-44ae02621429（deploy-hook-runs-as-pusher-gate-on-served-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deploy-mismatch-resolve-commit-containment-before-host-or-record-searche-a2e219155c2a（deploy-mismatch-resolve-commit-containment-before-host-or-record-searches，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deployment-receipt-hub-for-restart-scope-and-effect-412788eabba1（deployment-receipt-hub-for-restart-scope-and-effect，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-command-target-path-from-episode-receipts-not-recalled-memory-5abe4e517a0d（derive-command-target-path-from-episode-receipts-not-recalled-memory，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558（derive-delivery-gates-from-repo-history-preverify-locally，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-direct-run-from-wrapper-source-9d61b63a698c（derive-direct-run-from-wrapper-source，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-endpoint-from-live-pid-before-probe-64db93a2fd0f（derive-endpoint-from-live-pid-before-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-gate-passability-from-source-before-first-run-2e3ce81ea1d9（derive-gate-passability-from-source-before-first-run，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-lookup-keys-from-observed-namespace-32cb8eb52723（derive-lookup-keys-from-observed-namespace，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-merge-verification-scope-from-tracked-diff-not-workdir-ls-ede9912c11ee（derive-merge-verification-scope-from-tracked-diff-not-workdir-ls，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-validator-contract-from-pinned-source-dd2083babf34（derive-validator-contract-from-pinned-source，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-verification-probes-from-colocated-change-record-30a94c9bddc3（derive-verification-probes-from-colocated-change-record，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:derive-wire-probe-paths-from-source-routes-and-verify-version-by-differe-8d66cdf25ea4（derive-wire-probe-paths-from-source-routes-and-verify-version-by-differential，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:designed-suppression-is-capability-gap-enumerate-gates-not-ungate-ce4a2c5e5e25（designed-suppression-is-capability-gap-enumerate-gates-not-ungate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:destructive-replay-failure-shift-work-into-stable-paste-payload-67917b175573（destructive-replay-failure-shift-work-into-stable-paste-payload，candidate；usage 1 条 {'applied': 1}，最近 2026-10-18T22:51:51.489591+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:detach-never-exiting-helpers-then-inline-probe-f5b9e5bd9255（detach-never-exiting-helpers-then-inline-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:deterministic-404-is-an-answer-pivot-to-canonical-candidate-daaa7d2b6d35（deterministic-404-is-an-answer-pivot-to-canonical-candidate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diagnose-failed-managed-action-via-id-keyed-record-not-snapshot-paging-1648d9a77e6f（diagnose-failed-managed-action-via-id-keyed-record-not-snapshot-paging，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diagnose-known-failing-tests-via-node-scoped-max-tb-rerun-25ece289a3f8（diagnose-known-failing-tests-via-node-scoped-max-tb-rerun，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit 存在 | `test -e tests/unit` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diff-gate-view-transform-before-resubmit-iteration-8e6916dec3c1（diff-gate-view-transform-before-resubmit-iteration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diff-named-closed-set-vs-classifier-branches-bfbd0238fca8（diff-named-closed-set-vs-classifier-branches，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diff-named-invalid-class-against-cited-spec-before-external-docs-d742a315aef9（diff-named-invalid-class-against-cited-spec-before-external-docs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diff-normalization-parity-probe-before-wiring-13850e612a58（diff-normalization-parity-probe-before-wiring，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:diff-partition-revision-rereview-ff8f3977837d（diff-partition-revision-rereview，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:disambiguate-named-entities-via-config-layers-before-answering-why-6e5b9cc171c3（disambiguate-named-entities-via-config-layers-before-answering-why，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:disambiguate-ref-correction-by-ancestry-and-blob-before-destructive-reba-418f6c654ba1（disambiguate-ref-correction-by-ancestry-and-blob-before-destructive-rebase，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:disambiguate-remote-404-by-parent-level-check-a37a153974db（disambiguate-remote-404-by-parent-level-check，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:disambiguate-term-against-deployment-topology-before-refix-e497872af535（disambiguate-term-against-deployment-topology-before-refix，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dissolve-regression-premise-via-history-existence-proof-78b1810f5e3d（dissolve-regression-premise-via-history-existence-proof，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:distinctive-token-first-code-search-c441ab967524（distinctive-token-first-code-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:distinctive-token-retry-after-conjunctive-miss-before-generic-enumeratio-a68e99abaf4e（distinctive-token-retry-after-conjunctive-miss-before-generic-enumeration，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 evals/methodcard_rsi_v1 存在 | `test -e evals/methodcard_rsi_v1` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:divergence-probe-temp0-executor-before-repeat-budget-12583e4679b1（divergence-probe-temp0-executor-before-repeat-budget，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:doc-sync-from-authoritative-implementation-3a45e2d43d70（doc-sync-from-authoritative-implementation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:doc-tree-capability-fork-for-platform-integration-research-027e38746f1a（doc-tree-capability-fork-for-platform-integration-research，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:documented-availability-limits-and-logs-before-config-archaeology-ad25f7196c99（documented-availability-limits-and-logs-before-config-archaeology，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dominant-reason-literal-to-emission-site-94d0631e6859（dominant-reason-literal-to-emission-site，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:drain-known-pagination-then-verify-checklist-89364875a12e（drain-known-pagination-then-verify-checklist，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:drilldown-via-named-source-kind-before-keyword-search-7cee909454b4（drilldown-via-named-source-kind-before-keyword-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dry-run-deterministic-arm-and-ceiling-probe-before-pairwise-run-ccc1716a10a4（dry-run-deterministic-arm-and-ceiling-probe-before-pairwise-run，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dry-run-gated-command-before-spending-human-approval-4e0fe61b61cf（dry-run-gated-command-before-spending-human-approval，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dual-id-reconcile-then-replay-captured-delete-endpoint-b2713a6499ba（dual-id-reconcile-then-replay-captured-delete-endpoint，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dump-exact-identifier-on-grounded-target-match-failure-72ab37ee7540（dump-exact-identifier-on-grounded-target-match-failure，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dump-one-full-record-before-log-extraction-scripts-351eec511bcf（dump-one-full-record-before-log-extraction-scripts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:dup-forensics-volatile-field-identity-plus-copy-lineage-2e19786207b7（dup-forensics-volatile-field-identity-plus-copy-lineage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:durable-job-defer-terminal-check-2a5ca0503c58（durable-job-defer-terminal-check，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:durable-trigger-evidence-gated-closure-for-rules-166bc0e935eb（durable-trigger-evidence-gated-closure-for-rules，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:edge-530-zero-traffic-resolve-hostname-tunnel-binding-via-control-plane-9296e6433628（edge-530-zero-traffic-resolve-hostname-tunnel-binding-via-control-plane，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:edge-error-first-tunnel-split-brain-diagnosis-944a40a37ffb（edge-error-first-tunnel-split-brain-diagnosis，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:edit-rejection-routes-write-modality-7d6abd8c6b50（edit-rejection-routes-write-modality，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:editable-restart-deploys-worktree-escalate-uncommitted-riders-c831e0694bd8（editable-restart-deploys-worktree-escalate-uncommitted-riders，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:editor-framework-signature-before-event-paste-iteration-71d7a8d9286a（editor-framework-signature-before-event-paste-iteration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:editor-input-channel-probe-before-bulk-write-a567dad632cf（editor-input-channel-probe-before-bulk-write，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:editor-model-authority-real-input-and-counter-invariants-7d9725013091（editor-model-authority-real-input-and-counter-invariants，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-18T22:51:51.573402+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:effect-state-over-ok-receipt-escalate-user-owned-causes-751c11d89228（effect-state-over-ok-receipt-escalate-user-owned-causes，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:effective-config-composition-before-version-attribution-7dcc17b75d47（effective-config-composition-before-version-attribution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:embed-reading-contract-in-composited-visual-qa-images-1504ed2361b8（embed-reading-contract-in-composited-visual-qa-images，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:emission-level-gate-before-log-absence-evidence-1ca78b9733ac（emission-level-gate-before-log-absence-evidence，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:emit-action-not-declaration-loop-breaker-6e0f345923d7（emit-action-not-declaration-loop-breaker，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:emit-pending-action-over-meta-declaration-loop-9c40e9e8063d（emit-pending-action-over-meta-declaration-loop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:empty-aggregation-zeroing-known-population-pin-addressing-scheme-80f527260411（empty-aggregation-zeroing-known-population-pin-addressing-scheme，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:empty-field-root-cause-at-schema-defining-instruction-770801887e3e（empty-field-root-cause-at-schema-defining-instruction，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:empty-git-pathspec-widen-ref-scope-before-repo-hop-16dad9f1e81f（empty-git-pathspec-widen-ref-scope-before-repo-hop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:empty-hit-with-enumeration-is-terminal-ca0a068ea465（empty-hit-with-enumeration-is-terminal，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:endpoint-blocked-pivot-to-identity-pinned-artifact-ec9fe655b7e9（endpoint-blocked-pivot-to-identity-pinned-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:entry-artifact-chain-before-corpus-keyword-search-81c999876daf（entry-artifact-chain-before-corpus-keyword-search，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/INDEX 存在 | `test -e docs/INDEX` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-anchor-consumers-before-changing-anchor-locked-artifact-a5f4dcaae305（enumerate-anchor-consumers-before-changing-anchor-locked-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-complete-inventory-before-scoped-bulk-action-f3854ca9176c（enumerate-complete-inventory-before-scoped-bulk-action，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-mandate-coupling-sites-before-weakening-sot-rule-782b1b4bf860（enumerate-mandate-coupling-sites-before-weakening-sot-rule，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit/test_ai_rules_sync.py 存在 | `test -e tests/unit/test_ai_rules_sync.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-refs-same-path-before-reviewing-untracked-copy-b7ca5ef613f9（enumerate-refs-same-path-before-reviewing-untracked-copy，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-store-before-emptiness-claim-4233c442bff2（enumerate-store-before-emptiness-claim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:enumerate-task-surface-via-matching-commit-stat-before-path-guessing-660835bf0587（enumerate-task-surface-via-matching-commit-stat-before-path-guessing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:env-blocked-symptom-audit-api-owner-source-for-fallback-gaps-27fc61125e4f（env-blocked-symptom-audit-api-owner-source-for-fallback-gaps，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:env-red-attribution-via-pristine-baseline-control-then-bounded-handoff-df91239e9e92（env-red-attribution-via-pristine-baseline-control-then-bounded-handoff，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:env-self-query-before-guess-enumeration-a98f32371d18（env-self-query-before-guess-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:envelope-guided-tail-jump-on-truncated-snapshots-9ce1414e7617（envelope-guided-tail-jump-on-truncated-snapshots，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:epoch-scoped-evidence-before-liveness-claim-fd41ce1aa61b（epoch-scoped-evidence-before-liveness-claim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:error-credential-fingerprint-mismatch-stale-process-snapshot-630dbdca290f（error-credential-fingerprint-mismatch-stale-process-snapshot，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:error-digest-literal-into-runtime-session-store-then-live-policy-code-9293972283b3（error-digest-literal-into-runtime-session-store-then-live-policy-code，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:error-self-provenance-attribution-before-config-blame-111060210cd9（error-self-provenance-attribution-before-config-blame，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:escalate-hydration-range-on-first-truncation-before-fanning-out-1ab55636440b（escalate-hydration-range-on-first-truncation-before-fanning-out，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:escaped-name-verbatim-enumeration-before-exact-read-d876e624f1d3（escaped-name-verbatim-enumeration-before-exact-read，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:establish-actor-authority-before-remediation-path-17da98049b61（establish-actor-authority-before-remediation-path，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:eval-store-isolation-at-binding-point-with-write-canary-08a376c4a22f（eval-store-isolation-at-binding-point-with-write-canary，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:event-source-before-proxy-sweep-2ac5da147bd6（event-source-before-proxy-sweep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:event-stream-first-for-runtime-emitted-verdict-tokens-cac4ae68dcc7（event-stream-first-for-runtime-emitted-verdict-tokens，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:evidence-index-direct-hydration-on-ref-rejection-ab5570e5e33a（evidence-index-direct-hydration-on-ref-rejection，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-canonical-id-lookup-key-not-keyword-mashup-4b96fc6a2b01（exact-canonical-id-lookup-key-not-keyword-mashup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-id-hydrate-from-backing-store-on-truncated-hit-ca65ffc3114e（exact-id-hydrate-from-backing-store-on-truncated-hit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-id-locate-store-backing-file-by-scoped-find-not-wide-grep-7b1f386ab61c（exact-id-locate-store-backing-file-by-scoped-find-not-wide-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-id-lookup-in-system-of-record-before-semantic-search-c6a94d4ae9ad（exact-id-lookup-in-system-of-record-before-semantic-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-id-miss-then-read-state-ledger-f3b36ead67dd（exact-id-miss-then-read-state-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-identifier-first-search-with-subsystem-split-b2d923262868（exact-identifier-first-search-with-subsystem-split，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 src/transport 存在 | `test -e src/transport` → `exit=1` | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `stable_prefix` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `stable_prefix_fp` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-identifier-registry-lookup-before-keyword-enumeration-27394ce12058（exact-identifier-registry-lookup-before-keyword-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-identifier-then-namespace-verification-ceabd1d5ad03（exact-identifier-then-namespace-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-identity-pairing-for-event-ledger-correlation-b5ee30161d5b（exact-identity-pairing-for-event-ledger-correlation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-key-miss-switch-addressing-not-rewording-ddbdc01e5361（exact-key-miss-switch-addressing-not-rewording，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-path-only-discovery-resolve-store-naming-scheme-escalate-on-opaque-da02954b84a1（exact-path-only-discovery-resolve-store-naming-scheme-escalate-on-opaque-ids，active；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/INDEX.md 存在 | `test -e docs/INDEX.md` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/event_log/store.py 存在 | `test -e src/llm_loop/event_log/store.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-ref-first-lookup-when-artifact-declares-canonical-ids-f3ee251bab11（exact-ref-first-lookup-when-artifact-declares-canonical-ids，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-threshold-signal-goes-straight-to-construction-site-5a62fdd88773（exact-threshold-signal-goes-straight-to-construction-site，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-token-disambiguation-before-generic-platform-search-0770b3fc9a97（exact-token-disambiguation-before-generic-platform-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-token-grep-first-when-fix-instruction-carries-identifiers-801173cd3e24（exact-token-grep-first-when-fix-instruction-carries-identifiers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exact-token-nomatch-means-switch-source-class-17cc20f513e8（exact_token_nomatch_means_switch_source_class，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exclude-masked-closeout-manifest-driven-add-f-and-tracking-verify-8fdebf9afa52（exclude-masked-closeout-manifest-driven-add-f-and-tracking-verify，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:excluded-artifact-tests-reuse-sibling-availability-gate-020629ebf0a8（excluded-artifact-tests-reuse-sibling-availability-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:executable-qualification-before-variant-enumeration-a95d43616564（executable-qualification-before-variant-enumeration，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 scripts/qualification 存在 | `test -e scripts/qualification` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-approved-proposal-from-held-record-one-read-per-target-9befafb3af1b（execute-approved-proposal-from-held-record-one-read-per-target，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-approved-proposal-via-named-pointers-288506c99efc（execute-approved-proposal-via-named-pointers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-change-spec-at-cited-anchors-resolve-modules-by-symbol-grep-1107f356e6f2（execute-change-spec-at-cited-anchors-resolve-modules-by-symbol-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-formal-time-gate-immediately-on-condition-resolution-60f0700a0900（execute-formal-time-gate-immediately-on-condition-resolution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-gate-qualified-command-verbatim-split-verification-calls-96fd8da6b070（execute-gate-qualified-command-verbatim-split-verification-calls，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:execute-set-defining-code-when-coverage-reports-disagree-on-count-43a4886861e0（execute-set-defining-code-when-coverage-reports-disagree-on-count，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exempt-vs-rollback-adjudicate-by-real-rollback-cost-and-consumer-audit-8b98727ca82a（exempt-vs-rollback-adjudicate-by-real-rollback-cost-and-consumer-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exhaustive-hit-list-as-change-manifest-773f35db6472（exhaustive-hit-list-as-change-manifest，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exhaustive-search-hits-decide-implementation-location-10d261abf6c4（exhaustive-search-hits-decide-implementation-location，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:existence-premise-check-via-primary-source-on-search-plateau-6d6909a4c41a（existence-premise-check-via-primary-source-on-search-plateau，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:existence-proof-mine-persisted-audit-for-prior-channel-fcfaf2892610（existence-proof-mine-persisted-audit-for-prior-channel，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exit-127-is-not-a-negative-finding-probe-validity-first-33217a853c6c（exit-127-is-not-a-negative-finding-probe-validity-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-3249731118b4（exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-result，candidate；usage 2 条 {'applied': 2}，最近 2026-10-30T07:24:51.446970+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:exit0-gated-push-mixed-receipt-local-tracking-ref-triage-1cd9dd1d0985（exit0-gated-push-mixed-receipt-local-tracking-ref-triage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:explain-audit-checker-via-own-records-before-source-hunt-3ed782c1aa67（explain-audit-checker-via-own-records-before-source-hunt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:explicit-redeclare-target-env-on-generation-switch-6e73ca09c81d（explicit-redeclare-target-env-on-generation-switch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:explicit-required-call-over-available-alternative-131af40bf770（explicit-required-call-over-available-alternative，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:extend-sanctioned-topology-rebind-pathway-not-new-mechanism-f561bc6e8c59（extend-sanctioned-topology-rebind-pathway-not-new-mechanism，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/method_seed 存在 | `test -e docs/method_seed` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:external-mechanism-decomposition-as-local-probe-plan-de4dddf1c1de（external-mechanism-decomposition-as-local-probe-plan，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:external-receipt-store-miss-pivots-to-store-location-f1e40be0a4f0（external-receipt-store-miss-pivots-to-store-location，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:external-service-behavior-from-first-party-integration-code-f29c9b0e03de（external-service-behavior-from-first-party-integration-code，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:external-update-merge-status-via-remote-setdiff-not-label-search-36ab77644027（external-update-merge-status-via-remote-setdiff-not-label-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fact-subset-diff-adapted-drafts-before-review-gate-81ce6e9f92b8（fact-subset-diff-adapted-drafts-before-review-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failed-action-keyed-ledger-lookup-then-prescribed-remediation-efed0f93c3f4（failed-action-keyed-ledger-lookup-then-prescribed-remediation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failed-async-action-follow-named-handles-before-reissue-6ae72aaea529（failed-async-action-follow-named-handles-before-reissue，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failed-ci-gate-diagnose-from-local-gate-script-repro-04eed411f3de（failed-ci-gate-diagnose-from-local-gate-script-repro，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failed-row-attribution-triage-before-rerun-63b44d73bd3f（failed-row-attribution-triage-before-rerun，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failing-daemon-own-log-first-fix-at-real-supervisor-297cab3af0ce（failing-daemon-own-log-first-fix-at-real-supervisor，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failing-test-red-triage-by-failure-signature-86ac002c4e46（failing-test-red-triage-by-failure-signature，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failure-receipt-is-zero-info-not-absence-20ac7bad5b0a（failure-receipt-is-zero-info-not-absence，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failure-scoped-ci-log-triage-f602c22331b4（failure-scoped-ci-log-triage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:failure-tolerant-readiness-poll-for-service-switchover-8571c4547411（failure-tolerant-readiness-poll-for-service-switchover，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fakeip-dial-target-x-interface-bind-unselfhealing-restart-0fb68c88db26（fakeip-dial-target-x-interface-bind-unselfhealing-restart，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:false-red-guard-delegate-to-truth-source-e38f5294fa10（false-red-guard-delegate-to-truth-source，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-behavior-premise-before-inherited-change-6c6091650c9c（falsify-behavior-premise-before-inherited-change，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-detector-criterion-and-patch-gate-loop-before-detector-driven-ru-720ca0ed7acd（falsify-detector-criterion-and-patch-gate-loop-before-detector-driven-run，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-error-message-attribution-via-emitter-and-state-truth-8c08c0091979（falsify-error-message-attribution-via-emitter-and-state-truth，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-error-receipt-on-identical-recurrence-verify-echoed-input-c0166d5a76ba（falsify-error-receipt-on-identical-recurrence-verify-echoed-input，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-mechanism-attribution-via-remedy-reproduction-23940a181dc9（falsify-mechanism-attribution-via-remedy-reproduction，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-own-command-platform-flag-before-concurrent-mutation-hypothesis-fb6cbf566324（falsify-own-command-platform-flag-before-concurrent-mutation-hypothesis，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-selection-premise-via-origin-target-ledger-570c187396ab（falsify-selection-premise-via-origin-target-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:falsify-stale-backlog-premise-at-current-head-59a8dae4eadd（falsify-stale-backlog-premise-at-current-head，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:family-containment-gate-before-batch-branch-merge-519261763620（family-containment-gate-before-batch-branch-merge，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T02:29:33.651360+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fastfail-ci-gate-filtered-verdict-then-named-artifact-14e1acb2a084（fastfail-ci-gate-filtered-verdict-then-named-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:feature-parity-audit-anchor-named-mechanism-live-source-915ad1f1438c（feature-parity-audit-anchor-named-mechanism-live-source，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:feature-status-audit-probe-each-causal-link-1be540874c58（feature-status-audit-probe-each-causal-link，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 src/scripts/webui/tests 存在 | `test -e src/scripts/webui/tests` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-before-remote-state-judgment-39e9db9b5bd4（fetch-before-remote-state-judgment，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-current-spec-before-implementing-post-cutoff-protocol-a092d0be5b2a（fetch-current-spec-before-implementing-post-cutoff-protocol，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-named-refs-before-speculative-keyword-search-8cdc4e44d5b2（fetch-named-refs-before-speculative-keyword-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-refresh-before-shared-remote-push-d4c26f4e9abb（fetch-refresh-before-shared-remote-push，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-surfaced-primary-once-authority-named-stop-variant-search-on-noise-018f906d6122（fetch-surfaced-primary-once-authority-named-stop-variant-search-on-noise，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-user-cited-source-before-broad-search-a64b7143ad48（fetch-user-cited-source-before-broad-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fetch-user-given-official-doc-before-plan-name-web-search-c1390111f35f（fetch-user-given-official-doc-before-plan-name-web-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ff-ancestry-before-conflict-surface-bbca6df4f924（ff-ancestry-before-conflict-surface，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ff-window-first-shared-ref-advance-25c56c2869fa（ff-window-first-shared-ref-advance，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:field-driven-sufficiency-stop-on-versioned-receipt-pagination-e5fd2e32a9e9（field-driven-sufficiency-stop-on-versioned-receipt-pagination，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:field-targeted-retrieval-before-linear-receipt-pagination-180c1e26f771（field-targeted-retrieval-before-linear-receipt-pagination，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:field-targeted-skip-scan-on-paged-evidence-blobs-5800d16689b6（field-targeted-skip-scan-on-paged-evidence-blobs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:figure-label-verification-via-coordinate-ocr-not-crop-assumptions-f744cab75889（figure-label-verification-via-coordinate-ocr-not-crop-assumptions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:filter-first-when-pattern-already-in-hand-e3ab57d7561c（filter-first-when-pattern-already-in-hand，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:filter-mirrors-and-name-collisions-then-read-canonical-endpoints-1f35dcf5cbad（filter-mirrors-and-name-collisions-then-read-canonical-endpoints，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/memory/extractor.py 存在 | `test -e src/llm_loop/memory/extractor.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:filter-vendor-tree-hits-and-pin-source-layout-before-reads-41c79a675c78（filter-vendor-tree-hits-and-pin-source-layout-before-reads，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:find-receipts-by-ledger-enumeration-not-keyword-rephrase-5f5c2f39b0e3（find-receipts-by-ledger-enumeration-not-keyword-rephrase，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fingerprint-is-not-wiring-verify-before-direct-api-calls-5e2ca480e807（fingerprint-is-not-wiring-verify-before-direct-api-calls，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:first-deterministic-rejection-adjudicates-batch-local-archive-fallback-beed3526257e（first-deterministic-rejection-adjudicates-batch-local-archive-fallback，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:first-party-scope-discovery-when-vendor-trees-match-the-keyword-73e828d729aa（first-party-scope-discovery-when-vendor-trees-match-the-keyword，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop 存在 | `test -e src/llm_loop` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:first-query-must-preserve-partition-discriminator-ff363d2669cc（first-query-must-preserve-partition-discriminator，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fix-verification-by-residual-signature-scan-be7e078b60f3（fix-verification-by-residual-signature-scan，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:flag-invariant-scopes-fastpath-claim-probe-blindspot-d03a18167e6b（flag-invariant-scopes-fastpath-claim-probe-blindspot，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:flag-lifecycle-entry-cleanup-diff-then-cheap-attribution-2ff3d5aaf963（flag-lifecycle-entry-cleanup-diff-then-cheap-attribution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:flip-gate-decision-probe-named-observation-channel-first-932c22906c23（flip-gate-decision-probe-named-observation-channel-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-authoritative-portal-before-parallel-broad-queries-7d0cd4178e8d（follow-authoritative-portal-before-parallel-broad-queries，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-cited-artifacts-before-tree-scan-d35c39a1fcb7（follow-cited-artifacts-before-tree-scan，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-deliverable-declared-next-step-before-history-sweep-c240a19d8177（follow-deliverable-declared-next-step-before-history-sweep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-error-named-remediation-to-subsystem-interface-568c647646cb（follow-error-named-remediation-to-subsystem-interface，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-existing-instruction-contracts-before-broad-discovery-b5abb650bcdf（follow-existing-instruction-contracts-before-broad-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-gate-rejection-to-tool-contract-before-channel-attempts-58a33089f835（follow-gate-rejection-to-tool-contract-before-channel-attempts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-guard-remediation-pointer-not-rederive-e37995e31fd4（follow-guard-remediation-pointer-not-rederive，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-named-mechanism-identifier-into-code-before-record-sweep-54f607702c00（follow-named-mechanism-identifier-into-code-before-record-sweep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-named-terminal-entrance-decouple-effect-from-own-action-388d5c33615a（follow-named-terminal-entrance-decouple-effect-from-own-action，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-process-provenance-before-path-guessing-491e9b2f03c8（follow-process-provenance-before-path-guessing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-receipt-effect-provenance-not-stale-refs-058c0f5bbc26（follow-receipt-effect-provenance-not-stale-refs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-record-provenance-grep-unique-id-in-producer-store-dd3f8cb3158a（follow-record-provenance-grep-unique-id-in-producer-store，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/ai_rules.md 存在 | `test -e docs/ai_rules.md` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-record-provenance-map-before-broad-grep-cad93ee1503d（follow-record-provenance-map-before-broad-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:follow-scenario-matched-record-edge-before-index-requery-d09df9b8b4d3（follow-scenario-matched-record-edge-before-index-requery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:followup-questions-route-to-recent-artifact-first-4ef2b5c311a1（followup-questions-route-to-recent-artifact-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:font-metrics-over-vision-loop-for-generated-figures-8db5b38fec16（font-metrics-over-vision-loop-for-generated-figures，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:force-trigger-ab-release-snapshot-vs-worktree-fix-verification-2b4e2bc12749（force-trigger-ab-release-snapshot-vs-worktree-fix-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:foreign-namespace-reference-pivot-to-identifier-keyed-ledger-7e3191d702c8（foreign-namespace-reference-pivot-to-identifier-keyed-ledger，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:form-named-block-decompose-atomic-write-then-separate-validate-ec980d278760（form-named-block-decompose-atomic-write-then-separate-validate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:format-only-verdict-rejection-echo-raw-tail-before-resubmit-993ae3583cea（format-only-verdict-rejection-echo-raw-tail-before-resubmit，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fresh-read-authoritative-record-before-finality-claim-35fe91da2cd4（fresh-read-authoritative-record-before-finality-claim，active；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/runtime/service_control.py 存在 | `test -e src/llm_loop/runtime/service_control.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:fresh-resolve-mutable-shared-state-before-bound-mutation-086c24b92de0（fresh-resolve-mutable-shared-state-before-bound-mutation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:frozen-per-item-offline-rescreen-before-new-measurement-f0f72331e448（frozen-per-item-offline-rescreen-before-new-measurement，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:frozen-qualification-drift-switch-to-path-equivalent-worktree-channel-88675a04097b（frozen-qualification-drift-switch-to-path-equivalent-worktree-channel，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:frozen-round-metric-narrows-loop-diagnosis-to-provider-config-fe0fbd99620d（frozen-round-metric-narrows-loop-diagnosis-to-provider-config，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:full-tty-detach-for-long-jobs-in-persistent-interactive-shell-2aeba404466d（full-tty-detach-for-long-jobs-in-persistent-interactive-shell，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:function-role-match-gate-before-usage-trace-a086d1ad82ac（function-role-match-gate-before-usage-trace，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-attribution-on-shared-tree-with-active-foreign-writer-ef14c3fec208（gate-attribution-on-shared-tree-with-active-foreign-writer，candidate；usage 1 条 {'not_applicable': 1}，最近 2026-10-26T07:22:38.148743+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-authenticity-requires-artifact-paths-not-record-ids-48b20cd473ba（gate-authenticity-requires-artifact-paths-not-record-ids，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-boundary-fresh-status-and-residual-triage-under-concurrent-writers-5d18784881c0（gate-boundary-fresh-status-and-residual-triage-under-concurrent-writers，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-cap-rejection-read-assembly-then-split-at-measured-boundary-e4fad2a53218（gate-cap-rejection-read-assembly-then-split-at-measured-boundary，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-check-by-mechanical-state-not-memory-retrieval-e9f89cbf1205（gate-check-by-mechanical-state-not-memory-retrieval，candidate；usage 1 条 {'applied': 1}，最近 2026-10-20T16:40:55.391213+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-check-discrimination-and-grader-contract-replay-before-full-paired--3043322f2952（gate-check-discrimination-and-grader-contract-replay-before-full-paired-run，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-closure-on-job-receipt-result-not-completion-claim-ae5b24ee7dba（gate-closure-on-job-receipt-result-not-completion-claim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-conjunct-over-documented-underdetecting-grader-is-structural-fail-fa7366e0721f（gate-conjunct-over-documented-underdetecting-grader-is-structural-fail，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-design-choke-point-descent-and-entry-path-enumeration-50b160c29f22（gate-design-choke-point-descent-and-entry-path-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-each-tool-call-against-explicit-script-prohibitions-6c8db79dc6f1（gate-each-tool-call-against-explicit-script-prohibitions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-effectiveness-audit-by-ledger-flow-counts-0d787d276e77（gate-effectiveness-audit-by-ledger-flow-counts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-faithful-prevalidation-via-ci-oracle-invocation-923ca6f1141c（gate-faithful-prevalidation-via-ci-oracle-invocation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-fused-ranking-changes-per-channel-and-scope-hints-out-of-coverage-72e7a06b5d22（gate-fused-ranking-changes-per-channel-and-scope-hints-out-of-coverage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-into-shared-query-path-verify-caller-contracts-first-1ebda9a978d9（gate-into-shared-query-path-verify-caller-contracts-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-irreversible-publish-on-dialog-default-verification-341b89e62a91（gate-irreversible-publish-on-dialog-default-verification，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-loosening-union-allowlist-error-fail-closed-237889b5f548（gate-loosening-union-allowlist-error-fail-closed，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-mutations-by-semantics-before-execution-1c8bb257011d（gate-mutations-by-semantics-before-execution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-named-scope-minimal-restage-23984171754a（gate-named-scope-minimal-restage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-named-symbol-provenance-first-c98d1d0291f0（gate-named-symbol-provenance-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-negative-existence-claims-on-partial-coverage-550377503e78（gate-negative-existence-claims-on-partial-coverage，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-on-authoritative-verdict-field-not-payload-prose-4755e0acfb16（gate-on-authoritative-verdict-field-not-payload-prose，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-on-captured-exit-code-c32ebd89e7e8（gate-on-captured-exit-code，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-order-audit-before-mechanism-fix-d71689d412ac（gate-order-audit-before-mechanism-fix，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-qualifier-adjudication-before-recording-literal-pass-5d0d1cde04f4（gate-qualifier-adjudication-before-recording-literal-pass，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-receipt-names-resolver-characterize-foreign-wip-then-escalate-af0444aa3164（gate-receipt-names-resolver-characterize-foreign-wip-then-escalate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-refusal-reason-routes-named-tree-class-then-hash-relocate-5616fd79b947（gate-refusal-reason-routes-named-tree-class-then-hash-relocate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-rerun-exitcode-logfile-discipline-4718d9fcc0ad（gate-rerun-exitcode-logfile-discipline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-reuse-by-input-stability-not-receipt-archaeology-52cc715fc1ec（gate-reuse-by-input-stability-not-receipt-archaeology，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-single-entry-branch-test-on-entry-state-record-38d9f1ba6860（gate-single-entry-branch-test-on-entry-state-record，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gate-untracked-build-artifact-currency-before-requal-suite-701f99ae6906（gate-untracked-build-artifact-currency-before-requal-suite，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:gh-device-push-v2-5a5db8a6b474（gh-device-push 设备码推送链 v2，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:git-bounded-discovery-and-guard-test-as-surface-checklist-c63c51b9c3b1（git-bounded-discovery-and-guard-test-as-surface-checklist，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 tests/unit/__pycache__/test_version_consistency 存在 | `test -e tests/unit/__pycache__/test_version_consistency` → `exit=1` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/web/routes.py 存在 | `test -e src/llm_loop/web/routes.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit/test_version_consistency.py 存在 | `test -e tests/unit/test_version_consistency.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:git-content-hash-canonicalize-before-reading-41a3a7d6b702（git-content-hash-canonicalize-before-reading，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:git-first-when-vcs-identifiers-are-named-9269c9624595（git-first-when-vcs-identifiers-are-named，candidate；usage 2 条 {'applied': 2}，最近 2026-10-17T02:29:33.812141+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:git-metadata-isolation-convention-before-broad-doc-search-0ec3c92ebd6b（git-metadata-isolation-convention-before-broad-doc-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:goal-completion-audit-remote-ground-truth-over-ledger-status-14f50cf116c6（goal-completion-audit-remote-ground-truth-over-ledger-status，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:goal-ledger-first-scoping-then-named-artifacts-96aa2c851c0a（goal-ledger-first-scoping-then-named-artifacts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:goal-named-doc-miss-switch-to-git-commit-provenance-6b7542581f5a（goal-named-doc-miss-switch-to-git-commit-provenance，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/content 存在 | `test -e docs/content` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:goal-url-redirect-as-login-oracle-9eb30c24b411（goal-url-redirect-as-login-oracle，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:governance-chain-first-for-external-rule-integration-913c08708119（governance-chain-first-for-external-rule-integration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:governed-action-three-hop-rule-skill-latest-status-f4ed30ec8caa（governed-action-three-hop-rule-skill-latest-status，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:grandfather-inflight-run-quarantine-admissibility-behind-new-gate-e08762799ff7（grandfather-inflight-run-quarantine-admissibility-behind-new-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:green-health-not-identity-trace-loaded-source-then-provider-auth-c1cc23236a53（green-health-not-identity-trace-loaded-source-then-provider-auth，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:grep-anchor-sufficiency-audit-c4d68f5a0033（grep-anchor-sufficiency-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:grep-asserted-literal-in-producer-before-defect-side-archaeology-c8b986e315af（grep-asserted-literal-in-producer-before-defect-side-archaeology，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:grep-machine-reason-into-local-gate-source-before-retry-guesses-ddc27025dfb2（grep-machine-reason-into-local-gate-source-before-retry-guesses，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-ambiguous-term-once-then-authoritative-doc-ec38bb8b70b4（ground-ambiguous-term-once-then-authoritative-doc，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-derived-label-claims-in-semantics-and-existence-probe-39d27fc2e645（ground-derived-label-claims-in-semantics-and-existence-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-efficiency-in-observed-cost-profile-ea444557e851（ground-efficiency-in-observed-cost-profile，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-enumerable-scale-assumptions-before-design-finalization-83a4fb4a2c33（ground-enumerable-scale-assumptions-before-design-finalization，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-git-target-coordinates-before-location-sensitive-git-ops-aa0ebfc35d75（ground-git-target-coordinates-before-location-sensitive-git-ops，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T00:33:12.500581+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-internal-term-via-authoritative-doc-02de45463890（ground-internal-term-via-authoritative-doc，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-next-step-advice-in-delivery-vs-deployed-delta-4acaaf9ba59c（ground-next-step-advice-in-delivery-vs-deployed-delta，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-review-answers-in-load-bearing-facts-46a13f0bc356（ground-review-answers-in-load-bearing-facts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-terse-cross-platform-republish-via-status-chain-not-workspace-str-448bd1a6dd54（ground-terse-cross-platform-republish-via-status-chain-not-workspace-streams，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ground-verification-in-observed-structure-d7a1bd70547a（ground-verification-in-observed-structure，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:group-by-producer-id-before-similarity-dedup-178708c874e1（group-by-producer-id-before-similarity-dedup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:group-worktree-batches-by-in-diff-id-tags-not-history-lookup-be7684a1e126（group-worktree-batches-by-in-diff-id-tags-not-history-lookup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-block-follow-fence-and-handoff-ec83b7302e72（guard-block-follow-fence-and-handoff，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-fail-attribution-before-broad-forensics-7179e48d8700（guard-fail-attribution-before-broad-forensics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-fix-falsified-enumerate-items-with-own-counter-ec15a8d441ae（guard-fix-falsified-enumerate-items-with-own-counter，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-jurisdiction-before-rule-matching-new-artifact-63bebfdfb4ae（guard-jurisdiction-before-rule-matching-new-artifact，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-precondition-bisection-on-sim-vs-real-divergence-f8ef03768c09（guard-precondition-bisection-on-sim-vs-real-divergence，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-receipt-names-dedicated-path-one-lookup-then-single-call-7aa7e31ff2fd（guard-receipt-names-dedicated-path-one-lookup-then-single-call，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:guard-test-bisect-fixture-vs-guard-via-direct-sensor-probe-9ec082c1a84c（guard-test-bisect-fixture-vs-guard-via-direct-sensor-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:halt-restore-verify-and-inventory-fork-on-tool-substitution-7af144f2ab03（halt-restore-verify-and-inventory-fork-on-tool-substitution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:handover-pending-status-is-snapshot-reread-action-record-before-plan-f805ae0dc5b5（handover-pending-status-is-snapshot-reread-action-record-before-plan，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:harvest-full-write-contract-on-first-gate-rejection-76b1a4f39cee（harvest-full-write-contract-on-first-gate-rejection，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hazard-class-triage-by-declared-safety-mechanisms-a56dd5555cf5（hazard-class-triage-by-declared-safety-mechanisms，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:held-action-id-record-before-state-machine-archaeology-c244c18e01e7（held-action-id-record-before-state-machine-archaeology，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hit-anchor-directed-range-reads-49b9d87e7cb0（hit-anchor-directed-range-reads，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hoist-sandbox-workdir-to-cover-git-worktree-metadata-writes-3c9c32f723d8（hoist-sandbox-workdir-to-cover-git-worktree-metadata-writes，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:honor-prescriptive-rejection-before-retry-96c602058bfc（honor-prescriptive-rejection-before-retry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:honor-receipt-scripted-call-contract-5d17ef812a89（honor-receipt-scripted-call-contract，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hook-invocation-proof-via-exec-bit-parity-and-own-output-905d2cb1f051（hook-invocation-proof-via-exec-bit-parity-and-own-output，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:http-archive-fallback-on-git-tls-failure-behind-transparent-proxy-0020799a8fc8（http-archive-fallback-on-git-tls-failure-behind-transparent-proxy，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:human-gated-precondition-one-probe-then-handoff-and-scheduled-recheck-e15bcda05038（human-gated-precondition-one-probe-then-handoff-and-scheduled-recheck，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-durable-doc-ref-before-log-preview-ba6362597e76（hydrate-durable-doc-ref-before-log-preview，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-in-receipt-ref-before-loss-or-policy-verdict-b393f0bd7087（hydrate-in-receipt-ref-before-loss-or-policy-verdict，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-interrupted-action-receipt-before-rerun-a84e37408d27（hydrate-interrupted-action-receipt-before-rerun，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-matching-verified-card-before-reimplementing-b3015a473bda（hydrate-matching-verified-card-before-reimplementing，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-only-observations-not-already-in-hand-331c0db953f9（hydrate-only-observations-not-already-in-hand，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:hydrate-terminal-closure-evidence-before-recovery-search-32bde0e15581（hydrate-terminal-closure-evidence-before-recovery-search，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/x.md 存在 | `test -e docs/x.md` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:id-2a4e1585a9f5（状态问题直查状态源与按ID全量记录，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:id-anchored-lookup-before-semantic-scan-in-rule-sot-576c6aa1be44（id-anchored-lookup-before-semantic-scan-in-rule-sot，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:id-anchored-scope-and-identity-check-before-destructive-cleanup-be8adedf004d（id-anchored-scope-and-identity-check-before-destructive-cleanup，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:id-keyed-state-lookup-before-layout-enumeration-e1448b14a10d（id-keyed-state-lookup-before-layout-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identical-retry-receipt-after-productive-first-call-self-execute-progres-2949ae0bea24（identical-retry-receipt-after-productive-first-call-self-execute-progression，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identical-truncation-author-provenance-first-dda883f6db50（identical-truncation-author-provenance-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identified-artifact-truncated-previews-read-primary-store-by-owner-id-285e30bdc2e4（identified-artifact-truncated-previews-read-primary-store-by-owner-id，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identifier-form-differential-before-credential-matrix-9e19f844cedd（identifier-form-differential-before-credential-matrix，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identity-check-before-reenumeration-1348df6535d1（identity-check-before-reenumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identity-key-collision-check-before-canonicalizing-orphans-5f33c5eac17b（identity-key-collision-check-before-canonicalizing-orphans，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:identity-mismatch-falsifies-pending-claim-then-state-artifacts-aec0a15a6062（identity-mismatch-falsifies-pending-claim-then-state-artifacts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ignore-stack-audit-before-editing-negation-safe-dir-star-00c008a4e2c5（ignore-stack-audit-before-editing-negation-safe-dir-star，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:in-session-provenance-before-refetch-aa9132287223（in-session-provenance-before-refetch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inband-identity-verify-receipt-suffices-over-sandbox-probes-3fef9050cadb（inband-identity-verify-receipt-suffices-over-sandbox-probes，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inbound-tracked-refs-decide-untracked-disposal-b7dee9896288（inbound-tracked-refs-decide-untracked-disposal，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:include-executable-verification-line-when-depositing-method-cards-91668dcab954（include-executable-verification-line-when-depositing-method-cards，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:index-miss-on-fresh-artifact-verify-disk-ground-truth-69d205734f31（index-miss-on-fresh-artifact-verify-disk-ground-truth，candidate；usage 1 条 {'applied': 1}，最近 2026-10-17T01:13:56.393210+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:index-versioned-report-chain-before-adhoc-evidence-reads-0988210ce2a1（index-versioned-report-chain-before-adhoc-evidence-reads，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inert-diff-gate-rerun-failure-is-environment-22e7ade258b1（inert-diff-gate-rerun-failure-is-environment，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/receipts 存在 | `test -e docs/receipts` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inherit-dated-workspace-research-before-new-discovery-0308e23fc5b0（inherit-dated-workspace-research-before-new-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inject-known-bad-probe-to-falsify-vacuous-green-gate-8a4903b7b2e8（inject-known-bad-probe-to-falsify-vacuous-green-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:input-device-dead-after-update-layer-bisect-udev-tag-before-driver-09139120b0f0（input-device-dead-after-update-layer-bisect-udev-tag-before-driver，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inspect-existing-artifact-directly-before-generation-record-hunt-064baa5920e7（inspect-existing-artifact-directly-before-generation-record-hunt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inspect-resulting-state-before-repeating-non-idempotent-action-41c95818b7b7（inspect-resulting-state-before-repeating-non-idempotent-action，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:instructionless-content-drop-clarify-via-canonical-register-1c05c71f5acb（instructionless-content-drop-clarify-via-canonical-register，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:intent-state-contradiction-probe-veto-gates-6051991d5cf0（intent-state-contradiction-probe-veto-gates，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:interpreter-resolve-source-and-config-paths-under-relocated-installs-0e82fcc12b3d（interpreter-resolve-source-and-config-paths-under-relocated-installs，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:interrupt-reconcile-from-receipts-yield-to-active-owner-df8e729aafcf（interrupt-reconcile-from-receipts-yield-to-active-owner，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:invalid-choice-error-is-interface-truth-map-verb-to-owner-layer-cb58a78c027d（invalid-choice-error-is-interface-truth-map-verb-to-owner-layer，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:invalid-object-fatal-voids-ancestry-label-rerun-where-refs-resolve-be127aa9dece（invalid-object-fatal-voids-ancestry-label-rerun-where-refs-resolve，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:invalid-ref-fastfail-single-decision-question-3e4e777015b4（invalid-ref-fastfail-single-decision-question，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:inventory-driven-salvage-commit-5b505795e3f4（inventory-driven-salvage-commit，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/evals 存在 | `test -e docs/evals` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:irreversible-action-lossless-reconciliation-4266e4ab4385（irreversible-action-lossless-reconciliation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:is-it-used-enrollment-checklist-from-assembly-code-first-9eb5e4073a1a（is-it-used-enrollment-checklist-from-assembly-code-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolate-sibling-paths-in-negative-tests-2a915029c432（isolate-sibling-paths-in-negative-tests，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolate-via-linked-worktree-when-dirty-state-disjoint-and-foreign-0b5a33f42326（isolate-via-linked-worktree-when-dirty-state-disjoint-and-foreign，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolation-config-visibility-seed-and-identity-gate-77b2f298c154（isolation-config-visibility-seed-and-identity-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolation-delta-config-cache-shadowing-f8ead0b047a4（isolation-delta-config-cache-shadowing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:isolation-preflight-before-trusting-gate-verdicts-6f1cd4e954c7（isolation-preflight-before-trusting-gate-verdicts，candidate；usage 2 条 {'applied': 2}，最近 2026-10-29T23:02:55.235575+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:item-record-and-deployed-delta-before-execution-registration-fd6b348f72de（item-record-and-deployed-delta-before-execution-registration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:jitter-explainability-signature-triage-before-flaky-stabilization-23d6b79e9329（jitter-explainability-signature-triage-before-flaky-stabilization，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:job-receipt-embedded-command-pins-run-paths-before-filename-search-5b65acb00e1e（job-receipt-embedded-command-pins-run-paths-before-filename-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:join-handover-receipt-root-and-relative-path-before-root-guessing-0e89d3202731（join-handover-receipt-root-and-relative-path-before-root-guessing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:jsonl-zero-count-needs-positive-control-and-encoding-variants-b470876758d1（jsonl-zero-count-needs-positive-control-and-encoding-variants，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:jump-probe-oversized-single-line-blob-past-uniform-noise-66a24f77d981（jump-probe-oversized-single-line-blob-past-uniform-noise，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:key-next-round-advice-to-doc-deliverable-and-clause-arity-aaef8961d3fb（key-next-round-advice-to-doc-deliverable-and-clause-arity，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:keyed-bounded-find-resolves-relative-path-parent-after-root-probe-fails-57de0ea2e736（keyed-bounded-find-resolves-relative-path-parent-after-root-probe-fails，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:keyed-in-blob-search-before-linear-receipt-pagination-65ddc0c5ae1f（keyed-in-blob-search-before-linear-receipt-pagination，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:known-issue-citation-resolve-originating-record-first-23882c95be22（known-issue-citation-resolve-originating-record-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:known-long-installs-background-first-verify-via-receipt-path-ed0ef0e5f36a（known-long-installs-background-first-verify-via-receipt-path，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:late-stage-failure-reuse-receipt-stdout-then-symmetric-compare-a2f037e33df4（late-stage-failure-reuse-receipt-stdout-then-symmetric-compare，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:layer-mixed-permission-denials-by-signature-before-sandbox-attribution-8388f1ed031b（layer-mixed-permission-denials-by-signature-before-sandbox-attribution，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:layered-merge-gap-adjudication-cherry-vs-integration-signal-ddf15fea71c0（layered-merge-gap-adjudication-cherry-vs-integration-signal，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:least-invasive-sufficient-channel-first-f7c59cb213c7（least-invasive-sufficient-channel-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ledger-first-recovery-of-session-created-record-payloads-6a434adcecc9（ledger-first-recovery-of-session-created-record-payloads，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:ledger-ref-anchored-nextstep-87c39f2a55b6（ledger-ref-anchored-nextstep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lfl-mirror-qualified-worktree-33ba78f2f2e7（LFL mirror 新代码上线：qualified worktree + 代次推进全流程，hold；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 docs/LFL-restart-guide.md 存在 | `test -e docs/LFL-restart-guide.md` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/runtime/service_control.py 存在 | `test -e src/llm_loop/runtime/service_control.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 scripts/restart_mirror.sh 存在 | `test -e scripts/restart_mirror.sh` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/LFL-restart-guide.md 存在 | `test -e docs/LFL-restart-guide.md` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lifecycle-record-adjudication-via-owner-source-grep-7a7ec7f064d0（lifecycle-record-adjudication-via-owner-source-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lifecycle-registry-first-restart-not-name-grep-absence-0acaca0d0557（lifecycle-registry-first-restart-not-name-grep-absence，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lifecycle-status-from-event-stream-receipt-8c3894cb0fea（lifecycle-status-from-event-stream-receipt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:line-anchored-windowed-read-not-read-to-eof-d4021b82c0c9（line-anchored-windowed-read-not-read-to-eof，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:literal-anchor-resolves-layout-contract-and-consumption-scope-4fd76f834978（literal-anchor-resolves-layout-contract-and-consumption-scope，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:literal-grep-and-source-scope-before-disputing-numbers-0595645fda7f（literal-grep-and-source-scope-before-disputing-numbers，candidate；usage 1 条 {'adapted': 1}，最近 2026-10-21T20:31:39.392317+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-authority-sibling-probe-falsify-user-premise-d00f07864d09（live-authority-sibling-probe-falsify-user-premise，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-code-artifact-ancestry-fork-restart-vs-publish-cdbc4bab486f（live-code-artifact-ancestry-fork-restart-vs-publish，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-code-grounding-over-chat-archaeology-ca680180ad24（live-code-grounding-over-chat-archaeology，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-config-carrier-authority-for-enablement-claims-8d4742a5d55e（live-config-carrier-authority-for-enablement-claims，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-config-first-sibling-diff-gap-audit-3837d578ee9e（live-config-first-sibling-diff-gap-audit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-copy-first-when-search-hits-snapshot-forests-cfbfa757fb77（live-copy-first-when-search-hits-snapshot-forests，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/methods/store.py 存在 | `test -e src/llm_loop/methods/store.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/methods 存在 | `test -e src/llm_loop/methods` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-data-copy-verify-toctou-rebaseline-snapshot-internal-4b1694aa0ee9（live-data-copy-verify-toctou-rebaseline-snapshot-internal，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-endpoint-over-static-artifacts-for-registry-facts-e48f75a876e6（live-endpoint-over-static-artifacts-for-registry-facts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-job-handle-before-index-and-telemetry-enumeration-afa65afe53fc（live-job-handle-before-index-and-telemetry-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-pid-first-runtime-lookup-abefca85b64f（live-pid-first-runtime-lookup，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 src/HEAD 存在 | `test -e src/HEAD` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-process-anchor-verify-deployment-claims-b3abbf2f86e4（live-process-anchor-verify-deployment-claims，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-process-fd-map-before-fuzzy-log-search-f876c55bcf3e（live-process-fd-map-before-fuzzy-log-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-process-handles-before-path-guessing-0aede9c1dc0b（live-process-handles-before-path-guessing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-rerun-over-history-recovery-5920494e9147（live-rerun-over-history-recovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-run-loop-triage-and-steer-channel-rescue-3d75908f33cc（live-run-loop-triage-and-steer-channel-rescue，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-service-self-route-discovery-before-guess-or-recall-bd6b7da3387e（live-service-self-route-discovery-before-guess-or-recall，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| url | no_verdict（无判定） | 正文含外部 URL http://host:port/（死链即事实性失锚） | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-shared-main-merge-via-isolated-review-and-ff-realign-loop-ae7818a50e76（live-shared-main-merge-via-isolated-review-and-ff-realign-loop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-smoke-probe-before-accepting-probe-fixes-58bb619419c1（live-smoke-probe-before-accepting-probe-fixes，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-source-verify-pending-external-items-4574e64b5649（live-source-verify-pending-external-items，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-state-first-for-forward-looking-ops-questions-c18cb8033d16（live-state-first-for-forward-looking-ops-questions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:live-tree-first-discovery-under-snapshot-mirrors-and-excludes-9a0fe7ca5ab2（live-tree-first-discovery-under-snapshot-mirrors-and-excludes，active；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 tests/unit/test_ 存在 | `test -e tests/unit/test_` → `exit=1` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit 存在 | `test -e tests/unit` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:liveness-by-consumption-point-not-mention-d3de6db1b4cf（liveness-by-consumption-point-not-mention，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:local-service-impl-via-runtime-probe-3cb597c518a0（local-service-impl-via-runtime-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-attested-deliverable-by-title-phrase-content-search-70cc0b8fd489（locate-attested-deliverable-by-title-phrase-content-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-authoritative-record-via-handler-store-code-c1394db56200（locate-authoritative-record-via-handler-store-code，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-authority-repo-by-live-hash-membership-not-fs-enumeration-455cf755a248（locate-authority-repo-by-live-hash-membership-not-fs-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-batch-repo-by-change-fingerprint-not-filename-search-9829cbed8a0e（locate-batch-repo-by-change-fingerprint-not-filename-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-cited-doc-by-structural-metadata-and-recency-69a3131cd3b6（locate-cited-doc-by-structural-metadata-and-recency，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-generic-named-task-script-by-artifact-domain-token-7a839dceabb9（locate-generic-named-task-script-by-artifact-domain-token，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-live-service-runtime-via-process-table-first-490c83c76eda（locate-live-service-runtime-via-process-table-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-project-env-before-symptom-workarounds-f7dd29f1718b（locate-project-env-before-symptom-workarounds，hold；usage 2 条 {'applied': 2}，最近 2026-10-13T17:53:59.397638+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-recent-plan-doc-by-mtime-on-content-keyword-miss-19812522a9d4（locate-recent-plan-doc-by-mtime-on-content-keyword-miss，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-referenced-deliverable-via-ledger-before-repo-search-21108ddca9fa（locate-referenced-deliverable-via-ledger-before-repo-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-registry-data-via-loader-docstring-and-live-catalog-proof-a3ac1f105008（locate-registry-data-via-loader-docstring-and-live-catalog-proof，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/fixtures 存在 | `test -e tests/fixtures` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-running-service-log-via-process-fds-not-path-guesses-4d621248a800（locate-running-service-log-via-process-fds-not-path-guesses，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-runtime-files-via-lsof-on-live-pid-before-filesystem-hunt-70fce75a4462（locate-runtime-files-via-lsof-on-live-pid-before-filesystem-hunt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-session-declared-deliverables-via-present-files-record-before-fil-5ff35633a5e8（locate-session-declared-deliverables-via-present-files-record-before-filename-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-symbol-via-its-introducing-commit-cd76af98cfb1（locate-symbol-via-its-introducing-commit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-test-consumers-by-module-import-path-845a04c7caf6（locate-test-consumers-by-module-import-path，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-unimplemented-feature-host-via-spec-cited-anchors-2752753f5c23（locate-unimplemented-feature-host-via-spec-cited-anchors，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 evals/tests 存在 | `test -e evals/tests` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-via-quoted-ui-literals-before-broad-filename-search-c867a42a91f8（locate-via-quoted-ui-literals-before-broad-filename-search，candidate；usage 1 条 {'applied': 1}，最近 2026-10-18T13:32:45.815602+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locate-workdir-via-job-receipt-commandline-8d8ea4f52975（locate-workdir-via-job-receipt-commandline，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:locator-answered-checklist-edit-not-resweep-0e7df520d3ab（locator-answered-checklist-edit-not-resweep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:log-subject-edge-show-stat-before-indexed-search-3743949bac4c（log-subject-edge-show-stat-before-indexed-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:long-job-observe-by-estimate-efe14a4ca321（long-job-observe-by-estimate，hold；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lossless-rewrite-over-allowlist-on-content-gate-block-c8c66285564e（lossless-rewrite-over-allowlist-on-content-gate-block，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lossless-verify-before-irreversible-publish-0d0481739cfc（lossless-verify-before-irreversible-publish，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:lost-handle-regenerate-forward-3a6d0088a08d（lost-handle-regenerate-forward，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:machine-literal-preflight-before-curated-commit-18f7c6295efd（machine-literal-preflight-before-curated-commit，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:managed-restart-target-config-preflight-and-rollback-binding-356473240ac6（managed-restart-target-config-preflight-and-rollback-binding，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/runtime/resolver.py 存在 | `test -e src/llm_loop/runtime/resolver.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/web/task_budget_canary.py 存在 | `test -e src/llm_loop/web/task_budget_canary.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/runtime/service_control.py 存在 | `test -e src/llm_loop/runtime/service_control.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 scripts/restart_mirror.sh 存在 | `test -e scripts/restart_mirror.sh` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 scripts/restart_mirror.sh 存在 | `test -e scripts/restart_mirror.sh` → `exit=0` | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `dist` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `dual_root_rejected` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `svc-2fee46dc41e04067b8a1c29dc807c753` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mandate-anchored-enforcement-audit-before-gating-660a179d6684（mandate-anchored-enforcement-audit-before-gating，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:manifest-first-stack-discovery-45cfedd8b434（manifest-first-stack-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:manifest-first-stack-id-over-broad-grep-81e0b01cb231（manifest-first-stack-id-over-broad-grep，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:manifest-verify-fetched-artifact-before-consume-4aa016596e58（manifest-verify-fetched-artifact-before-consume，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:manual-command-parity-from-internal-caller-via-pinned-release-4dc917161921（manual-command-parity-from-internal-caller-via-pinned-release，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:map-audit-dimensions-to-enumerated-evidence-before-discovery-c33abfe6afc7（map-audit-dimensions-to-enumerated-evidence-before-discovery，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:map-declared-gates-to-receipts-before-completion-claim-ab5801cb82e3（map-declared-gates-to-receipts-before-completion-claim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-evidence-modality-to-user-complaint-752a2d104abd（match-evidence-modality-to-user-complaint，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-exception-value-to-user-context-read-only-producer-frame-b35dc2b74734（match-exception-value-to-user-context-read-only-producer-frame，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-git-add-mode-to-status-change-class-ee1d2bb36f21（match-git-add-mode-to-status-change-class，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-probe-breadth-to-unknown-granularity-d245467b53e0（match-probe-breadth-to-unknown-granularity，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/prompting.md 存在 | `test -e docs/prompting.md` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-search-store-scope-to-record-epoch-228dfa88ba03（match-search-store-scope-to-record-epoch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:match-verification-granularity-to-claim-47645b9a0a43（match-verification-granularity-to-claim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:max-blocking-wait-when-polling-background-subagents-d8b428b468c2（max-blocking-wait-when-polling-background-subagents，candidate；usage 4 条 {'applied': 4}，最近 2026-10-30T09:28:47.843180+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:max-wait-block-poll-and-interleave-parent-prep-for-long-subagents-c0aab429fa3f（max-wait-block-poll-and-interleave-parent-prep-for-long-subagents，candidate；usage 1 条 {'applied': 1}，最近 2026-10-16T09:37:05.153913+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:measure-exposure-classes-at-remediation-parent-before-history-rewrite-ed8d23d1b91c（measure-exposure-classes-at-remediation-parent-before-history-rewrite，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:measured-timeout-as-poll-lower-bound-4da80a3cf9e3（measured-timeout-as-poll-lower-bound，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mechanical-blind-eval-isolation-00c0648997ae（mechanical-blind-eval-isolation，qualified；usage 1 条 {'applied': 1}，最近 2026-10-05T23:28:40.990128+08:00）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 evals/instrument_qualification_v1/iq_R1_notes.md 存在 | `test -e evals/instrument_qualification_v1/iq_R1_notes.md` → `exit=0` | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `sha256sum` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mechanical-identity-resolution-then-receipt-narrowed-retry-7701e37ca4b6（mechanical-identity-resolution-then-receipt-narrowed-retry，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:memory-as-hypothesis-live-schema-as-authority-041838a41b0f（memory-as-hypothesis-live-schema-as-authority，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:memory-gap-audit-stream-verify-and-fix-owner-routing-fa9741a96fc7（memory-gap-audit-stream-verify-and-fix-owner-routing，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:memory-gap-diagnose-by-state-readout-not-reflection-loop-d4334f34c812（memory-gap-diagnose-by-state-readout-not-reflection-loop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:merge-base-probe-first-no-push-history-archaeology-52268e021e44（merge-base-probe-first-no-push-history-archaeology，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:method-candidate-ab-validity-trigger-confound（method-candidate-ab-validity-trigger-confound，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:method-candidate-current-callsite-refresh（method-candidate-current-callsite-refresh，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:method-candidate-hydrate-trace（method-candidate-hydrate-trace，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mine-canonical-ids-and-role-notes-before-search-or-attempt-8f7fffa1d71b（mine-canonical-ids-and-role-notes-before-search-or-attempt，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | manual_review（需人工） | [mention] body 声明仓库路径 docs/src 存在 | `test -e docs/src` → `exit=1` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mine-gated-cli-contract-one-read-then-qualified-destructive-command-8d148edb6ddc（mine-gated-cli-contract-one-read-then-qualified-destructive-command，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mine-read-source-conventions-before-writing-derived-artifacts-e9d2fc4d0154（mine-read-source-conventions-before-writing-derived-artifacts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mine-spa-bundle-before-render-escalation-b78f02786ab1（mine-spa-bundle-before-render-escalation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:minimal-injection-probe-before-accepting-tightened-grader-gate-e602f6a5ebb2（minimal-injection-probe-before-accepting-tightened-grader-gate，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:minimal-probe-before-full-payload-on-unverified-write-path-ba5bcd9406c0（minimal-probe-before-full-payload-on-unverified-write-path，candidate；usage 4 条 {'applied': 1, 'not_applicable': 3}，最近 2026-10-30T08:40:53.162144+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mirror-ci-triage-local-fix-attribution-and-sibling-remote-oracle-9363433bcbf1（mirror-ci-triage-local-fix-attribution-and-sibling-remote-oracle，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mirror-receipt-declared-call-contract-verbatim-6a1113951efb（mirror-receipt-declared-call-contract-verbatim，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:module-not-found-diagnose-from-path-and-interpreter-facts-80e0f6d68dad（module-not-found-diagnose-from-path-and-interpreter-facts，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:multi-hop-client-state-test-localize-at-first-unproven-hop-4bdae8a23567（multi-hop-client-state-test-localize-at-first-unproven-hop，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:multi-option-approval-adjudicate-by-gate-preservation-e916f208abbf（multi-option-approval-adjudicate-by-gate-preservation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:multiplatform-publish-order-by-irreversibility-8a3eb6cf2ab5（multiplatform-publish-order-by-irreversibility，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:multiplatform-publish-order-by-irreversibility-d9f5c7ea6b4d（multiplatform-publish-order-by-irreversibility，invalidated；usage 2 条 {'applied': 1, 'not_applicable': 1}，最近 2026-10-20T13:43:20.566097+08:00）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:must-exist-term-zero-hit-switch-to-unindexed-ground-truth-6cb544dc95ac（must-exist-term-zero-hit-switch-to-unindexed-ground-truth，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 docs/analysis 存在 | `test -e docs/analysis` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mutate-live-registry-via-its-own-admin-surface-f80eb5fb1e98（mutate-live-registry-via-its-own-admin-surface，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:mutation-verify-consumption-protocol-9adee5230506（mutation-verify-consumption-protocol，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/browser/perception.py 存在 | `test -e src/llm_loop/browser/perception.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 src/llm_loop/browser/method_card.py 存在 | `test -e src/llm_loop/browser/method_card.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [anchor] frontmatter.freshness_refs 声明仓库路径 docs/DESIGN-20261007-browser-semantic-guard.md 存在 | `test -e docs/DESIGN-20261007-browser-semantic-guard.md` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/browser/perception.py 存在 | `test -e src/llm_loop/browser/perception.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/browser/method_card.py 存在 | `test -e src/llm_loop/browser/method_card.py` → `exit=0` | false |
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 tests/unit/test_browser_perception_sensitive_redaction.py 存在 | `test -e tests/unit/test_browser_perception_sensitive_redaction.py` → `exit=0` | false |
| tool_existence | pass（断言成立，非证据） | 正文以反引号提及工具/命令 `browser_operate` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `method-semantic-operation` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `value_text` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `object_state` | （成员检查/人工项，无命令输出） | false |
| tool_existence | manual_review（需人工） | 正文以反引号提及工具/命令 `object_text` | （成员检查/人工项，无命令输出） | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:name-keyed-git-ref-lookup-before-enumeration-398f57241d7f（name-keyed-git-ref-lookup-before-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:name-path-mismatch-probe-git-identity-before-scope-advice-69dab3d36927（name-path-mismatch-probe-git-identity-before-scope-advice，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-artifact-git-metadata-before-repo-enumeration-5f43d6c96a8d（named-artifact-git-metadata-before-repo-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-entity-verification-via-canonical-url-fetch-d7d09edf826b（named-entity-verification-via-canonical-url-fetch，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-gate-read-source-before-env-exploration-318c227849ec（named-gate-read-source-before-env-exploration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-label-check-against-authoritative-registry-before-implementation-a6207ad19e5c（named-label-check-against-authoritative-registry-before-implementation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-pointer-over-enumeration-e0a1ff56244a（named-pointer-over-enumeration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-producer-fact-fetch-canonical-source-not-generic-search-09db57a70349（named-producer-fact-fetch-canonical-source-not-generic-search，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-product-ops-identity-and-verified-experience-first-e521c85e2825（named-product-ops-identity-and-verified-experience-first，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-remote-containment-answer-for-merge-status-questions-97d1bcfd9fdb（named-remote-containment-answer-for-merge-status-questions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-service-integration-three-plane-check-03a7adb71023（named-service-integration-three-plane-check，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-target-lookup-plus-error-coded-probe-2d520339e0c0（named-target-lookup-plus-error-coded-probe，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:named-tool-hang-code-vs-environment-triage-9eb9df956369（named-tool-hang-code-vs-environment-triage，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:narrow-recheck-delegation-from-prior-pass-receipt-plus-delta-c05655a7602e（narrow-recheck-delegation-from-prior-pass-receipt-plus-delta，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:native-logs-before-heavy-probes-on-live-shared-services-5bcd812f372c（native-logs-before-heavy-probes-on-live-shared-services，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:negative-claims-anchor-to-target-canonical-enumerative-source-e5d5ff7045e1（negative-claims-anchor-to-target-canonical-enumerative-source，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:negative-liveness-reobserve-before-restore-7998be3d09ca（negative-liveness-reobserve-before-restore，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:next-phase-advice-from-state-ledgers-not-docs-keywords-21b53965269c（next-phase-advice-from-state-ledgers-not-docs-keywords，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:next-step-via-authoritative-state-aggregators-a599d11e1b37（next-step-via-authoritative-state-aggregators，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:next-steps-from-artifact-forward-declaration-255044cc9d80（next-steps-from-artifact-forward-declaration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:no-anchor-artifact-ref-ask-path-before-scope-walk-d6a9acff0544（no-anchor-artifact-ref-ask-path-before-scope-walk，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:no-error-list-absence-unknown-poll-and-authoritative-readback-before-ret-cfd08c217602（no-error-list-absence-unknown-poll-and-authoritative-readback-before-retry，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:no-identical-retry-after-deterministic-target-failure-b0198a230707（no-identical-retry-after-deterministic-target-failure，candidate；usage 0 条 {}，最近 ）

| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |
|---|---|---|---|---|
| local_path | pass（断言成立，非证据） | [mention] body 声明仓库路径 src/llm_loop/factory.py 存在 | `test -e src/llm_loop/factory.py` → `exit=0` | false |

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:no-identical-retry-on-deterministic-param-error-receipt-8c5c35a2bb26（no-identical-retry-on-deterministic-param-error-receipt，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:none-result-triage-control-probe-then-domain-enable-before-env-hypothese-03e7ab1ff8a7（none-result-triage-control-probe-then-domain-enable-before-env-hypotheses，active；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:noop-delta-check-before-bulk-field-backfill-4a058f7f9b98（noop-delta-check-before-bulk-field-backfill，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:normalize-timebase-before-cross-source-correlation-882497ea70e9（normalize-timebase-before-cross-source-correlation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:novelty-gated-facet-enumeration-keyword-only-store-1c3087ae48c3（novelty-gated-facet-enumeration-keyword-only-store，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:null-delta-triage-pairing-validity-before-buying-reruns-d406fcaafec9（null-delta-triage-pairing-validity-before-buying-reruns，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:null-result-noise-floor-audit-before-mechanism-iteration-46498b4dded0（null-result-noise-floor-audit-before-mechanism-iteration，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:numeric-invariant-arbitration-for-animated-geometry-over-vlm-impressions-e243b8ee7b54（numeric-invariant-arbitration-for-animated-geometry-over-vlm-impressions，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:numstat-fingerprint-reconcile-before-loss-forensics-fe0e96a92220（numstat-fingerprint-reconcile-before-loss-forensics，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

### method:object-scoped-remediation-before-shared-worktree-mutation-b735540602a6（object-scoped-remediation-before-shared-worktree-mutation，candidate；usage 0 条 {}，最近 ）

- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。

- code_conflict：代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码

