# Branch Governance Phase 18 — Unique Tip Disposition Audit

- Date: 2026-09-29
- Audit main: `070154444433896d964aacec8753b8caa7d9529d`
- Scope: 67 retained unique-patch tips (excluding `main`, production, and the Phase14 archive branch)
- Result: **AUDIT COMPLETE — no migration candidate and no active tip**

## Executive result

| Disposition | Count | Meaning |
| --- | ---: | --- |
| `MIGRATE_TO_MAIN` | 0 | No branch contains a current-valid capability that current main still lacks with sufficient promotion evidence. |
| `KEEP_ACTIVE` | 0 | No tip has an attached worktree, branch-backed process, or current continuation role. |
| `ARCHIVE_ONLY` | 38 | Frozen eval/design/research/incident/WIP evidence, or qualified experiments never selected for production. |
| `SUPERSEDED_SEMANTICALLY` | 29 | Unique patch history remains, but later main represents the intent or the old mechanism is obsolete. |
| **Total** | **67** | 52 local-only + 15 exact-remote-backed. |

Phase 18 deliberately does **not** equate “unique patch” with “missing capability.” The audit compared branch intent and frozen result boundaries against the current-main mechanism. Any future migration would be a current-main semantic implementation, never an automatic cherry-pick.

## Why there are no migration candidates

- **Execution Ledger:** the frozen S2 treatment had zero adoption and no benefit evidence; its result explicitly rejects production promotion/automatic gating. The later Qwen 10/10 mini-gate was control-only.
- **SMC ActionRef:** the branch was a valid qualified experiment, but governance explicitly stopped before merge/deploy. Current main independently retains the hard Browser safety boundaries: exact GroundingRef/version, single dispatch, target binding, ActionReceipt and durable execution/effect fencing.
- **Middleware:** Phase 12 formally retired the middleware runtime/worktree after decoupling production Chrome. Its design and implementation history is valuable, but the current Web-GPT path no longer depends on it.
- **Context T2/T3/T4:** those default-off flags were not adopted into current runtime. Current main subsequently converged on atomic protocol groups, task/ingress anchors, bounded recoverable tool views and newer compaction/cache protections.
- **Narrow fixes:** current main directly contains the service `no_manifest_skip`/`verify_targets` behavior, immutable file-version preconditions, evidence source resolution/exact-read recovery, later cache-health logic, first-call schema facts, Web session model authority, live interjection, tool activity, Markdown isolation, memory citation behavior and subagent lifecycle hardening.
- **Projection env leak:** current main passes the affected projection suite 23/23 even with `LFL_TOOL_WORKING_SET_GRACE_GROUPS=3`; the old fixture is not required.
- **M1 fixes:** nonconvergence, Memory observation-history compatibility and schema-mismatch/corruption classification have direct current-main successors (`24705c077`, `f1bfa11d1`, `29c92087d`).

## Family summary

| Family | Archive only | Semantically superseded |
| --- | ---: | ---: |
| `cache-context-accounting` | 4 | 4 |
| `chatgpt-web-middleware-ingress` | 4 | 0 |
| `context-retrieval-evals` | 6 | 0 |
| `execution-efficiency-tooling` | 1 | 1 |
| `governance-qualification` | 5 | 0 |
| `learning-memory-methods` | 1 | 2 |
| `misc-preservation` | 6 | 3 |
| `provider-protocol-continuity` | 5 | 0 |
| `runtime-config-service-control` | 1 | 4 |
| `smc-actionref-execution` | 4 | 1 |
| `web-webui-product` | 1 | 14 |

## 38 archive-only tips

