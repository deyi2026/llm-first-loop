# Human Turn Queue Convergence Qualification — 2026-09-11

> **Verdict:** PASS / ADMIT final safe queue implementation.
> **Integration parent:** `integration/convergence-20260911@43c78ee`.
> **Source feature evidence:** `feature/webui-human-turn-queue-20260910@f39152084ab420d0922e09c13732573e057df8eb`.
> **Qualified implementation commit:** `5349a337a62fefbd06df78286e6d3e9cf765f91e`.
> **Rule:** the source feature commit is evidence, not an admissible merge unit; its duplicate-dispatch lifecycle gaps are corrected in the qualified implementation.

## 1. User-visible capability

The qualified implementation provides the previously advertised Human Turn queue:

- while a response is generating, `Cmd+Enter` and `Ctrl+Enter` enqueue the current Human Turn instead of issuing a second direct `/chat/stream` request;
- FIFO queue state is durable under `data/human_turn_queue.json`;
- message, attachment refs/facts, model, reasoning effort, and reasoning mode are frozen at enqueue time;
- multi-tab dispatch uses an atomic `queued -> claimed` transition;
- queue state is rendered in WebUI and survives refresh/session revisit.

Frontend regression proves both Cmd and Ctrl modifiers call the queue endpoint, do not call the direct stream endpoint, and clear the composer only after an accepted enqueue.

## 2. Source defects found during convergence review

### 2.1 Timeout-only stale reaper could duplicate a live run

The source feature treated `claimed_at + 60s` as sufficient evidence that a claim was dead. A legitimate run lasting beyond the timeout could therefore be changed back to `queued` and dispatched again.

**Correction:** timeout is only a reconciliation trigger. It does not grant replay authority.

### 2.2 SSE subscriber incorrectly owned queue terminal settlement

The source feature marked `completed/failed` from `_stream_background`, which is an SSE subscriber. Browser disconnect is intentionally not a run cancellation, so the subscriber could disappear while the background run continued. The queue claim then had no terminal owner and could later be stale-reaped and replayed.

**Correction:** `BackgroundRunner` owns the terminal callback. Subscriber disconnect only unsubscribes from delivery; it does not remove terminal settlement.

### 2.3 External `release` could requeue a started claim

The source `/api/v1/chat/queue/release` changed any claimed item back to queued without proving the run had not crossed an execution boundary.

**Correction:** external release is allowed only when formal run/EventStore facts resolve the claim as `not_started`. Active, started-without-terminal, ambiguous, or unknown states return 409. A `SessionBusy` failure is handled internally by the run owner as `not_started`; the frontend no longer decides whether execution began.

### 2.4 `queue_id` did not bind the frozen request

A caller could submit a claimed `queue_id` with different message/model/attachment facts and still let that id drive terminal queue settlement.

**Correction:** `/chat/stream` exact-compares the claimed frozen message, attachment refs/facts, model, reasoning effort, and reasoning mode. Mismatch returns 409 before model execution and leaves Session/EventStore unchanged.

### 2.5 reasoning mode was not actually frozen

The source relay attempted to read `claimed.reasoning_mode`, but enqueue schema/storage did not persist it.

**Correction:** queue enqueue/storage/API/Web types now freeze `auto|off|on` together with model and reasoning effort.

## 3. Single durable execution boundary

The queue does **not** create a second run ledger.

It reuses existing authorities:

- `SessionStore.run_lease` / `management_lease` = formal active-run mechanical truth, including cross-process locking;
- `EventStore message.appended` = exact durable queued-human ingress fact;
- `EventStore run.end` = durable run terminal fact;
- `BackgroundRunner` = same-process run owner and terminal callback owner;
- `HumanTurnQueue` = queue/FIFO/claim state only.

For a queued turn, `human_turn_queue_id` is stored only as bounded internal Message/Event metadata. Before any LLM/tool action, the exact `message.appended` event must become durable. If EventStore is disabled/unavailable or the append fails, the in-memory user message is removed and a typed `QueuedIngressDurabilityError` aborts the run as `not_started`; the queue claim is safely released for later retry.

Ordinary non-queued human ingress keeps the existing EventStore fail-open behavior. The stronger requirement is scoped only to replay-sensitive queued turns.

