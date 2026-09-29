# Mainline Reconciliation Phase 12 — Production Chrome Decoupling + Middleware Worktree Retirement

- Date: 2026-09-29
- Canonical main before evidence commit: `7e80475e3108cd85586c47395df683d1975b2f53`
- Result: **PASS**

## Executed retirement

- Revalidated middleware turn-10 at `armed` with no ingress/engine/final/recovery block.
- Gracefully stopped the middleware supervisor/runner while Chrome remained live.
- Moved the 72-file / 11,012,051-byte private middleware runtime evidence tree to a Git-ignored archive; manifest SHA256 `f6e5fca9cec43151826f0bec4196f85d6bef096ceab5e2999df3807cf678aaf2`.
- Migrated the authenticated Chrome profile out of `.worktrees` into `data/runtime/chatgpt-web-chrome-profile` and installed independent launchd owner `local.llmfirstloop.chatgpt-web-chrome` on loopback 9229.
- User re-authentication was required after the controlled restart. Canonical `ChatGPTSurface` then recovered the persisted production lease and rebound the stale target while preserving conversation identity.
- Real web-gpt smoke before worktree retirement returned exact `PHASE12_WEBGPT_OK`; after physical worktree removal a second smoke returned exact `PHASE12_POSTRETIRE_OK`. Both had zero tool calls and `finish_reason=stop`.
- Removed `.worktrees/middleware-m1-currentness-gen120-20260926` with plain `git worktree remove`, no force.
- Retained `fix/middleware-m1-currentness-gen120-20260926@101beba03604479b80585caad6707fe65935f541`; it still carries 34 unique commits.

## Residual-state correction

R7 preflight exposed additional worktree-local `data/` state. An initial whole-`data/` preservation move temporarily made tracked `data/methods`/calibration files appear deleted. Before retirement, all tracked data was restored authoritatively from branch HEAD; the redundant private archive was retained; only truly generated ignored caches (`__pycache__`, pytest/ruff caches, `.DS_Store`) were removed. Final pre-remove worktree state was clean with zero ignored/untracked residue, zero process refs, and zero open handles.

Residual archive manifest SHA256: `8a2599353fc2f062b613b2fb9ee6ead4fe4628bba5c560c32ef3877066bca51f`.

## Final topology and invariants

- Worktrees: **3** — canonical `main`, production `fix/mobile-copy-user-activation-20260929`, preserved root WIP `wip/main-pre-reconcile-20260929`.
- Local branches: **106**; middleware branch retained.
- Production: `service_control verify` **PASS**, generation **161**; production services were not restarted.
- Preserved root WIP: **31 tracked modifications**, hash drift **0**, index `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`.
- Chrome lifecycle is independent of the retired middleware worktree and remains launchd-managed from `data/runtime`.
- No remote ref was changed.

Phase 12 therefore closes the last runtime-specific worktree while retaining all unique middleware history and preserving production web-gpt capability.
