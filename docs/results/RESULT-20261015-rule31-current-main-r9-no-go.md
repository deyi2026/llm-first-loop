# Rule31 current-main isolation: R9 NO_GO receipt

Date: 2026-10-15. Goal: `d0a3a009-34d8-4f71-a957-60f0e3254249`.

## Authority and scope

- Current integration baseline: `main@db4aaa8565ea0d0cc061b12e5701f5398b53698e`.
- New isolated branch: `fix/rule31-current-main-20261015`; no merge, push, publish, restart, or production modification.
- Seven-file staged RuleIndex/search_records/ledger/test patch: 23,187 bytes; `git diff --cached --no-ext-diff --binary` SHA-256 `f858e5eb20c9df60da0702e2d0c0554bcb3b7cf03df6508416777eaa0526e43f`.
- Exact bytes **match** the independent GLM-5.3 source review from the predecessor integration (`subagent_994462fc80b0`, completed, PASS P0=0/P1=0; see the predecessor branch's committed sanitized Reviewer receipt).
- This is **not a fresh independent Reviewer run** against the current main's complete content. Among the three newer main commits, `docs/ai_rules.md` Rule31 § at line 517 changed D3 advancement-vs-correction behavior; the exact seven files were not modified. Do not claim the old code review validated that newer SoT statement.

## RED to GREEN and preflight

- On the new current-main worktree before implementation, the three transferred regressions were **3 failed**: bounded search_records initial packet and two H2 cutoff tests.
- Re-applying the predecessor's exact seven-file patch produced **61 passed**, including browser attestation negative tests.
- `git_security_scan.sh --staged`: PASS (seven files), staged diff-check: PASS.
- Original `bash scripts/ci_gate.sh --quick`: exit 0; Ruff current35/new0/changed0, EnvPin 853 files, Pyright current19/new0/changed0, WebUI build PASS, tier0 **319 passed / 8585 deselected**.

## Original, unmodified canonical full R9

`bash scripts/ci_gate.sh` ran once against the actual new staged worktree with four xdist workers. The real CI process **exited 1**; no success or exception was manufactured.

- Ruff/EnvPin/Pyright/WebUI/tier0: PASS.
- Full xdist: **8741 passed / 146 skipped / 1 failed / 13 warnings**, 182.11s.
- Built-in serial failure reproduction: **12 passed / 1 failed**.
- Unique failing node: `tests/unit/test_backup_store_durability.py::test_orphan_tmp_and_lock_invisible_to_scan_surfaces`.
- Assertion: `BackupStore.cleanup()` produced `{"pruned": 1}`, fixture expected `{"pruned": 0}`.
- Current date boundary root cause: the test uses hardcoded `BACKUP_AT="2026-10-08T10:00:00"` and `RetryPolicy.RETENTION_PERIOD_DAYS=7`. At the verified local date `2026-10-15T12:28+0800` the supposedly fresh backup is over seven days old, so the retention cleaner correctly prunes it. The test and `src/llm_loop/recovery/backup.py` are unchanged from current main. This is a pre-existing time-dependent test fixture defect, **not evidence of a Rule31 regression**; nonetheless full R9 is genuinely RED and blocks source commit.
- Authoritative ignored local log: `data/rule31-current-main-r9-full-20261015.log`; SHA-256 `e420da8a5caab39c7aba6108fe7374f6a6655a2b076208794e8078a600b0c243`.

## Safety and cleanliness

- No API credential environment variables were passed; no local isolated `.env` exists.
- The ignored CI-only Python `sitecustomize.py` socket guard has SHA-256 `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`; it denied nonloopback DNS/TCP and newly spawned Python+httpx, while allowing loopback and Unix sockets. This is **not an OS-wide outbound firewall** and does not prove native non-Python child processes cannot reach external networks.
- After the failed CI terminated, exactly 18 tracked report files produced by this suite were matched against an explicit whitelist and restored in the isolated worktree. No other-agent files or original main tree changed.
- The original seven-file staged patch SHA remains unchanged, and there are no unstaged tracked source edits. This receipt is an untracked local report pending a qualified review/closure.

## Verdict and narrowly scoped next action

**NO_GO for complete integration qualification or source commit.** Do not lower the retention constant, skip the test, widen a known-red baseline, fake the clock for the entire R9 run, or misreport the full result.

1. In a separate minimal reviewed change, correct the single **fresh-backup** test fixture to derive the archive timestamp from `backup_module.system_local_now()` (rather than the fixed 2026-10-08 date); keep explicit retention-expiry tests time-controlled.
2. Obtain an independent Reviewer PASS bound to any modified candidate SHA and explicitly review the new main Rule31 D3 SoT drift.
3. Re-run the unmodified canonical full R9 against the resulting exact isolated candidate, then perform final safety/status checks and only then create isolated local code and evidence commits. Separate user authorization remains required for any later main merge or deployment.