- `archive/local-main-pre-convergence-20260911` — `historical_snapshot`; local-only preservation root. Explicit pre-convergence preservation root; long-term value is historical reconstruction, not current runtime adoption.
- `audit/d8f3-context-replay-20260921` — `frozen_audit`; local-only preservation root. Frozen context-visibility replay evidence; no production patch is authorized by this audit tip.
- `audit/m1-g2-gate-report-20260915` — `frozen_audit`; local-only preservation root. Frozen scorer/gate findings; preserve as governance evidence rather than runtime source.
- `backup/20260819-after-3am` — `historical_backup`; exact remote backup. Explicit historical backup containing an old product/cache state; preserve for archaeology only.
- `benchmark/reliable-v0-20260921` — `frozen_benchmark`; local-only preservation root. Qualified measurement-chain benchmark snapshot; evidence asset, not production feature branch.
- `docs-plan-20260914-preserved` — `preserved_plan`; local-only preservation root. Explicitly preserved design/state-ownership/context-integrity plan; retain as design history only.
- `docs/agent-qualification-envelope-v0.1-20260915` — `frozen_governance_gate`; local-only preservation root. A.5/governance gate design and wiring from an earlier qualification cycle; preserve as governance evidence.
- `docs/middleware-envelope-protocol-v0.1-20260925` — `retired_middleware`; local-only preservation root. Middleware envelope design/implementation line. Phase12 formally retired the middleware runtime/worktree after Chrome decoupling; branch history remains archival.
- `eval/fc2c-live-runtime-20260913` — `frozen_eval`; local-only preservation root. Frozen Browser live-runtime qualification protocol/result; preserve as evaluation evidence.
- `eval/p2a-older-history-eval-20260928` — `frozen_eval`; local-only preservation root. Frozen P2A older-history baseline/evidence; no direct production promotion is encoded by the branch.
- `eval/p2a-receipt-ab-20260928` — `frozen_eval`; local-only preservation root. Frozen P2A receipt A/B and final-wire audit; preserve experiment evidence.
- `eval/stagec-tool-surface-c1-20260928` — `frozen_eval`; local-only preservation root. Stage-C tool-surface real-model gate recorded a rejection; evidence should remain immutable, not migrated.
- `eval/web-gpt-512k-canary-20260927` — `frozen_eval`; local-only preservation root. Long-context Web-GPT qualification harness/canary evidence; archival test asset.
- `evo-20260914-exec-surface-followup` — `measurement_prereg`; exact remote backup. Unique tip is measurement/preregistration material; runtime descendants are represented elsewhere.
- `exp/execution-efficiency-fcr-p2-gen120-20260926` — `frozen_eval_not_promoted`; local-only preservation root. Frozen P2 execution-efficiency/currentness replay and quick-canary evidence; prior result was not a production promotion.
- `exp/qwen-reliability-s2b-20260927` — `execution_ledger_no_benefit`; local-only preservation root. Frozen S2 Execution Ledger result: zero treatment adoption, no benefit evidence, and explicit no production promotion/automatic gating; Qwen 10/10 follow-up was control-only.
- `experiment/common-governance-activation-20260913` — `frozen_experiment`; local-only preservation root. Frozen activation-kernel A/B protocol; experimental evidence only.
- `experiment/common-governance-rerun-20260914` — `frozen_experiment_hold`; local-only preservation root. Frozen governance activation rerun; result recorded hold rather than promotion.
- `experiment/epistemic-closure-ab-20260914` — `frozen_experiment_hold`; local-only preservation root. Cognitive/epistemic closure qualification line ended in a recorded hold; preserve for study, not runtime adoption.
- `experiment/retrieval-ab-20260922` — `frozen_research_finding`; local-only preservation root. Retrieval A/B and oracle rewrite work produced useful query-bridge findings, but this branch is evaluation evidence rather than a production patch.
- `experiment/s1-checkpoint-producer-20260906` — `dormant_experiment`; local-only preservation root. Branch explicitly preserves a dormant checkpoint-producer experiment.
- `feature/smc-execution-binding-p11-20260919` — `qualified_experiment_not_selected`; exact remote backup. Execution-binding P1/P1.1 design/synthetic qualification is valuable frozen evidence, but it was not selected into current runtime.
- `feature/smc-p4-live-v02-live-20260920` — `qualified_experiment_not_selected`; exact remote backup. ActionRef P4-FCR/P4-LIVE line reached frozen qualification, but contemporaneous governance explicitly stopped before merge/deploy. Current main retained the underlying hard safety invariants without adopting this alias layer.
- `fix/agentpilot-tool-contracts-20260912` — `frozen_eval_protocol`; local-only preservation root. Unique patch freezes an SMX focused evaluation protocol; no current runtime delta to migrate.
- `fix/chatgpt-web-exact-ingress-20260927` — `wip_evidence_prototype`; local-only preservation root. WIP evidence/working-set capture prototype retained during middleware/ingress investigation; archival provenance only.
- `fix/err1214-preserve-human-wire` — `root_cause_analysis_only`; local-only preservation root. Unique commits are root-cause/attribution analysis documents for ERR1214; preserve as incident evidence.
- `fix/middleware-m1-currentness-gen120-20260926` — `retired_middleware`; local-only preservation root. Full middleware v0.2 implementation/qualification history; Phase12 retired its runtime/worktree while preserving this branch intentionally.
- `fix/runtime-config-p0-main-20260915` — `qualification_evidence_only`; exact remote backup. The only current-main-unique tip content is P0 qualification documentation; runtime configuration has since advanced.
- `integration/smc-p4-live-fresh-20260921` — `qualification_evidence_only`; local-only preservation root. Fresh P4-LIVE ActionRef integration qualification snapshot; no active deployment/merge authority.
- `plan/skill-execution-ledger-gen120-20260926` — `plan_only`; local-only preservation root. Progressive skill Execution Ledger plan only; subsequent experiment produced no adoption/benefit evidence.
- `preserve/cache-accounting-dirty-20260923` — `wip_preservation`; local-only preservation root. Explicit preserved dirty-worktree cache-accounting files; forensic/WIP archive asset.
- `rescue/r9probe.XF5YIU-f1e102e60` — `rescue_experiment_below_gate`; local-only preservation root. Representative rescue probe for memory-compile experiment; subject records MRR improvement but recall@5 remained below the 60% gate.
- `rescue/r9probe.bHfX1x-255014902` — `rescue_experiment_below_gate`; local-only preservation root. Second content class from the same memory-compile rescue probe; preserve experiment evidence, not promote.
- `research/cloud-continuity-qualification-20260908` — `research_qualification`; local-only preservation root. Three-provider continuity qualification snapshot; research evidence.
- `research/cloud-provider-handoff-20260908` — `research_qualification`; local-only preservation root. Cloud provider handoff/continuity qualification line; current provider runtime has since advanced.
- `research/method-curriculum-20260908` — `research_unpromoted`; local-only preservation root. Curriculum and explicitly unpromoted Method candidates; preserve as research provenance.
- `research/model-protocol-continuity` — `research_qualification_current_mechanics_elsewhere`; local-only preservation root. Protocol-continuity harness/research. Current main already enforces snapshot/version write preconditions and exact evidence/read recovery; retain the experiment as evidence rather than replay its branch.
- `review/agent-qualification-step5-rebuild-20260915` — `frozen_review_gate`; local-only preservation root. Narrow A.5 review-gate rebuild artifact; preserve as governance/review evidence.

