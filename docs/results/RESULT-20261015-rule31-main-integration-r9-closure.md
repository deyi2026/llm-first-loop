# Rule31 RuleIndex / search_records — isolated main-baseline integration closure

Date: 2026-10-15. Goal: `ebd586f5-4d28-49bd-aab1-80b26f708c22`.

## Scope and disposition

**ISOLATED_CODE_REVIEW_PASS / CANONICAL_FULL_R9_PASS / ISOLATED_SOURCE_COMMIT_CREATED.**

This result concerns only the independently reviewed Rule31 integration **based on main commit `2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2`**. The isolated branch is `fix/rule31-main-integration-20261015`. At this report's verification point, `main` had advanced separately to `db4aaa8565ea0d0cc061b12e5701f5398b53698e`. **This branch has NOT been merged into current main and has NOT been pushed, released, deployed, or restarted.** Existing production services, signer authorities, and Provider budgets were not changed.

| Evidence | Verified result |
| --- | --- |
| Reviewed source candidate | 7 staged files, **23,187 bytes**, `git diff --cached --no-ext-diff` SHA-256 `f858e5eb20c9df60da0702e2d0c0554bcb3b7cf03df6508416777eaa0526e43f` |
| Source commit (isolated) | `a75513b1f5ef1798db1a55d09e2f2428a7b5b265` |
| Commit patch verification | `git diff --no-ext-diff HEAD^ HEAD` matched the reviewed candidate exactly: 23,187 bytes, same SHA-256 |
| Precommit security | `scripts/git_security_scan.sh --staged` **PASS**, exactly 7 files |
| Static and worktree discipline | `git diff --cached --check` **PASS**; unrelated root worktree and its in-progress reports untouched |

## Integration behavior preserved

- `RuleIndex` ends each rule at the next same-level H2, separating real Rule33 from the following `## 配置扩展` without swallowing or discarding nested H3 text.
- Full and Compact `search_records` descriptions preserve bounded Method / Experience / Lesson discovery, specific refs, a one-time task-window lookup, and model judgment; they do not require universal eager injection.
- Current main's `service_control` generation/CAS, `notify_external_result`, E2/E6 diagnostics, and existing tool-schema behavior remain intact.
- The formal rules ledger retains main's Rule32/33 rows and adds Rule31. SoT contains 33 formal H2 rules and three additional scope entries (36 actual registered items). The older inventory scanner reports 37 because its full-text ref search also counts `RULE-AI-21`, mentioned only as an absent-number explanation. This discrepancy was disclosed rather than disguised or used to relax the test.
- Browser negative attestation test reserves an ephemeral loopback port without listening and preserves the real fail-closed path, avoiding collisions with unrelated applications.

## Real independent code reviews

1. Initial 7-file candidate, child `subagent_d6cc727fb220`, independent GLM-5.3 terminal outcome `completed`, verdict **PASS P0=0 P1=0 P2=3**. Child terminal event `4378bb1e-0478-48e5-97de-6841420b8800`. Source SHA `a26be24d3631473ad9b6792ac95f96f63f7c98218cd65443d3300f0fc4f2b811`. Archived **sanitized derivative** `docs/governance/receipts/RECEIPT-20261015-RULE-AI-28-rule31-main-integration-independent-review-subagent_d6cc727fb220-sanitized.md`, SHA-256 `db5e1252fbaa9aa58753121d4cec2421d307ae6c48d7a9022ce39a02e7e1ac38`; unmodified raw receipt SHA-256 `b0c7ecf992880f21e47ccac84ecbe9eced56a2ab94a98b4dedd6657c2d6fd97c` retained locally outside the commit.
2. After correcting ledger inventory wording, a **different** independent child `subagent_994462fc80b0` reviewed the final **23,187-byte SHA above** and gave **PASS P0=0 P1=0 P2=2**; terminal event `d43a19f6-6979-462f-b466-7fb53e67fe09` outcome `completed`. Archived **sanitized derivative** `docs/governance/receipts/RECEIPT-20261015-RULE-AI-28-rule31-main-integration-independent-review-round2-subagent_994462fc80b0-sanitized.md`, SHA-256 `9d698d6c550cbb0acc3c25383a0a8d1f30f3deb666bdbac855a3804d4a280369`; unmodified raw receipt SHA-256 `20758b4c0918213eab3768d25d65c282f697b4b116059a9d473797a13a793128` retained locally outside the commit.

