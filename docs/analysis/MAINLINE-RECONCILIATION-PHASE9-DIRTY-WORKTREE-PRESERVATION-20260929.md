# Mainline Reconciliation Phase 9 — Dirty Worktree Preservation

- Date: 2026-09-29
- Canonical main before evidence commit: `9bec930d11f5b7c5ee1ae5cb497d4b1136704831`
- Result: **PRESERVATION COMPLETE — cleanup pending explicit checkpoint**

## 1. `fix/chatgpt-web-exact-ingress-20260927`

Disposition: **retain branch, removable worktree after checkpoint**.

- Preserved WIP commit: `ade11de5fdba186f2c77c844ea93e975bd512364`.
- Worktree is now clean.
- `evidence_shadow.py` adds `WorkingSetEvidenceRecorder`; `registry.py` adds the matching hook plumbing.
- Current main already has working-set receipt/bounded-first-view projection, but this prototype has no factory/config activation and no dedicated integration qualification. Therefore it is not safe to migrate mechanically.
- Focused evidence/working-set tests: **27/27 PASS**.
- Branch remains a true unique patch against main and must not be deleted as part of cleanup.

## 2. `eval/web-gpt-512k-canary-20260927`

### Runtime fix migrated

- Source preservation commit: `aa71c7a5a8a16becb1ed03e525aea4e06ddd1b76`.
- Canonical main migration commit: `9bec930d11f5b7c5ee1ae5cb497d4b1136704831`.
- Migrated paths:
  - `src/llm_loop/llm/chatgpt_page.py`
  - `tests/unit/test_chatgpt_page_send_transient.py`
- Current relation: source commit is now `git cherry -` versus main.
- Qualification on current main: **98/98 PASS** across `tests/unit/test_chatgpt*.py` plus `test_deepseek_web_model_client.py`; Ruff, py_compile, diff-check, and security scan PASS.

### Long-context harness archived on branch

Archive commit: `94cfad505ffb887e5078eab94ed9ee72bb1f5ee9`.

Preserved on the eval branch:

- seven long-context probe/canary Python scripts;
- `true_limit_results.json`;
- `attachment_result.json`.

Before archival, machine-specific absolute paths were replaced by worktree-relative root discovery. All seven scripts py_compile successfully and the security scan passed. Ruff still reports legacy exploratory-script style debt; that was intentionally not rewritten as part of evidence preservation.

### Generated-only remainder

- `lfl_snapshot_1_4m.txt`: **generated payload, pending discard after checkpoint**; size `1400000` bytes; SHA256 `81166c2355dc7d6a74f446343a57e825a43cb582bd861eb9c1d708971b4e81cc`. Its generator and result evidence are preserved, so this large payload is not canonical source.
- `__pycache__/run_canary.cpython-313.pyc`: ignored bytecode cache; discardable.

The eval worktree is therefore not yet clean solely because the 1.4MB generated payload is intentionally left in place until the cleanup checkpoint.

## 3. Safety invariants

- Production remains **gen161 / `67ce123c5fa8430ab833610857fbf276d55e589d`**; read-only `service_control verify` PASS.
- Production was not restarted.
- Preserved root WIP remains `wip/main-pre-reconcile-20260929@8454c8a981...`: 31 tracked modifications, hash drift=0, index `1d6bf5bd04e8eaf3857f8e4ae5ab85e61ef59616`.
- No remote branch was modified.

## 4. Cleanup gate

After explicit checkpoint only:

1. Remove the ingress worktree without force while retaining branch `fix/chatgpt-web-exact-ingress-20260927`.
2. Delete only the generated 1.4MB snapshot / ignored cache in the 512k worktree, then verify `git status` is clean.
3. Remove the 512k worktree without force while retaining branch `eval/web-gpt-512k-canary-20260927` because archive commit `94cfad505` remains unique.
4. Re-run production, root-WIP, branch-reachability, and six→four worktree invariants after cleanup.

The `WorkingSetEvidenceRecorder` prototype requires a separate design/qualification phase before any future migration to main.
