# LFL architecture / agency: knowledge and Learning repair candidate

Date: 2026-10-14 (+08:00). Candidate: `fix/architecture-guard-and-agency-20261014`, continuing Phase-A code `fdf280c6f` and Phase-B scoped receipt `580ba4b0c`. This is **not** a production release receipt.

## Scope and evidence

Production facts were read without mutating services. Main was `c1408d7a7` during inspection and had unrelated tracked report modifications plus many user-owned untracked Method files; keep these untouched. Desired Web generation 258 bound to `5786fc5c9` and Web/Feishu manifests agreed; independent Learning manifest on `7b79c7ace` was alive. At the 10:51 snapshot, `data/runtime/learning_admission.json` was fresh with `state=idle, queued=0`. Direct read-only fold of actual 34 MB `data/sessions/learning/journal.jsonl` yielded states `saved=1401, none=238, failed=257, cancelled=27`, `runnable_jobs=[]` (these counts are only that instant, not a health SLA).

### Reproduced bug 1 — deleted session becomes three worker failures

Production `data/learning.log` contains repeated `SessionDeletedError` from `MemoryExtractor.extract_session(interval) → SessionStore.load_from_identity_owner` because the owner session had been durably deleted. The matching journal job ended `failed, attempt=3, reason=worker_exception`. This is **not** a current queued backlog; it is a real retry-waste/error-classification defect, and deleted sessions must remain inaccessible.

Fix: `LearningPlane._run_memory_extract_job` handles **only** `SessionDeletedError` by appending a terminal `cancelled(source_session_deleted)` event. Generic extractor failures still propagate and remain retryable; foreground preemption still has priority. New regressions cover the exact exception, ordinary error, and a real two-workspace `SessionStore` tombstone with a provider stub that must never be called. No production journal surgery or deleted-content restoration.

### Reproduced bug 2 — RULE-AI-31 exact hydration absorbs an unrelated appendix

The SoT-backed `RuleIndex('docs/ai_rules.md').search('RULE-AI-31', 1)` did return `full_rule`, but its body also included the sibling `## 配置扩展` section: `6476` chars before correction. Since it was the last numbered Rule, the parser used EOF instead of the next level-2 Markdown heading. Fix: precompute all `##` sibling heading boundaries and close each numbered rule at the next sibling. Test against current SoT and synthetic Rule/appendix/Rule sections; exact hydration retains version SHA and `task_applicability=not_evaluated`.

### Rule/Method/Experience availability — provider-visible contract, not efficacy proof

The SoT `RULE-AI-31` calls for bounded first-stage discovery for substantial work (tool use / multi-step / artifact edits / diagnosis; at most two knowledge kinds, up to five per kind, once per continuous task window; simple chat exempt). The existing search tool described narrower high-frequency triggers. Align existing `search_records` full **and** stable compact descriptions with this SoT without increasing the universal prompt or changing model-owned applicability judgments; compact description shrank **430 → 394 chars** and passes the existing `390+80` guard.

An initial ERR1210 two-tool test fixture was correctly rejected as nonrepresentative. The full `build_test_engine` fixture captured the actual first `FakeLLM.chat` request from `LoopEngine`: SOUL's learning identity appears in the system message; search_records / method_manage / save_experience / refine_experience are available and the Rule31 discovery guidance reaches the compact schema. This is a real assembly-path **offline wire capture**, with **no paid provider call**, not evidence that a live GLM model chooses the method or that success rate improves. Independent task-level strong/weak A/B is still required.

## Verification snapshot

- Focused suites, covering Rule retrieval/presence/SoT, Method and Experience, knowledge receipts, Learning and wake, factory and providers, architecture guard: **374 passed** (`-q --tb=short`, ~7.7 s) on the isolated working candidate.
- Post-commit candidate `47ef1b60c` re-ran the exact focused test selection: **374 passed**. Tier0 preflight `python -m pytest -m tier0 -q --tb=short`: **318 passed, 8,543 deselected, 3 dependency deprecation warnings**, exit 0. Tier0 is a preflight, **not** the full R9 gate.
- Ruff on seven modified Python files: PASS; `git diff --check`: PASS.
- `scripts/check_static_diagnostics.py --tool pyright`: exit 0; historical 45, current 19, new 0, resolved 26, changed-file diagnostics 0 (tool version 1.1.411).
- Existing test-side-effect audit issued 51 non-blocking review warnings, not counted as verified harmless across all cases.
- Whole R9/full-suite gate, independent SubAgent review receipt, real GLM provider-view result, weak-model efficacy experiment, production merge/publish/restart: **NOT DONE**. Per RULE-AI-28, independent code-review SubAgent PASS receipt must precede full-suite execution; self-review and scoped tests cannot substitute.
- An isolated browser tab was opened to inspect whether a fresh LFL Web session could safely host an independent reviewer. Its UI indicated a different active background stream, so no review task was dispatched through that tab; the tab was then closed. This is an unverified observation, **not** a confirmed cross-session bug and **not** a reviewer run. Independent reviewer identity/verdict/receipt remain absent.

## Next stage

1. Independent read-only code-review SubAgent of exact commit/diff and evidence using `skills/code-review-gate/SKILL.md`; record reviewer ID, verdict, findings, dispositions and artifact SHA under `docs/governance/receipts/`.
2. On PASS, formal R9 on a clean final candidate, no baseline widening; categorize any pre-existing red with a current SHA. Verify real provider-visible messages and exact hydration plus bounded weak-model FCR/whole-run cost with GLM-5.3 preference, not DeepSeek.
3. Merge only from reconciled latest main after workspace and active-worktree audit. Check desired/live identity and active-run barriers before any authorized managed release. No force kill, no Web/Feishu/Learning restart solely to satisfy a test.

Exit note: code and test candidate is ready for independent review; it is not yet a qualified production artifact.
