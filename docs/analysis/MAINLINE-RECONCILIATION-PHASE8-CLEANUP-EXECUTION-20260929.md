# Mainline Reconciliation Phase 8 — Mechanical Cleanup Execution

- Date: 2026-09-29
- Canonical main before evidence commit: `b6fb59451c59b1095814f94cc7a86e1f60af9bd5`
- Result: **PASS**

## Executed scope

- Batch A: deleted **6** unattached local branches already represented by canonical `main`.
- Batch B: removed **37** clean inactive worktrees without force, then deleted their safe local branches.
- Batch C: removed **10** clean inactive worktrees without force and retained all **10** branches with true unique patches.
- Remote branches: **not modified**.

## Net result

- Local branches: **149 → 106** (43 removed).
- Worktrees: **53 → 6** (47 removed).
- Remaining worktrees are exactly the six protected bindings:
  - canonical `main`
  - live production `fix/mobile-copy-user-activation-20260929`
  - preserved root WIP `wip/main-pre-reconcile-20260929`
  - active middleware `fix/middleware-m1-currentness-gen120-20260926`
  - dirty blocked `fix/chatgpt-web-exact-ingress-20260927`
  - dirty blocked `eval/web-gpt-512k-canary-20260927`

## Patch-equivalent non-ancestor deletions

These four local branches were deleted only after `git cherry main <branch>` was revalidated as all-minus (no unique patch):
- `deploy/20260916-anchor-integration`
- `experiment/mem-citations-20260922`
- `deploy/learning-evo20260928-e312b78f`
- `feat/web-chatgpt-model-switch-20260927`

## Preserved invariants

- Production: gen161 / `67ce123c5fa8430ab833610857fbf276d55e589d`; read-only service-control verify PASS.
- Root WIP: 31 tracked modifications; frozen SHA drift=0; index `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`.
- Phase 8C: all 10 retained branches still have positive `git cherry +` unique patches.
- Active middleware process references remain present (`{'middleware_human_loop': 1, 'chrome_profile_process': 12, 'middleware_supervisor': 1}`).
- Both dirty blocked worktrees remain dirty and were not altered.
- No worktree was force-removed.

## Evidence

`docs/analysis/MAINLINE-RECONCILIATION-PHASE8-CLEANUP-EXECUTION-20260929.json` contains the exact batch membership and final state.