The first review's PASS does not stand in for the later SHA. Both separate child EventStore terminal events and the saved original receipt bodies were inspected before the final source commit.

**Security-scan handling:** The original Reviewer receipts contained three host-specific absolute home-directory prefixes and were rejected by `git_security_scan.sh --staged`. No allowlist or scanner exception was added. The raw receipt files remain **unmodified and untracked** with the raw hashes above; the separately committed `-sanitized.md` derivatives redact only those home-directory prefixes and identify their source hashes. The independent child EventStore terminal events and exact reviewed source diff provide the authoritative review provenance.

## Full R9 final result

The repository's original, unmodified `bash scripts/ci_gate.sh` ran with its full five-stage selection, including xdist `--dist loadfile -n auto` with four workers. **Real process exit 0**:

| Gate | Result |
| --- | --- |
| Ruff diagnostic ratchet | PASS; current 35, new 0; modified Python files clean |
| Test-environment declaration | PASS; 853 test files scanned |
| Pyright diagnostic ratchet | PASS; historical 45, current 19, new 0 |
| WebUI candidate build | PASS |
| tier0 preflight | **319 passed**, 8,580 deselected, 3 warnings |
| Full xdist suite | **8,737 passed, 146 skipped, 13 warnings**, 194.76 seconds |
| Final guard-report selection | **1 passed**, 29 deselected |
| Overall CI | **PASS / exit 0** |

The complete output is retained locally (ignored runtime evidence) as `data/rule31-main-integration-r9-full-ci-dispatch-pathfixed-20261015.log`, SHA-256 `843324e86555337205634f22de3302cfff869596aa627299043cc17fa4fd4f84`.

### Earlier failed runs and network-test boundary

Earlier full attempts were **not** represented as passing: a macOS parent sandbox caused incompatible nested child sandbox, AF_UNIX, and Chromium operations; the five affected test files passed **46/46** when run natively under an independently tested Python socket guard. Adding the temporary guard directory to the global `PYTHONPATH` then contaminated Pyright resolution, producing one new diagnostic in untouched code; standard-module-path Pyright passed. A later full run was **8,736 passed / 146 skipped / 1 failed** because a nested `pytest --version` resolved to the system Python 3.14 launcher while the test used project venv Python 3.13.

To obtain an unbiased full result without skipping tests or changing committed sources, the final run used an **ignored CI-only shell dispatcher** via the existing `PY` environment interface. All phases used the **same existing project venv Python**: static analyzers ran with standard source paths, while pytest received a temporary `sitecustomize` loopback-only Python socket egress guard and a venv-first `PATH`. The previously failing nested command test passed in isolation before the final full run. The original CI script, diagnostic debt baseline, test selection, and assertions were not edited.

The guard protects supported **Python socket paths only**, including the tested fresh spawned Python/`httpx.Client(trust_env=False)` path; **it is not an OS-wide firewall and does not prove that every non-Python native subprocess was physically blocked from the internet**. No real Provider credentials were injected (relevant API key variables unset; no local worktree `.env`); no live Provider qualification experiment was authorized.

The final full suite rewrote exactly 18 previously clean Git-tracked `reports/phase3` through `reports/phase6` files. After suite termination, those explicit 18 paths were verified as the entire unstaged difference set and restored using `git restore --worktree -- <exact report paths>`; no source/index/other-Agent files were restored. The reviewed source SHA remained unchanged throughout.

## Handoff and rollback boundary

**Isolated development and test qualification is complete. Production integration is NOT.** A later carry-forward to the then-current `main` requires renewed drift/semantic conflict assessment, a freshly frozen integrated patch, applicable independent code review and integration-state R9, and explicit owner authorization for merge and any separate deployment/restart. Before merging, the isolated branch may simply be left untouched; after an authorized merge, use an approved exact `git revert` plan rather than destructively resetting a shared branch. No push or production activation was performed here.
