# Branch Governance Phase 17 — Execution Receipt

- Date: 2026-09-29
- Audit commit: `1de84408828ea77524d465cf87815a71940ed724`
- Main before this receipt commit: `1722e33e247c915b3dcc121ae63315ffb86a1ac5`
- Result: **PASS**

## Concurrent assets resolved first

The deletion flow stopped when four new Learning Methods and a root `deliverables/` directory appeared. The four Methods are valid `status=candidate` learning assets and were committed separately as `a9f4bc1e9faf463b22a33fab4a771802a8af0c3c` after **91/91** focused Method/Learning tests and security checks.

The five `deliverables/` files are business outputs, not source assets. They were left byte-for-byte in place and `/deliverables/` was added to `.gitignore` in `1722e33e247c915b3dcc121ae63315ffb86a1ac5`. Aggregate filename/hash/size snapshot SHA256: `e732627d0e290fc2c04eab7d0d5c069a7b1d6bdcb47ce5da4c90bfd81e5d914e`. No deliverable file was deleted or modified by Phase 17.

## Private recovery bundle

Before branch deletion, all 36 candidate refs were frozen into the Git-ignored private bundle:

`data/private-archive/branch-governance/phase17/ref-backup-20260929/phase17-delete-candidates.bundle`

- bundle size: **14,667,327 bytes**
- bundle SHA256: `2d00df7ae5ea11682fa434b947f894721a6fa77271c1f82c35522a47082caa2e`
- manifest SHA256: `4a0b850d6d2fd08c421f5f9876d41fff2177000e6b063c8831b329b9bed637b1`
- `git bundle verify`: **PASS; complete history**
- `git bundle list-heads`: **36/36 exact refs**

The manifest also freezes all 70 retained refs. Remote refs are not part of the mutation scope.

## Immediate pre-delete proof

- 36/36 candidate refs matched audited heads.
- Batch A: **31/31** local-containment ancestry witnesses PASS.
- Batch B: **5/5** exact duplicate proofs PASS (same parent, tree, subject, stable patch-id as retained representative).
- Root clean; worktrees=2; production gen161 PASS.
- Remote-ref snapshot SHA256: `fc8dc145f2556cf52392382f50dd3cc436427e54d9e1b2dcaa8a72346e4587a5`.

## Deletion execution

- Batch A: 31 historical pointers deleted.
- Batch B: 5 exact duplicate rescue pointers deleted.
- Total local refs deleted: **36**.
- Branch count: **106 → 70**.
- Delete modes: ordinary `git branch -d`: **1**; local `git branch -D` after normal ancestry refusal and current preservation proof: **35**.
- Remote refs modified: **no**.
- Production restart/publish: **no**.

## Acceptance before this receipt commit

- retained heads: **70/70 exact**
- deleted candidate refs absent: **36/36**
- private bundle: **verify PASS**, still advertises all 36 deleted refs
- worktrees: **2** (root main + production)
- root: **clean**
- production: **gen161 PASS**
- remote-ref snapshot: unchanged

Phase 17 therefore reduces local branch pointers without sacrificing any audited unique local history: 67 unique-patch preservation tips plus `main`, production, and the retained archive branch remain.
