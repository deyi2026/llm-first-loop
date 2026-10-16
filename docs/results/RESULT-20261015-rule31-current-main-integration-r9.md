# Rule31 2026-10-15 latest-main isolated integration and R9 closure

## Decision

**ISOLATED_SOURCE_COMMITTED / INDEPENDENT_REVIEW_CHAIN_PASS / CANONICAL_FULL_R9_PASS / NOT_DEPLOYED.**

This is the NEW current-main requalification following the earlier completed Rule31 Goal `ebd586f5-4d28-49bd-aab1-80b26f708c22`. This report is limited to the isolated branch `fix/rule31-current-main-integration-20261015`, based on main `db4aaa8565ea0d0cc061b12e5701f5398b53698e`. No `main` merge, push, publish, restart, production/G4 change, or live Provider qualification took place. The concurrent, unfinished Rule28 P0-B Goal is independent and was not checkpointed or changed by this task.

## Source and scope

| Item | Attested value |
| --- | --- |
| Main baseline | `db4aaa8565ea0d0cc061b12e5701f5398b53698e` |
| Rule31 source integration commit (7 paths) | `45b11409376b81ce8aa84e80f43e35301f8b4d83` |
| Test-only backup fixture correction commit (1 path) | `9d395835f8293ddc0d357bbf8c52095bd1a87de2` |
| Full eight-file reviewed and R9-tested diff `git diff --no-ext-diff BASE..HEAD` | 23,979 bytes, SHA-256 `b29fa92693a883598cc362f24617578b39a6f50b04a37dd70eae3a2cc2d1b39a` |
| Prior Rule31 seven-file subdiff / source commit patch | 23,187 bytes, SHA-256 `f858e5eb20c9df60da0702e2d0c0554bcb3b7cf03df6508416777eaa0526e43f` |
| Additional two-line backup-test subdiff | 792 bytes, SHA-256 `db919ebe76c0d6f32593b02675fec3c9fe24916e21fc936ecfe18ecda49cf451` |
| Pre-commit security scan and `git diff --cached --check` | PASS; eight files, no scanner exemption |

Main had three additional commits after the earlier integration baseline `2ad0bc06`; none touched the seven integrated files. The only related main semantic drift changed Rule31's `usage_net` D3 lifecycle explanation in `docs/ai_rules.md`; the isolated integration preserved that current SoT. Rule32/33 and main service-control generation/CAS, notify_external_result, E2/E6 behavior were not rolled back. Bounded `search_records` discovery stays a hint with model-driven applicability judgment, not mandatory universal Method loading. RuleIndex hydration now terminates at the next real H2 rather than incorrectly absorbing the `## 配置扩展` section after Rule33.

### Test-only red-to-green repair

A separate concurrent identical seven-file candidate's full R9 reported one reproducible failure in `tests/unit/test_backup_store_durability.py::test_orphan_tmp_and_lock_invisible_to_scan_surfaces`, initially 8,741 passed / 146 skipped / 1 failed. On 2026-10-15 after 10:00 local time, its fixed `backup_at=2026-10-08T10:00:00` was legitimately older than `RetryPolicy.RETENTION_PERIOD_DAYS=7`; `BackupStore.cleanup()` correctly returned one pruned item, contradicting the test's expected zero. The same test independently reproduced red in this worktree. The isolated repair changes only test setup to a fresh timestamp; it does not change production retention, backup code, or assert strength. Focused RED/GREEN verification: 45 tests passed; positive/negative behavioral canary retained a one-hour-old backup and pruned an eight-day-old backup. The incremental fix has a separate commit and separate independent narrow rereview.

## Independent reviewer provenance