## 4. Stale-claim reconciliation states

After the timeout trigger, the program derives only mechanical states:

```text
formal run lease active
    -> active                 -> keep claimed

no exact queue ingress event
    -> not_started            -> safe requeue/release

exact queue ingress, no run.end
    -> ingress_open           -> keep claimed + recovery_required

exact queue ingress + run.end
    -> completed | failed     -> terminal convergence, no replay

corrupt/multiple/ambiguous facts
    -> unknown                -> keep claimed, fail closed
```

If another genuine human ingress appears after the queued ingress but before a corresponding `run.end`, correlation is treated as `unknown`; the program does not guess which terminal belongs to which turn.

The key invariant is:

> **started-without-terminal is outcome unknown, never automatic whole-turn re-execution.**

This matches the existing tool/external-execution continuity rule that unknown side-effect outcome cannot authorize replay.

## 5. Provider-visible invariants

`human_turn_queue_id` is provenance metadata only. Deterministic comparison of an otherwise identical user Message with and without this metadata produces exactly the same `to_llm_dict()`:

```text
{'role': 'user', 'content': 'same'}
WIRE_EXACT_MATCH = True
```

Actual `build_engine` parent-vs-candidate comparison is also exact:

```text
registered provider params
  parent/candidate: 62 tools / 23652 bytes
  SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37

runtime-health projected provider params
  parent/candidate: 60 tools / 22978 bytes
  SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8

Universal Prompt
  parent/candidate: 192 chars
  SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
```

Queue metadata therefore changes durability/control facts, not model-visible semantics.

## 6. Qualification gates

Backend:

```text
queue + BackgroundRunner focused                 50/50 PASS
Web / Session / Event adjacent                  157/157 PASS
Ruff changed Python surface                     PASS
py_compile changed Python surface                PASS
Pyright repository                              0 errors / 0 warnings / 0 informations
git diff --check                                PASS
full pytest tests -q -m 'not real_llm'          explicit RC=0 (~161s)
Git security hook on 16-file implementation     PASS
private-path/key addition scan                   0 findings
```

Frontend:

```text
Cmd/Ctrl+Enter + frozen handoff focused          12/12 PASS
full Vitest                                      19 files / 105 tests PASS
tsc --noEmit                                     PASS
Vite production build                           PASS
```

Existing React `act(...)` warnings and bundle-size warning remain warnings only and were not introduced as queue correctness gates.

## 7. A.5 governance declaration (G1–G4)

### G1 — Necessity

Duplicate execution is an idempotency/durability boundary. The model cannot safely decide whether an already-issued Human Turn crossed a process/run execution boundary, especially when tool side effects may already have occurred. Mechanical run locks and EventStore sequence facts are required.

### G2 — Ownership / non-duplication

The queue owns only FIFO/claim lifecycle. It reuses SessionStore for run activity and EventStore for durable ingress/terminal truth. It does not infer task completion, maintain a second run ledger, or reinterpret provider/model semantics.

### G3 — Evidence / veto / recovery exit

The UI/API can inspect queue status plus bounded `recovery_state` / `recovery_required`. `not_started` claims may be retried. `ingress_open`/`unknown` claims are deliberately not model-overridable because replay could duplicate non-repeatable side effects; recovery must use existing Session/Event/tool execution evidence rather than re-sending the entire Human Turn.

### G4 — Rollback / verification

The feature is isolated in one convergence implementation commit plus one qualification commit and can be reverted as a capability. The replay-safety boundary itself is fail-closed and must not be weakened to restore availability. Provider-visible prompt/tool surfaces are byte-identical to the integration parent, and dedicated regressions cover live-run timeout, subscriber disconnect, restart reconciliation, EventStore failure, exact handoff binding, and both keyboard shortcuts.

## 8. Verdict

**PASS / ADMIT** the qualified final implementation, not the original `f391520` merge unit.

The convergence defect `HUMAN-TURN-CLAIM-REAPER-DUPLICATE` is resolved for this selected tree. Final status becomes integration truth only after the same tree is ported onto the single unified integration ancestry and post-port committed-state gates pass.
