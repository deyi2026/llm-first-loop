# R8.11 Observability Receipt Prompt Exit

Status: **PASS / detached-clean fixed-point verified**

Implementation commit: `1114044 fix(injection): retire observability prompt receipts`

## Scope

R8.11 closes two OPEN surfaces that were pure runtime bookkeeping but still produced model-facing natural language:

- **E20 `cache_gate_note`**
- **E21 `injection_budget_receipt`**

The governing rule is the strengthened post-R8.10 contract:

> **program state is observable/retrievable, not self-injecting.**

A runtime subsystem may change deterministic runtime behavior and expose that state to UI/status/audit, but the fact that the subsystem acted is not itself a reason to add prose to the model's task context.

## E20 — cache gate note

Previous live behavior consumed `gate_note_pending` and appended the fixed text beginning `[门禁干预] ... 你无需处理...` into the dynamic program appendix. The text was explicitly informational, yet it still changed the model's attention and provider wire.

R8.11 now:

1. keeps the cache monitor intervention (`force_head_keep`, drift/health state) unchanged;
2. consumes the one-shot `gate_note_pending` marker so runtime state cannot churn indefinitely;
3. records `run.cache_gate / observed_only / prompt_chars=0` action telemetry;
4. removes `gate_note` from `PROMPT_DYNAMIC_PRODUCER_SLOTS`;
5. emits **zero gate-note prompt characters**;
6. keeps `GATE_NOTE_CONTENT`, `restore_gate_note()` and err1210 parser/defer support only as compatibility for historical payloads/snapshots. A restored legacy marker is consumed/retired, not replayed.

Engine-level err1210 tests were moved from gate-note as a live fixture to a still-eligible `interop` fixture, preserving strip/defer recovery coverage without requiring a retired producer to stay prompt-visible.

A read-only artifact scan found the exact historical gate-note phrase **35 occurrences** across current audit/event artifacts. This is an artifact occurrence count, not a unique-request count, but it confirms the surface reached real captured payload/history paths.

## E21 — injection budget receipt

Previous budget enforcement created a synthetic highest-priority `BudgetBlock` for the receipt, reserved prompt budget for it, and then `build.py` appended the receipt *after* the eligibility pass to both the wire appendix and cognitive packet.

That had two structural problems:

- bookkeeping consumed the same scarce prompt budget it was supposed to govern;
- it bypassed the centralized dynamic-producer eligibility gate by being appended later.

R8.11 keeps `InjectionBudgetResult.receipt_content` as out-of-band observability, but:

- no synthetic receipt block is created;
- receipt text consumes **zero** prompt budget;
- `used_chars` reflects only actual kept program blocks plus their real group overhead;
- `build.py` never appends receipt text to `_inject_parts` or `_packet_parts`;
- `action.injection_budget / pruned` retains `used/budget/dropped` and records `prompt_receipt=0`.

The current exact receipt phrase was found once in the artifact scan; again this is only evidence of reachability, not a request-rate metric.

## Provider-shape effects

The production golden injection morphology was intentionally updated: arming a cache gate marker can no longer change the provider wire or golden prompt digest. The live eligible dynamic set in those fixtures is now memory / interop / tip / hotcard (subject to their own later eligibility audits).

The cognitive compiler retains low-level ability to parse/classify a legacy `gate_note` input, but the live build eligibility layer no longer produces or admits that slot. This separates compatibility parsing from production prompt authority.

## Verification

Detached clean checkout of `1114044` passed:

- focused E20/E21 + morphology + cognitive + err1210 suite: **108/108 PASS**;
- broader 17-file cache/cognitive/1210/history/reference/user-truth/program-recovery suite: **242/242 PASS**;
- touched production pyright: **0 errors / 0 warnings**;
- production ruff findings are baseline-equivalent to parent HEAD (no new lint debt attributed to R8.11);
- canonical R0 replay: **R0-1 through R0-4 PASS**;
- tracked frozen R0 directory unchanged; frozen hash remains `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`;
- detached checkout: **clean before and after verification**.

The main worktree had unrelated pre-existing import-order/newline edits in `tests/integration/test_cognitive_integration.py`; R8.11 used index-only partial staging so only the four behavior assertions were committed. The unrelated worktree diff remains untouched.

## Matrix state

After E20/E21 closure:

- `DONE=22`
- `KEEP=1`
- `PARTIAL=10`
- `OPEN=1` — E25 `interop_notify_and_backlog`

Behavior canary remains **READY but not started**. E25 is the next OPEN observability surface, but it requires a separate audit because an external interop message can sometimes be a genuine dependency/input rather than mere notification.
