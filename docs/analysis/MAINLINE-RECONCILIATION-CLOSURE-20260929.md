# Mainline Reconciliation — Closure Ledger

- Date: 2026-09-29
- Canonical main before closure evidence commit: `4082dca6518bf9994e2c86ffc7aaa186467657f7`
- Production: `gen161@67ce123c5fa8430ab833610857fbf276d55e589d` — healthy and intentionally not advanced to main
- Result: **CLOSED**

## Final state

- Primary repository root owns canonical `main` and is clean.
- Exactly **2 worktrees** remain: root main and production.
- **106 local branches** remain; branch governance is not part of reconciliation closure.
- Retained archive branch: `archive/root-untracked-eval-bundle-20260929@80f7ff79b51252da162634bbcf391a6a0e3e2017`.
- Production Chrome/CDP lifecycle is independent of retired worktrees and owned from `data/runtime`.
- Production `service_control verify` is PASS at generation 161.

## What closure means

Closure means the repository now has one canonical development mainline with a clean primary root, every removed/retired WIP/worktree asset was classified and preserved before deletion, and current main adds **no failing-test or static-analysis fingerprint beyond the exact gen161 production baseline**. It does **not** mean existing technical debt is zero, nor does it imply production has been deployed to current main.

Known baseline debt remains: **9 pytest failures, 32 Ruff findings, 58 Pyright errors**; all are exact A/B reproductions on gen161. These belong to future debt-remediation work, not reconciliation.

## Preservation anchors

- Eval archive branch: `80f7ff79b51252da162634bbcf391a6a0e3e2017`.
- Phase 14 raw eval manifest SHA256: `d947790a54dc37a3c1e261df763467860ebeeeeff349d2134cdf122bfa69d462`.
- Phase 14 noncanonical manifest SHA256: `9580907e22db86f219d4c538b49ddaf97e9bd787c1291e8f370978de1fd23733`.
- Phase 15 linked-main audit manifest SHA256: `cc879116345863de3663401afc9cc1908ab20ac3d5b0074b13ba813c9f11e955`.

## Phase trace

1. Freeze/inventory dirty root.
2. Resolve semantic overlap.
3. Migrate qualified restart/cache runtime deltas.
4. Recover docs/knowledge and classify untracked assets.
5. Qualify canonical-main cutover.
6. Cut main while preserving root WIP.
7–10. Audit and mechanically collapse historical worktrees/branches while preserving unique patches.
11–12. Decouple production Chrome runtime and retire middleware worktree.
13–15. Audit/preserve root tracked+untracked WIP, restore primary root to main, retire patch-equivalent WIP branch.
16. Requalify from the primary root and prove zero new regression against gen161.

## Next scope

**Phase 17** governs the remaining 106 local branches as a separate lifecycle problem. This closure ledger authorizes no branch deletion.
