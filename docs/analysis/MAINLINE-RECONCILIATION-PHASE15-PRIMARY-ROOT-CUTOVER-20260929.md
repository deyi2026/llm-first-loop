# Mainline Reconciliation Phase 15 — Primary Root Cutover & WIP Retirement

- Date: 2026-09-29
- Canonical main before this evidence commit: `4894979bdf299ce1037b214a79f9bc735ae20633`
- Result: **PASS**

## Executed cleanup

- Revalidated every one of the 805 Phase-14 untracked assets immediately before deletion: **0 missing / 0 hash mismatch**.
- Deleted exactly **804** paths already preserved or superseded. Kept the single regenerable Method embedding lock, which current `main` ignores.
- Revalidated Phase-14 private archives and production, then restored exactly the **31** frozen tracked WIP paths from `wip/main-pre-reconcile-20260929` HEAD. Root tracked diff became zero.

## Linked canonical-main worktree retirement

The temporary linked canonical-main worktree contained 2,312 ignored artifacts. It had no tracked/nonignored changes, no process references, and no open handles. Its `.env` SHA256 matched the primary root `.env` exactly.

Potentially valuable ignored `data/audit` residue was exact-byte archived before removal: **1,130 files / 3,632,628 bytes**, manifest SHA256 `cc879116345863de3663401afc9cc1908ab20ac3d5b0074b13ba813c9f11e955`. Remaining WebUI build products and Python/test/lint caches were reproducible generated state and were deleted. The worktree then had zero ignored/status entries and was removed with plain `git worktree remove` — no force.

## Primary root ownership

The repository primary root was switched from the preserved WIP branch to canonical `main@4894979bdf299ce1037b214a79f9bc735ae20633`. Pre-evidence tree: `5bd4ee6ea1b56aaaafd0fa0d306abbebcc3d93b2`. Final topology before this evidence commit is **2 worktrees**: primary root `main` and production `fix/mobile-copy-user-activation-20260929`.

## WIP branch retirement

Immediately before branch deletion:

- branch head: `8454c8a9813947173bc5696dcb5d5309d21cdf3b`
- attached worktree: **false**
- `git cherry main wip/main-pre-reconcile-20260929`: both entries were `-`
- retained archive branch: `archive/root-untracked-eval-bundle-20260929@80f7ff79b51252da162634bbcf391a6a0e3e2017`

Normal `git branch -d` refused because the historical divergent ancestry is not merged. Since patch equivalence was explicitly proven and Phase 15 retirement had been authorized, the local WIP branch was deleted with `git branch -D`. No remote ref was changed.

## Final acceptance

- Private archive integrity: Phase-14 eval raw **720/720**, Phase-14 noncanonical **5/5**, Phase-15 linked-main audit residue **1,130/1,130**, all hash-valid.
- Root MethodStore: **547** records; **542 candidate**; **2 active/qualified**.
- Chrome lifecycle: launchd running from root `data/runtime`; CDP healthy on `127.0.0.1:9229`.
- Real root-main web-gpt smoke: exact `PHASE15_ROOT_MAIN_OK`, 0 tool calls, `finish_reason=stop`.
- Production `service_control verify`: **PASS / generation 161**; production was not restarted.
- Local branches: **106**. WIP branch absent; archive branch retained.
- Root status: clean.

Phase 15 closes the preserved dirty-root lifecycle: canonical `main` again owns the primary worktree, all unique untracked value was preserved before cleanup, and the patch-equivalent local WIP branch is retired.
