# Mainline Reconciliation Phase 10 — Preserved Worktree Cleanup

- Date: 2026-09-29
- Canonical main before evidence commit: `08be00ca711668043d98bcd5e7fbde0e0de3ad27`
- Result: **PASS**

## Executed cleanup

Phase 10 removed the two worktrees whose valuable content was preserved and qualified in Phase 9. Both removals used normal `git worktree remove`; **no force flag** was used and **no local or remote branch was deleted**.

1. `fix/chatgpt-web-exact-ingress-20260927`
   - retained branch head: `ade11de5fdba186f2c77c844ea93e975bd512364`
   - worktree was clean before removal
   - branch remains a true unique patch against main and is intentionally retained

2. `eval/web-gpt-512k-canary-20260927`
   - retained branch head: `94cfad505ffb887e5078eab94ed9ee72bb1f5ee9`
   - deleted only the Phase 9-classified generated payload `lfl_snapshot_1_4m.txt` (1,400,000 bytes; SHA256 `81166c2355dc7d6a74f446343a57e825a43cb582bd861eb9c1d708971b4e81cc`) and generated `__pycache__`
   - verified worktree clean before removal
   - runtime commit `aa71c7a5a...` remains patch-equivalent to main while archive commit `94cfad505...` remains unique and retained

## Final topology

Worktrees: **6 → 4**. The exact remaining set is:

- canonical `main`
- production `fix/mobile-copy-user-activation-20260929`
- preserved root WIP `wip/main-pre-reconcile-20260929`
- active middleware `fix/middleware-m1-currentness-gen120-20260926`

Local branch count remains **106**; Phase 10 deleted zero branches.

## Safety verification

- Production `service_control verify`: **PASS**, generation **161**; production was not restarted.
- Preserved root WIP: **31 tracked modifications**, hash drift **0**, index tree `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`.
- Active middleware worktree still has live supervisor/human-loop/Chrome-profile process references and remains untouched.
- Removed worktree directories are absent.
- Both preserved branches resolve to their exact qualified heads after worktree removal.

## Result

Phase 10 closes the two Phase 9 preservation worktrees without losing their unique branch history or archived evidence. Further topology reduction would require a separate decision about the active middleware worktree and/or the preserved root WIP; neither is mechanically cleanup-safe under the current evidence.
