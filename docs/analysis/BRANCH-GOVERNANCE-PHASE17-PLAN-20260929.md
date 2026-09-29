# Branch Governance Phase 17 — Audit and Plan

- Date: 2026-09-29
- Audit base: `main@aaaeae6002d52f7d722aad467e971cc225c51ac5`
- Result: **AUDIT COMPLETE — no deletion executed**

## Executive result

All 106 local branches are classified. The conservative plan keeps every true unique local tip and deletes only branch pointers whose content/history is already preserved by another retained local branch or by an exact content-equivalent representative.

| Disposition | Count |
| --- | ---: |
| Retain canonical `main` | 1 |
| Retain production | 1 |
| Retain archive | 1 |
| Retain unique-patch tips | 67 |
| Delete candidate: locally contained historical pointer | 31 |
| Delete candidate: exact content duplicate | 5 |
| **Total** | **106** |

Of the 67 retained unique tips, 15 currently have an exact local remote-tracking ref and 52 do not. This is inventory only: **remote reachability is not used as the sole preservation proof**, and no remote-ref deletion is authorized.

## Safety model

1. `main`, production, and the Phase 14 archive branch are unconditional keepers.
2. A branch with a `git cherry main <branch>` `+` patch is never deleted merely because main is newer.
3. A main-unique historical pointer becomes a local deletion candidate only when its HEAD is a proven ancestor of at least one retained local tip.
4. Content-duplicate rescue tips require identical parent, tree, subject, and stable patch-id; one representative is retained per equivalence class.
5. Before any ref deletion, create an ignored private Git bundle containing all 36 candidate refs, record its SHA256, and run `git bundle verify`.
6. Delete local refs only. Never push/delete remote refs. Revalidate all witnesses immediately before mutation.

## Batch A — 31 locally contained historical pointers