| Review | Physical reviewer child ID | Terminal | Verdict and severity | Qualification |
| --- | --- | --- | --- | --- |
| Seven-file current-main full source review | `subagent_acccbf62cee0` | `6ffd2312-91bc-4d0f-91e3-9997026a7346` | PASS; P0=0, P1=0, P2=7 | PASS for exact seven-file SHA |
| Initial eight-file re-review | `subagent_2cc8e351474e` | `e440ae3b-abb3-4cb9-a6ed-b02a6b6af7af` | Output truncated, no unique verdict/counts | **NOT_QUALIFIED**, not used to authorize R9 |
| Incremental 792-byte test-only narrow review | `subagent_3f0fdd7782f4` | `a167e9af-2d10-49f0-b6ac-223d4e59f3fc` | PASS; P0=0, P1=0, P2=1 | PASS, bound to prior seven-file SHA and combined eight-file SHA |

The last review launcher checked the previously-qualified seven-file receipt fingerprint and unchanged exact seven-file diff, froze the 792-byte incremental diff, and bound the verdict to the combined eight-file diff before R9. All three children had a single recorded `subagent.terminal` EventStore event; the middle incomplete report is retained locally without promoting it to PASS. Raw reviewer JSON files are ignored local evidence, not committed. Full fingerprints and evidence locations are recorded in the companion sanitized receipt `docs/governance/receipts/RECEIPT-20261015-rule31-current-main-independent-review.md`.

## Exact canonical R9

Ran original, unmodified `bash scripts/ci_gate.sh` against the frozen reviewed eight-file staged candidate, exit **0**. No skipped failing tests, no diagnostic-ratchet widening, no baseline changes:

| Gate | Verified outcome |
| --- | --- |
| Ruff | PASS, new diagnostics 0 and touched files clean |
| Test-environment declaration | PASS, 853 files |
| Pyright | PASS, new diagnostics 0 and touched files clean |
| WebUI asset build from candidate | PASS |
| Tier0 | **319 passed**, 8,585 deselected, 3 warnings |
| Full `pytest --dist loadfile -n auto -q`, 4 workers | **8,742 passed, 146 skipped, 14 warnings**, 198.60 seconds |
| Guard-report selection | **1 passed**, 29 deselected |
| CI process exit code | **0** |

Exact ignored local CI output: `data/rule31-next-phase-20261015/full-r9.log`, SHA-256 `ad43d8a76ed5ede221119166b7e39ed41a71606cf851bd0e0d41c301f4fb36d0`. The CI-only interpreter dispatcher used the same pinned project venv for static and pytest; pytest alone inherited an ignored Python-only loopback egress guard and venv-first PATH to support nested CLI tests. The guard SHA-256 is `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`. Explicit guard canaries validated public DNS/connect denial and localhost/Unix socket functionality. **It is not an OS-wide firewall; do not claim physical blocking of non-Python native subprocess traffic.** The isolated candidate had no `.env`; relevant API-key environment variables were removed from CI. This was not a real Provider experiment.

The full suite rewrote exactly 18 previously clean tracked `reports/phase3` through `reports/phase6` files. After the CI process ended, the entire unstaged difference set was matched byte-for-byte by path against the 18-path test-generated report whitelist, and only those paths were restored with `git restore --worktree -- <exact paths>`. No source, index, root main worktree, or other Agent assets were restored or deleted. Subsequent source and test-only local commits exactly reproduced the independently reviewed full diff SHA above.

After commits, original `bash scripts/ci_gate.sh --quick` with the same test-only interpreter returned **exit 0**, Ruff/EnvPin/Pyright PASS and **319 passed**. This is a post-commit HEAD integrity check, NOT a replacement for the full R9 above. Log `data/rule31-next-phase-20261015/postcommit-quick.log`, SHA-256 `3b855401cda42667cb4674c7cd6787893161ae7562de8828ce76b391049a3a6a`.

## Boundary, residuals, and later actions

Current main and production have **NOT** adopted this branch. Reviewer nonblocking P2 observations include markdown fenced/H1 heading parsing edge cases in future SoT shapes and theoretical test-time boundary/clock skew; these were not silently treated as fixed or as authorization for an architectural expansion. If future promotion to main is desired: verify then-current main drift and current tool/runtime consumers, require owner merge authorization, review integration identity and applicable R9, and separately authorize any deployment/restart. Keep the isolated commit range as the precise rollback/revert anchor; never reset a shared branch or alter unrelated in-flight work.
