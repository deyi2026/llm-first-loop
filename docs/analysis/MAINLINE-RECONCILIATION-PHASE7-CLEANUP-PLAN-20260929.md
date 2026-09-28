# Mainline Reconciliation Phase 7 — Cleanup Audit

- Date: 2026-09-29
- Canonical main before this evidence commit: `0f8e7b3073d7903bb7d66f49e616a16333b23535`
- Production: gen161 / `67ce123c5fa8430ab833610857fbf276d55e589d`
- Result: **AUDIT COMPLETE — no cleanup performed**

## Decision rules

- Worktree removal and branch deletion are separate decisions.
- A worktree is removable only when it is clean, inactive, and is not canonical main, live production, or the preserved dirty root WIP.
- A local branch is deletion-safe only when it is not special/dirty/active and its content is already represented by canonical `main`: either the head is an ancestor of `main`, or every divergent commit is patch-equivalent according to `git cherry`.
- Any branch with at least one `git cherry` `+` patch is retained.
- No remote branch deletion is authorized by this phase.
- Dirty worktrees are never force-removed.

## Inventory summary

- Worktrees: **53** total
  - safe worktree-remove candidates: **47**
  - canonical main / live production / preserved root WIP / active middleware: **4 MUST KEEP**
  - other dirty worktrees: **2 BLOCKED**
- Local branches: **149** total
  - safe local branch-delete candidates: **43**
  - branches with true unique patches: **100 RETAIN**
  - special/dirty/active branches: **6 MUST KEEP/BLOCKED**

## Hard keep / blocked set

- `main` — canonical main in `.worktrees/mainline-reconcile-gen161-20260929`.
- `fix/mobile-copy-user-activation-20260929` — live production code root; gen161 / `67ce123c5fa8430ab833610857fbf276d55e589d`.
- `wip/main-pre-reconcile-20260929` — root preserved WIP; 31 tracked modifications; frozen hash drift=0; index `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`.
- `fix/middleware-m1-currentness-gen120-20260926` — active middleware processes still reference its worktree; types: `{'middleware_human_loop': 1, 'chrome_profile_process': 12, 'middleware_supervisor': 1}`.
- `fix/chatgpt-web-exact-ingress-20260927` — dirty: `src/llm_loop/tools/evidence_shadow.py`, `src/llm_loop/tools/registry.py`.
- `eval/web-gpt-512k-canary-20260927` — dirty source plus untracked eval/test assets under `evals/web_gpt_long_context_512k/` and `tests/unit/test_chatgpt_page_send_transient.py`.

## Proposed cleanup batches

### Batch A — unattached local branches safe now (6)

- `deploy/20260916-anchor-integration`
- `experiment/mem-citations-20260922`
- `feat/worktree-lifecycle-evo-20260920`
- `fix/chatgpt-surface-background-20260927`
- `reconcile/mainline-gen161-20260929`
- `tmp-integration-check-20260924`

### Batch B — clean inactive worktrees + branch deletion after removal (37)

- `deploy/gen148-ingress-clean-20260927`
- `deploy/learning-evo20260928-e312b78f`
- `feat/chatgpt-binding-notify-outlet-20260928`
- `feat/chatgpt-binding-telemetry-alerts-20260928`
- `feat/chatgpt-session-binding-20260928`
- `feat/chatgpt-session-observability-gc-20260928`
- `feat/deepseek-web-provider-20260927`
- `feat/learning-method-semantic-20260926`
- `feat/service-scoped-semantic-config-20260926`
- `feat/web-chatgpt-model-switch-20260927`
- `feat/web-gpt-ingress-budget-20260927`
- `feat/web-gpt-reasoning-context-20260927`
- `feat/web-progress-card-20260927`
- `fix/chatgpt-surface-project-drift-20260927`
- `fix/code-nav-hardening-20260928`
- `fix/convergence-fingerprint-canonical-20260926`
- `fix/deepseek-dsml-envelope-20260927`
- `fix/deepseek-tool-arguments-20260927`
- `fix/experience-semantic-qualification-20260926`
- `fix/gen151-learning-on-gen149-20260928`
- `fix/learning-cross-workspace-retry-20260926`
- `fix/lfrt-status-llama-observer-20260928`
- `fix/local-time-direct-tools-20260926`
- `fix/recent-dialogue-continuity-20260927`
- `fix/runtime-knowledge-path-bootstrap-20260926`
- `fix/schema-token-accounting-p0a-20260922`
- `fix/semantic-stabilization-deploy-20260926`
- `fix/service-control-time-order-20260927`
- `fix/web-auth-mobile-cookie-20260928`
- `fix/web-docs-promotion-20260926`
- `fix/web-gpt-context-parity-20260927`
- `fix/web-gpt-ingress-guard-deploy-20260927`
- `fix/web-gpt-reset-retry-20260927`
- `fix/web-gpt-ui-reasoning-effort-20260927`
- `fix/web-longrun-continuity-20260927`
- `fix/web-mobile-copy-hardening-20260928`
- `fix/web-product-audit-20260924`

### Batch C — remove worktree only; retain unique-patch branch (10)

- `benchmark/reliable-v0-20260921`
- `docs/middleware-envelope-protocol-v0.1-20260925`
- `eval/p2a-older-history-eval-20260928`
- `eval/p2a-receipt-ab-20260928`
- `eval/stagec-tool-surface-c1-20260928`
- `exp/execution-efficiency-fcr-p2-gen120-20260926`
- `exp/qwen-reliability-s2b-20260927`
- `feat/execution-ledger-query-s2-gen120-20260927`
- `feat/execution-ledger-shadow-gen120-20260926`
- `plan/skill-execution-ledger-gen120-20260926`

### Batch D — blocked dirty worktrees

- `fix/chatgpt-web-exact-ingress-20260927`: preserve/review its two modified source files before any removal.
- `eval/web-gpt-512k-canary-20260927`: preserve/review modified ChatGPT page logic plus its untracked 512k evaluation/test artifacts before any removal.

## Safety gates before executing any cleanup

1. Re-read production deployment/manifests and confirm the production code root has not changed into a candidate path.
2. Re-scan live processes for worktree path references; any candidate with a live reference is removed from the cleanup set.
3. Re-run `git status --porcelain` on every worktree immediately before removal; any non-empty status blocks removal.
4. For each branch deletion, re-evaluate main ancestry / `git cherry`; any new `+` patch blocks deletion.
5. Re-verify preserved root WIP hashes/index after the cleanup batch.
6. Never use force removal or remote branch deletion in the mechanical cleanup batch.

## Evidence file

`docs/analysis/MAINLINE-RECONCILIATION-PHASE7-CLEANUP-AUDIT-20260929.json` contains the complete 53-worktree and 149-branch inventory and classifications.
