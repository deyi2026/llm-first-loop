# Mainline Reconciliation Phase 14 — Root Untracked Audit & Preservation

- Date: 2026-09-29
- Canonical main: `b47163d6b9b527dcf78297e5c4bcb3a531bc6ac0`
- Preserved root: `wip/main-pre-reconcile-20260929@8454c8a9813947173bc5696dcb5d5309d21cdf3b`
- Result: **PRESERVATION COMPLETE — destructive cleanup not started**

## Complete accounting

All **805/805** Phase-1 untracked paths are still present as the exact same set. No path is uncovered.

| Disposition | Count |
| --- | ---: |
| Already byte-identical on canonical main | 18 |
| Already preserved on main with Phase-4 normalization | 1 |
| Superseded prototype; do not migrate | 3 |
| Candidate Method migrated to canonical main | 58 |
| Eval/docs/evidence preserved on archive branch + exact private raw archive | 711 |
| `.log` evidence preserved exact-private only because Git security forbids logs | 9 |
| Tool-local / standalone evidence preserved exact-private only | 4 |
| Regenerable Method embedding lock; keep runtime-only/ignored | 1 |

Total: **805**.

## Candidate Methods

The 58 `data/methods/*/METHOD.md` files all parse under the current `MethodStore`, all remain `status=candidate`, and all have non-empty bodies. Current reflection discovery permits only active/qualified Methods to influence dedup/reuse context, so preservation is behavior-neutral. A 67-test Method/Learning qualification suite passed.

Canonical preservation commit: `b47163d6b9b527dcf78297e5c4bcb3a531bc6ac0`. One Method contained historical machine-specific absolute paths; its canonical copy replaces those with `<prior-environment-root>` / `<repo-root>`. Its exact original bytes are retained in the private noncanonical archive. Security scan passed all 58 committed files.

## Eval / evidence bundle

Exact raw bytes for all **720** selected eval/docs/evidence files are preserved under the Git-ignored private archive `data/private-archive/mainline-reconciliation/phase14/root-untracked-eval-bundle-raw`; manifest SHA256 `d947790a54dc37a3c1e261df763467860ebeeeeff349d2134cdf122bfa69d462` and source-hash mismatch **0**.

A browsable retained branch `archive/root-untracked-eval-bundle-20260929@80f7ff79b51252da162634bbcf391a6a0e3e2017` preserves **711** payload files plus one archive metadata file. Twelve files had machine-local paths normalized; 76 historical files had only excess EOF blank lines normalized. Nine `.log` files remain raw-archive-only because repository security policy prohibits committing log paths. The branch passed the security hook for **712 files**. Broad syntax/structure validation found 0 Python syntax failures, 0 JSON parse failures, and 0 JSONL parse failures.

## Noncanonical local assets

The PDF, `facts.json`, and two `.opencode` local-tool files remain excluded from canonical source per Phase 4. Exact bytes are preserved under `data/private-archive/mainline-reconciliation/phase14/noncanonical-root-assets`; manifest SHA256 `9580907e22db86f219d4c538b49ddaf97e9bd787c1291e8f370978de1fd23733`.

## Root safety

The root WIP remains untouched: **31 tracked modifications, hash drift 0, index `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`**. The original **805 untracked paths have not been deleted or moved**. Phase 14 only copied them for preservation and migrated qualified Method knowledge through a separate worktree.

## Destructive cleanup gate

Phase 15 may now clean the root, but only after an explicit human checkpoint. Safe order:

1. Revalidate both private archive manifests, retained archive branch, and Method preservation commit.
2. Delete only root untracked paths already preserved/superseded; keep the regenerable embedding lock as ignored runtime state.
3. Revalidate the frozen 31 tracked hashes, then restore exactly those tracked WIP paths from the WIP branch HEAD.
4. Remove the linked canonical-main worktree and switch the primary root worktree to `main`.
5. Verify production gen161, root topology, ignored runtime state, and `git cherry main wip/main-pre-reconcile-20260929` all-minus before deleting the local WIP branch.

No destructive root cleanup is performed in Phase 14.
