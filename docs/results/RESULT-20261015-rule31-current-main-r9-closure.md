# Rule31 current-main isolation — code review and full R9 closure

Date: 2026-10-15. Goal: `d0a3a009-34d8-4f71-a957-60f0e3254249`.

**Result:** ISOLATED_REVIEW_PASS / CANONICAL_R9_EXIT_0_WITH_SERIAL_RECOVERY / ISOLATED_SOURCE_COMMIT_CREATED. **This is not xdist-all-green or deployment into main.**

## Baseline and exact candidate

- Isolated branch: `fix/rule31-current-main-20261015`; frozen baseline main `db4aaa8565ea0d0cc061b12e5701f5398b53698e`.
- Source local commit: `9c75e91bac76049eb0e9e131f4fd27d32a0ae5bf`; exact 8-file parent-relative Git diff size **24,049 bytes** and SHA-256 `705c094eb0c4b3d6bc82a69bacc0190e0d126d30df8eb9094cc10ddedd681e4f`.
- True independent GLM reviewer child `subagent_b94885b10d36`: completed, PASS P0=0/P1=0/P2=5, reviewed identical source SHA; full receipt in `docs/governance/receipts/RECEIPT-20261015-rule31-current-main-independent-glm53-review.md`.
- Main advanced *concurrently* to `68c5fb688635e400c1127b0b02a49910a2f492dc` (four Jev/knowledge commits), with **no touched-path overlap against the eight files and no change in Rule31 SoT since baseline**. However this frozen branch's R9 does *not* qualify that newer main: its scanner and other code changed independently. A future integration must repeat drift/review/R9 against its own new baseline.

## Source RED → GREEN and prior true failure

1. On the pre-integration main candidate, three Rule31 H2-discovery/first tool-packet regression tests truly failed. The seven-file Rule31 delta repaired them; 61 targeted tests passed.
2. The initial native full R9 then genuinely **exited 1**, xdist **8,741 passed / 146 skipped / 1 failed**, serial **12 passed / 1 failed**. `test_orphan_tmp_and_lock_invisible_to_scan_surfaces` had a fixed `BACKUP_AT=2026-10-08T10:00:00` and by 2026-10-15 12:28 +0800 crossed `RETENTION_PERIOD_DAYS=7`. Production cleaned the aged archive correctly; the “fresh” test expectation was stale. The historical NO_GO record remains immutable at `docs/results/RESULT-20261015-rule31-current-main-r9-no-go.md`.
3. The eighth-file delta fixes only this test to use `backup_module.system_local_now().isoformat()`. No production backup cleanup code, retention policy or global fixture defaults changed. The corrected Rule31/backup/browser adjacent run was **74 passed**.
4. On this exact eight-file staged SHA, original `bash scripts/ci_gate.sh --quick` genuinely **exited 0**: Ruff PASS (new0/changed0), env-pin 853 PASS, Pyright PASS (new0/changed0), candidate WebUI build PASS, tier0 **319 passed / 8,585 deselected / 3 warnings**.

## After-Reviewer full original project R9

No repository CI script, test assertion, retention policy, worker count or baseline was modified to turn a red test green.

| Gate | Observed actual outcome |
| --- | --- |
| Ruff diagnostic ratchet | PASS, new 0 and changed-file diagnostics 0 |
| Test environment declaration | PASS, 853 scanned |
| Pyright diagnostic ratchet | PASS, new 0 and changed-file diagnostics 0 |
| WebUI build from isolated candidate | PASS |
| Tier0 preflight | **319 passed**, 8,585 deselected, 3 warnings |
| xdist full 4 workers | **8,741 passed, 146 skipped, 1 failed, 13 warnings** in 203.73s |
| xdist failed node | `tests/phase4/test_m2_inflight_interrupt.py::test_c_s15_race_two_branches`; interject_pending vs interject_received under concurrent scheduling |
| Built-in serial recheck of affected file | **6 passed, 1 warning** in 18.55s |
| Native CI disposition | `serial 复核绿 = xdist 分布假红（不阻断）`; xdist failure disclosed, not hidden |
| Final guard-report selection | **1 passed**, 29 deselected |
| **Original full CI process** | **PASS / exit 0** (built-in policy) |

This is **not** a claim that every xdist worker passed. The parallel race test is outside the eight changed files, and the project's original gate treats successful serial reproduction of the full affected file as a non-blocking distribution issue. The raw failed node and serial recheck are preserved without skip, changed expectations, retries masquerading as first attempts, or raising a known-red allowance.

Exact ignored full CI log: `data/rule31-current-main-r9-full-after-fixture-20261015.log` SHA-256 `241d23237e57ebb32047dab30c4072dcf2c61d46ebfea6a909c25c9b1d198047`. Original previous failed R9 log remains ignored and unchanged, SHA-256 `e420da8a5caab39c7aba6108fe7374f6a6655a2b076208794e8078a600b0c243`.

## Governance and isolation

- Independent reviewer report fully preserves the five P2 suggestions; none are falsely marked fixed.
- Changed-source safety: `git diff --cached --check` and `scripts/git_security_scan.sh --staged` both PASS for eight files before the local source commit.
- Temporary isolated CI-only Python socket guard SHA-256 `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`; it canary-blocked external DNS/TCP and newly spawned Python/httpx while allowing localhost/AF_UNIX. **Not an OS-wide network firewall; non-Python native egress was not physically proved blocked.** CI API key environment variables were unset and isolated worktree has no `.env`. The deliberately authorized separate GLM review did contact its configured Coding-plan provider without changing Provider settings.
- A full R9 changed exactly 18 known tracked report paths (12 phase3, 1 phase4, 2 phase5, 3 phase6). After the CI terminated, these paths matched an exact whitelist and **only** these were restored. No changes to the dirty main checkout, other agents or Rule28 worktree.
- This local branch was **not** merged into main, pushed, published, deployed or restarted. Production authority, G4 and budgets were not mutated.

## Future merge and rollback

Qualification is **complete only for this frozen isolated branch**. Before any later integration into moving main, review the new baseline and its security scanner; freeze a new exact candidate, obtain applicable independent reviewer terminal and R9 evidence on that integration state. Separate owner authorization is required for merge/push/release/restart. Retain the isolated commits and original logs as forensic/rollback anchors; do not reset other agents' work.