## 29 semantically superseded tips

- `chore/ruff-format-repo` — `later_format_gate`; exact remote backup. Current main has later repo-wide Ruff/Pyright/style convergence; replaying an old format-only patch has no unique current semantic value.
- `docs/smc-model-friendly-v01-20260916` — `browser_surface_evolved`; exact remote backup. Current main has later Browser perceive/semantic-execute projection and evidence-quality work; the old model-friendly surface has evolved beyond this tip.
- `feature/learning-plane-p0a-20260910` — `learning_plane_evolved`; local-only preservation root. Learning Plane is present and substantially evolved in current main, including durable Method learning; this P0A assembly is an earlier implementation.
- `feature/web-model-provider-admin-20260909` — `provider_admin_evolved`; exact remote backup. Current Web/runtime has later provider/model administration and per-session model authority; the old admin implementation is no longer the current contract.
- `feature/webui-human-turn-queue-20260910` — `human_turn_queue_evolved`; local-only preservation root. Current main contains human_turn_queue plus later explicit interjection/CAS and recovery semantics.
- `feature/webui-live-parity-20260909` — `web_product_evolved`; local-only preservation root. Current WebUI contains later durable session/workspace/composer/runtime controls; this broad product-parity snapshot is an older implementation line.
- `feature/webui-product-closure-on-integration-20260909` — `web_product_evolved`; local-only preservation root. Current WebUI contains later durable product/session/workspace controls; this closure-on-integration line is an older implementation.
- `feature/webui-tool-activity-parity-20260909` — `tool_activity_evolved`; exact remote backup. Current main has `webui/src/core/toolActivity.ts`, `projectToolActivityMessages`, and later tool-activity tests/qualification.
- `fix/cache-fold-corrective-main-20260917` — `cache_fold_evolved`; local-only preservation root. Current main has later cache-fold convergence/same-run corrections, including `ddd108a2e` and adjacent cache-history work.
- `fix/cache-fold-same-run-fresh-20260917` — `cache_fold_evolved`; local-only preservation root. Current main has later same-run cache-prefix preservation (`6d6347cca`) and subsequent context/cache refinements.
- `fix/cache-health-comparable-regression` — `cache_health_successor`; local-only preservation root. Current main implements comparable cache-transition classification and hit-regression accounting; later main commits include `b4be6f95a` and `d4f00c497`.
- `fix/context-t2-archive-order-20260911` — `history_architecture_replaced`; local-only preservation root. The T2/T3/T4 flags were default-off experiments and are absent from current runtime. Current main instead uses atomic tool groups, ingress/task anchors, recoverable first views, and later compaction protections that cover the safety intent under a different architecture.
- `fix/evolution-213965a1-20260920` — `service_verify_successor`; local-only preservation root. Current `service_control.py` directly contains the later `no_manifest_skip`/manifest-window logic and typed `verify_targets`, so this repair is already represented.
- `fix/mem-citations-index-anchor` — `memory_citation_successor`; exact remote backup. Current main has later memory-citation extraction/index fixes (including `26da66f72`) and this branch itself primarily preserves the earlier report.
- `fix/projection-test-grace-env-leak` — `test_environment_no_longer_fails`; exact remote backup. On current main the target projection suite passes 23/23 even with `LFL_TOOL_WORKING_SET_GRACE_GROUPS=3`; the branch-only autouse fixture is no longer required.
- `fix/runtime-config-p1-dc2a-20260915` — `typed_runtime_config_successor`; local-only preservation root. Current main uses later typed Settings/runtime resolver/service-scoped configuration and exact recovery wiring; the P1 line is an earlier convergence implementation.
- `fix/runtime-config-sot-20260914` — `typed_runtime_config_successor`; local-only preservation root. Current main has the later typed runtime configuration/resolver architecture, superseding the initial file-backed SoT implementation.
- `fix/service-control-p0a1-49cd-20260916` — `service_control_successor`; exact remote backup. Current service-control has multiple later bootstrap/currentness/identity/host-local-time hardenings and remains production-qualified.
- `fix/stable184-subagent-cleanup-20260916` — `subagent_lifecycle_successor`; exact remote backup. Current main contains later subagent cancellation/settlement/lifecycle qualification; `fe209380a` is a later cleanup qualification on main.
- `fix/tool-schema-first-call-ready-20260912` — `first_call_contract_successor`; local-only preservation root. Current registry has `_COMPACT_PARAMETER_DESCRIPTIONS` and later first-call-ready schema contracts; main includes later `091a88ef5`.
- `fix/web-evolution-approval-20260909` — `approval_successor`; exact remote backup. Current main has Web + Feishu evolution approval flows and a later EvolutionPanel test surface.
- `fix/web-new-session-model-authority-20260921` — `session_model_authority_successor`; local-only preservation root. Current Web routes implement session-scoped model override/new-session inheritance and current tests cover the authority contract.
- `fix/web-workspace-busy-feedback-20260919` — `workspace_busy_successor`; local-only preservation root. Current API/UI contains `workspace_busy` handling and actionable workspace-switch feedback tests.
- `fix/webui-katex-code-pollution-20260918` — `markdown_successor`; local-only preservation root. Current Markdown renderer explicitly isolates code from KaTeX preprocessing and includes later shell-code regression coverage.
- `hotfix/web-evolution-approval-live-20260909` — `approval_successor`; exact remote backup. Current main has the later converged evolution approval implementation and UI review/receipt flow.
- `integration/capability-recovery-main-20260915` — `evidence_recovery_successor`; local-only preservation root. Current main has source-resolution/evidence reuse, exact read-range recovery and recovery contracts; the integration-line recovery intent is now represented directly.
- `m1-g1-scorer-fix-pre-rebase-20260915` — `exact_successor_commits_in_main`; local-only preservation root. The three intents have direct current-main successors: nonconvergence fuse `24705c077`, Memory observation-history compatibility `f1bfa11d1`, and schema-mismatch/corruption classification `29c92087d`.
- `public/promotion-20260908` — `runtime_baseline_advanced`; local-only preservation root. This was an older promoted runtime/provider baseline. Current main has materially advanced provider, runtime, continuity, Web and safety layers, so it is not a current integration source.
- `review/webui-true-interject-fresh-20260919` — `interjection_successor`; local-only preservation root. Current main contains later human-turn queue/interjection behavior, recovery, and explicit CAS steering semantics beyond this review tip.

## Next phase

**Recommended Phase 19A:** create one private exact-ref Git bundle for all 67 tips, plus a ref→HEAD manifest, SHA256, `git bundle verify`, and an isolated bare-repo restore drill. Do **not** delete refs in that phase until another human checkpoint.

If that archive is verified and the owner later authorizes retirement, all 67 tips become candidates for local-ref removal, potentially reducing the repository from 70 local branches to the three protected refs: canonical `main`, production, and `archive/root-untracked-eval-bundle-20260929`.

Phase 18 itself changes no branch refs, performs no merge/cherry-pick/rebase, and makes no production change.