- `design/smc-p4-live-g2-s2-red-plan-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `design/smc-p4-live-green2-plan-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `design/smc-p4-live-protocol-20260919` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `docs/smc-ai-native-control-plane-v02-20260919` → retained witness: `feature/smc-execution-binding-p11-20260919`
- `feat/execution-ledger-query-s2-gen120-20260927` → retained witness: `exp/qwen-reliability-s2b-20260927`
- `feat/execution-ledger-shadow-gen120-20260926` → retained witness: `exp/qwen-reliability-s2b-20260927`
- `feature/cognitive-baseline-v01-20260914` → retained witness: `experiment/epistemic-closure-ab-20260914`
- `feature/context-elasticity-20260910` → retained witness: `archive/local-main-pre-convergence-20260911`, `fix/context-t2-archive-order-20260911`
- `feature/learning-plane-20260910` → retained witness: `archive/local-main-pre-convergence-20260911`, `fix/context-t2-archive-order-20260911`
- `feature/smc-execution-binding-p1-20260919` → retained witness: `feature/smc-execution-binding-p11-20260919`
- `feature/smc-p4-live-core-green1-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-g2-s1-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-g2-s2-green-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-g2-s3-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-g2-s4-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-g2-s5-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-qualification-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-red-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-p4-live-v02-prelive-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-semantic-logic-p4-fcr-preflight-20260917` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/smc-semantic-logic-p4-fcr-v02-actionref-20260919` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `feature/webui-product-closure-20260909` → retained witness: `feature/webui-live-parity-20260909`
- `fix/cache-prefix-surface-contract-20260910` → retained witness: `archive/local-main-pre-convergence-20260911`
- `fix/session-health-integrity-20260914` → retained witness: `experiment/common-governance-rerun-20260914`, `experiment/epistemic-closure-ab-20260914`
- `fix/smc-p4-fcr-v02-qualification-isolation-20260919` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `fix/smc-p4-live-r12-target-identity-20260920` → retained witness: `feature/smc-p4-live-v02-live-20260920`
- `hotfix/memory-schema-fail-closed-20260915` → retained witness: `fix/runtime-config-p1-dc2a-20260915`
- `integration/memory-runtime-config-p0-20260915` → retained witness: `fix/runtime-config-p1-dc2a-20260915`
- `merge/lfl-main-history-bridge` → retained witness: `archive/local-main-pre-convergence-20260911`, `fix/context-t2-archive-order-20260911`
- `rescue/deploy-capability-96a-20260915-ba23add01` → retained witness: `fix/runtime-config-p1-dc2a-20260915`, `integration/capability-recovery-main-20260915`
- `rescue/smc-p4-fcr-v02-runner-eae7638c-eae7638c8` → retained witness: `feature/smc-p4-live-v02-live-20260920`

## Batch B — 5 exact content duplicates

Representative: `rescue/r9probe.XF5YIU-f1e102e60`
- parent: `c631b4acc674e40fb100f52b61568405a00adfaa`
- tree: `e4fff9216946fb7d0e47fa17c882a9a99931a9d9`
- stable patch-id: `7f0e2f21ec0269688315bec7f6588b5bc3304ac1`
- delete candidate: `rescue/r9probe.ANftDo-c453fc0df`
- delete candidate: `rescue/r9probe.HisszA-649029cc1`
- delete candidate: `rescue/r9probe.VdAUvk-fb96d0245`
- delete candidate: `rescue/r9probe.x60azn-b1688808e`

Representative: `rescue/r9probe.bHfX1x-255014902`
- parent: `c631b4acc674e40fb100f52b61568405a00adfaa`
- tree: `c0a873606ea436cb6a246b90a4910efa5f8de9f8`
- stable patch-id: `c4a264d76cff7655fc6ecf09da5532572b6b6762`
- delete candidate: `rescue/r9probe.Sdarnh-ccd5e3091`

## Retained 67 unique-patch tips

- `(root)`: 3
- `archive`: 1
- `audit`: 2
- `backup`: 1
- `benchmark`: 1
- `chore`: 1
- `docs`: 3
- `eval`: 5
- `exp`: 2
- `experiment`: 5
- `feature`: 8
- `fix`: 21
- `hotfix`: 1
- `integration`: 2
- `plan`: 1
- `preserve`: 1
- `public`: 1
- `rescue`: 2
- `research`: 4
- `review`: 2

Exact list:

- `archive/local-main-pre-convergence-20260911` — `+23/-7` vs main; local-only preservation
- `audit/d8f3-context-replay-20260921` — `+1/-0` vs main; local-only preservation
- `audit/m1-g2-gate-report-20260915` — `+1/-1` vs main; local-only preservation
- `backup/20260819-after-3am` — `+5/-2` vs main; exact remote-tracking: `mainrepo/backup/20260819-after-3am`, `oldarch20260908/backup/20260819-after-3am`
- `benchmark/reliable-v0-20260921` — `+1/-0` vs main; local-only preservation
- `chore/ruff-format-repo` — `+1/-0` vs main; exact remote-tracking: `lfl/chore/ruff-format-repo`
- `docs-plan-20260914-preserved` — `+1/-0` vs main; local-only preservation
- `docs/agent-qualification-envelope-v0.1-20260915` — `+1/-3` vs main; local-only preservation
- `docs/middleware-envelope-protocol-v0.1-20260925` — `+6/-0` vs main; local-only preservation
- `docs/smc-model-friendly-v01-20260916` — `+5/-68` vs main; exact remote-tracking: `lfl/docs/smc-model-friendly-v01-20260916`
- `eval/fc2c-live-runtime-20260913` — `+2/-0` vs main; local-only preservation
- `eval/p2a-older-history-eval-20260928` — `+4/-0` vs main; local-only preservation
- `eval/p2a-receipt-ab-20260928` — `+8/-0` vs main; local-only preservation
- `eval/stagec-tool-surface-c1-20260928` — `+3/-0` vs main; local-only preservation
- `eval/web-gpt-512k-canary-20260927` — `+1/-1` vs main; local-only preservation
- `evo-20260914-exec-surface-followup` — `+1/-2` vs main; exact remote-tracking: `lfl/evo-20260914-exec-surface-followup`
- `exp/execution-efficiency-fcr-p2-gen120-20260926` — `+3/-0` vs main; local-only preservation
- `exp/qwen-reliability-s2b-20260927` — `+6/-0` vs main; local-only preservation
- `experiment/common-governance-activation-20260913` — `+1/-0` vs main; local-only preservation
- `experiment/common-governance-rerun-20260914` — `+5/-1` vs main; local-only preservation
- `experiment/epistemic-closure-ab-20260914` — `+7/-1` vs main; local-only preservation
- `experiment/retrieval-ab-20260922` — `+2/-0` vs main; local-only preservation
- `experiment/s1-checkpoint-producer-20260906` — `+1/-0` vs main; local-only preservation
- `feature/learning-plane-p0a-20260910` — `+7/-2` vs main; local-only preservation
- `feature/smc-execution-binding-p11-20260919` — `+9/-0` vs main; exact remote-tracking: `lfl/review/smc-execution-binding-p11-20260919`
- `feature/smc-p4-live-v02-live-20260920` — `+29/-26` vs main; exact remote-tracking: `lfl/review/smc-p4-live-v02-qualified-v01-20260920`
- `feature/web-model-provider-admin-20260909` — `+3/-0` vs main; exact remote-tracking: `lfl/feature/web-model-provider-admin-20260909`
- `feature/webui-human-turn-queue-20260910` — `+1/-0` vs main; local-only preservation
- `feature/webui-live-parity-20260909` — `+7/-0` vs main; local-only preservation
- `feature/webui-product-closure-on-integration-20260909` — `+5/-0` vs main; local-only preservation
- `feature/webui-tool-activity-parity-20260909` — `+1/-0` vs main; exact remote-tracking: `lfl/feature/webui-tool-activity-parity-20260909`
- `fix/agentpilot-tool-contracts-20260912` — `+1/-1` vs main; local-only preservation
- `fix/cache-fold-corrective-main-20260917` — `+1/-0` vs main; local-only preservation
- `fix/cache-fold-same-run-fresh-20260917` — `+1/-1` vs main; local-only preservation
- `fix/cache-health-comparable-regression` — `+1/-0` vs main; local-only preservation
- `fix/chatgpt-web-exact-ingress-20260927` — `+1/-0` vs main; local-only preservation
- `fix/context-t2-archive-order-20260911` — `+13/-1` vs main; local-only preservation
- `fix/err1214-preserve-human-wire` — `+3/-0` vs main; local-only preservation
- `fix/evolution-213965a1-20260920` — `+2/-0` vs main; local-only preservation
- `fix/mem-citations-index-anchor` — `+1/-1` vs main; exact remote-tracking: `lfl/fix/mem-citations-index-anchor`
- `fix/middleware-m1-currentness-gen120-20260926` — `+34/-0` vs main; local-only preservation
- `fix/projection-test-grace-env-leak` — `+1/-0` vs main; exact remote-tracking: `lfl/fix/projection-test-grace-env-leak`
- `fix/runtime-config-p0-main-20260915` — `+1/-2` vs main; exact remote-tracking: `lfl/review/runtime-config-p0-main-20260915`
- `fix/runtime-config-p1-dc2a-20260915` — `+7/-3` vs main; local-only preservation
- `fix/runtime-config-sot-20260914` — `+1/-0` vs main; local-only preservation
- `fix/service-control-p0a1-49cd-20260916` — `+1/-0` vs main; exact remote-tracking: `lfl/review/service-control-p0a1-bootstrap-20260916`
- `fix/stable184-subagent-cleanup-20260916` — `+1/-2` vs main; exact remote-tracking: `lfl/review/stable184-subagent-cleanup-fresh-20260916`
- `fix/tool-schema-first-call-ready-20260912` — `+1/-0` vs main; local-only preservation
- `fix/web-evolution-approval-20260909` — `+1/-0` vs main; exact remote-tracking: `origin/fix/web-evolution-approval-20260909`
- `fix/web-new-session-model-authority-20260921` — `+1/-0` vs main; local-only preservation
- `fix/web-workspace-busy-feedback-20260919` — `+1/-0` vs main; local-only preservation
- `fix/webui-katex-code-pollution-20260918` — `+1/-0` vs main; local-only preservation
- `hotfix/web-evolution-approval-live-20260909` — `+1/-0` vs main; exact remote-tracking: `origin/hotfix/web-evolution-approval-live-20260909`
- `integration/capability-recovery-main-20260915` — `+5/-0` vs main; local-only preservation
- `integration/smc-p4-live-fresh-20260921` — `+1/-0` vs main; local-only preservation
- `m1-g1-scorer-fix-pre-rebase-20260915` — `+3/-3` vs main; local-only preservation
- `plan/skill-execution-ledger-gen120-20260926` — `+1/-0` vs main; local-only preservation
- `preserve/cache-accounting-dirty-20260923` — `+1/-0` vs main; local-only preservation
- `public/promotion-20260908` — `+2/-0` vs main; local-only preservation
- `rescue/r9probe.XF5YIU-f1e102e60` — `+1/-0` vs main; local-only preservation
- `rescue/r9probe.bHfX1x-255014902` — `+1/-0` vs main; local-only preservation
- `research/cloud-continuity-qualification-20260908` — `+1/-0` vs main; local-only preservation
- `research/cloud-provider-handoff-20260908` — `+1/-0` vs main; local-only preservation
- `research/method-curriculum-20260908` — `+1/-0` vs main; local-only preservation
- `research/model-protocol-continuity` — `+2/-0` vs main; local-only preservation
- `review/agent-qualification-step5-rebuild-20260915` — `+1/-5` vs main; local-only preservation
- `review/webui-true-interject-fresh-20260919` — `+2/-0` vs main; local-only preservation

## Execution plan after human authorization

1. Revalidate `main` clean, 2 worktrees, 106 branch refs, protected heads, and production gen161 PASS.
2. Create a private ignored Git bundle containing all 36 candidate refs plus a ref→HEAD manifest; verify bundle and SHA256.
3. Re-run ancestry witnesses for Batch A and parent/tree/patch-id equivalence for Batch B.
4. Delete only the 36 local branch refs using ordinary Git branch operations. If normal `-d` refuses solely because the branch is not merged to `main`, use explicit local `git branch -D` only after the preservation proof and bundle are current.
5. Verify branch count becomes 70; all 70 retained heads are unchanged; worktrees remain 2; production gen161 still PASS; bundle still verifies.
6. Commit an execution receipt separately. No remote refs are modified.

## Not in this deletion batch

The 67 retained unique tips remain intentionally retained. They are not “unclassified debt”: each still contains content not represented by canonical main and is a preservation root after this audit. Any later semantic integration, archival bundling, or retirement is a separate review.
