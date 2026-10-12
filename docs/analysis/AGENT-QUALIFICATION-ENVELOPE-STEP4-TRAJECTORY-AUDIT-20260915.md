# Agent Qualification Envelope v0.1 — Step 4 Mechanical Trajectory Audit

> Status: **NO-CHANGE / HOLD**
> Audit baseline: `744f5503871727f5a4cb46dc355a5bf4c85303f4`
> Step 2/3 frozen contract SHA256: `041e32c4501812fb2c10b1d3d95b7eadf659e0143d8e2cd43d64c8d7228ef9d1`
> Scope: non-adjacent exact recurrence/no-progress and terminal-after-close only.
> Runtime/scorer/Envelope contract changes: **none**.

## 0. Ruling

Step 4 does **not** add a generic `A -> B -> A => fail` rule and does **not** add a new
`terminal-after-close` eval verdict.

The audit found two different reasons:

1. generic LFL trajectory surfaces do not carry enough mechanical state/version/effect facts to prove
   that a non-adjacent repeat made no progress;
2. domains that *do* carry enough facts already have their own mechanical owners and hard boundaries
   (A3 experimental Action-Plane guard, Browser SMC ActionReceipt/action-id/version guard,
   ExternalExecutionJournal, and the main run lifecycle).

Adding another generic hard gate would therefore either be unsound or duplicate an existing owner.
Both violate the Envelope v0.1 G2/LLM-First boundary.

---

## 1. Question A — Can generic non-adjacent `A -> B -> A` be hard-failed?

### 1.1 Generic eval trace is intentionally too thin

The generic eval runner projects `EngineResult.tool_calls` to only:

```text
{name, arguments}
```

at `scripts/run_eval.py:91-113`.

There is no result status, result content/fingerprint, world/resource version, effect receipt,
idempotency class, or scope/version identity. Therefore after `A -> B -> A` the program cannot know
whether B changed the world, whether A is a deliberate re-observation, whether A targets a versioned
immutable object, or whether the second A is redundant.

Extending `src/llm_loop/eval/verdicts.py:_same_fingerprint()` from adjacent repeats to all prior
fingerprints would turn missing world-state information into a semantic claim.

### 1.2 Production repetition policy is explicitly telemetry-only

The production tool loop already freezes the opposite default:

- every valid declaration reaches normal execution/WAL;
- repetition is observed **after** the receipt and is never a pre-execution gate:
  `src/llm_loop/core/loop/engine_services/tool_cycle.py:356-359`;
- `_stagnation_fingerprint()` is exact tool + all arguments, not semantic target collapsing:
  `src/llm_loop/core/loop/engine_services/tool_cycle.py:583-590`;
- `_track_tool_observation()` explicitly states it never blocks, writes a model message, persists a
  cross-run deny state, or terminates a run:
  `src/llm_loop/core/loop/engine_services/tool_cycle.py:592-625`.

This is locked by `tests/unit/test_loopbreaker_integration.py:27-54`: five identical `read_file`
calls all execute, declaration/receipt pairing stays intact, and only one `tool.repeat_observed`
telemetry record appears. The test explicitly rejects generic `duplicate.*`, `stagnation.break`, and
`no_progress.*` blocking.

A repeated read can be legitimate because the underlying file can change or because the model/user
intentionally wants to re-observe. A repeated `read_evidence` may also be deliberate exact rehydration.
Neither is mechanically equivalent to “no progress”.

### 1.3 ToolExecutionJournal does not supply a generic no-progress identity

The production WAL is valuable recovery truth, but it does not close this gap:

- `execution_id` includes session, run generation, round, tool-call id, name, and arguments:
  `src/llm_loop/core/tool_execution_journal.py:206-223`;
- the persisted result snapshot itself includes execution id, round, tool-call id and tool name:
  `src/llm_loop/core/tool_execution_journal.py:586-605`;
- `result_state_sha256` hashes that whole attempt-specific snapshot:
  `src/llm_loop/core/tool_execution_journal.py:606-634`.

Thus `result_state_sha256` is an **integrity/recovery fingerprint of one execution attempt**, not a
cross-attempt semantic result hash. Two byte-identical tool contents from different rounds naturally
have different attempt envelopes. It also carries no universal world-version or idempotency contract.
Using it as a generic no-progress key would be a category error.

### 1.4 A3 duplicate suppression is deliberately domain/experiment scoped

A3's `scripts/calib/action_guard.py` has enough local knowledge to suppress a deterministic fixture
lookup:

- canonical exact call fingerprint: `scripts/calib/action_guard.py:41-43`;
- result cache only stores successful/available deterministic fixture results: `scripts/calib/action_guard.py:86-100,122-128`;
- the file itself states it is an experimental Action-Plane mechanism layer that knows tool
  identity/arguments and action budget, not benchmark semantics: `scripts/calib/action_guard.py:1-5`.

That mechanism is valid for its frozen experiment, not a proof that arbitrary production tools share
the same deterministic/idempotent contract.

### 1.5 Browser mutation already owns the mechanically safe duplicate case

Browser SMC has the richer facts that generic tools lack:

- `browser_semantic_execute` derives `action_id` from exact `verb + GroundingRef + args`; the
  GroundingRef includes the immutable observation version, so repeating the same request reuses the
  same action id: `src/llm_loop/tools/builtin/browser_semantic_execute.py:82-94`;
- a fresh observation gives a fresh action opportunity: same source lines;
- `BrowserActionReceiptStore.reserve()` uses an exclusive reservation to prevent duplicate action-id
  dispatch: `src/llm_loop/browser/action.py:109-148`;
- dispatch rechecks `expected_version/version_scope` before mutation:
  `src/llm_loop/browser/action.py:453-468`;
- duplicate action id is rejected before a second dispatch:
  `src/llm_loop/browser/action.py:426-439`;
- receipts are append-only revisions with monotonically assigned `receipt_seq`:
  `src/llm_loop/browser/action.py:150-180`;
- the mutation path emits running then terminal receipts and performs no automatic retry:
  `src/llm_loop/browser/action.py:517-609`.

Existing tests already prove the boundary:

- normal action dispatches once and appends running/terminal receipts:
  `tests/unit/test_smc_browser_action_v01.py:90-110`;
- stale precondition rejects before dispatch: `tests/unit/test_smc_browser_action_v01.py:113-125`;
- duplicate action id never dispatches twice: `tests/unit/test_smc_browser_action_v01.py:140-148`;
- ambiguous actuator error is failed, never automatically retried:
  `tests/unit/test_smc_browser_action_v01.py:151-163`.

A second generic duplicate-action gate would duplicate this owner and could disagree with its
version/action identity.

---

## 2. Question B — Is “terminal-after-close” missing as a generic trajectory hard gate?

### 2.1 Main run `run.end` is written only after the tool/model loop exits

The normal run control flow prevents same-run tool dispatch after durable `run.end`:

- model no-tool final exits the loop before the tool execution branch:
  `src/llm_loop/core/loop/engine.py:1769-1856`;
- after a tool batch, max-iteration hard stop sets the terminal reason and breaks:
  `src/llm_loop/core/loop/engine.py:1894-1909`;
- only after loop exit does the engine call `RunFinalizer.persist_and_settle()`:
  `src/llm_loop/core/loop/engine.py:1910-1935`;
- `run.end` is appended inside that finalizer:
  `src/llm_loop/core/loop/engine_services/run_finalizer.py:417-450`.

Therefore a normal trace cannot contain “durable run.end, then another tool dispatch in that same
run”. If such an event ordering appears, it is a lifecycle corruption/forensics issue, not a missing
model trajectory policy.

`TerminationController.should_terminate()` exists but has no production callsite on this baseline;
its current docstring explicitly says the interface is reserved for later wiring. Step 4 does not
pretend that dormant helper is the owner.

### 2.2 A3 action-channel terminal is already enforced at its owner

For the A3 frozen experiment:

- `visible_tools()` returns an empty tool surface after terminal budget exhaustion:
  `scripts/calib/action_guard.py:45-49`;
- an already closed channel blocks additional calls, including batched calls from the same response:
  `scripts/calib/action_guard.py:72-84`;
- reaching the execution limit sets `tool_budget_exhausted` and returns
  `channel_closed=true`: `scripts/calib/action_guard.py:102-115,130-143`.

A generic eval verdict would add no protection and would obscure the actual Action-Plane owner.

### 2.3 Browser ActionReceipt terminal is already action-id fenced

Browser's terminal receipt does not grant task completion. It only closes that exact action identity.
A repeated identical semantic request maps to the same `action_id` and is rejected by the reservation
store before dispatch. A fresh observation/version creates a new explicit action opportunity.

That is the correct mechanical boundary; “terminal receipt seen anywhere => no more browser actions”
would be wrong because a later world version can legitimately require a new action.

### 2.4 External execution terminal is already append-only/idempotent

`ExternalExecutionJournal` is the owner for long-lived external execution lifecycle facts and
explicitly does not judge task usefulness/completion (`src/llm_loop/core/external_execution.py:1-9`).

It already provides the relevant terminal/idempotency semantics:

- duplicate identical launch returns existing state, while conflicting reuse returns `None`:
  `src/llm_loop/core/external_execution.py:70-119`;
- repeated cancel request returns existing cancel state: `src/llm_loop/core/external_execution.py:123-151`;
- once `terminal_seq` exists, repeated terminal settlement returns the existing terminal state rather
  than appending a second terminal: `src/llm_loop/core/external_execution.py:153-191`.

Again, no new generic trajectory gate is needed.

---

## 3. What would be required to reopen non-adjacent no-progress as a hard rule?

The following facts would have to come from an existing domain owner; the Envelope/eval layer must not
invent them:

1. stable semantic/action identity for the *same physical operation*, not merely equal tool-name/args;
2. explicit operation/idempotency class (`read_only`, mechanically idempotent, non-idempotent, unknown);
3. before/after world/resource/version identity or equivalent mutation boundary;
4. effect/dispatch receipt proving whether a side effect occurred;
5. result/effect fingerprint whose identity is independent of round/tool-call attempt metadata;
6. an owner-defined rule saying the repeated action is mechanically forbidden or already settled.

Even with 1-5, a repeated read-only observation is not automatically invalid: a user/model can
intentionally re-observe. A hard fail is justified only when the **domain contract itself** establishes
that the action is closed/duplicate/stale/unsafe, as Browser already does.

Therefore the next safe trajectory work, if a real incident requires it, should be domain-scoped and
receipt/version-based. It should not start from a global “seen this fingerprint before” set.

---

## 4. Envelope v0.1 disposition

No Step 4 field is added to `AGENT-QUALIFICATION-ENVELOPE-v0.1.json`.

Reasons:

- `trajectory.adjacent_duplicate_fingerprint` already documents the existing selected eval verdict;
- generic non-adjacent no-progress has **no safe owner** on the current generic trace;
- Browser/A3/ExternalExecution terminal and duplicate facts already belong to their own owners;
- adding a generic field now would create either an ownerless pseudo-fact or duplicated authority.

The frozen 35-field contract and its SHA256 remain unchanged.

---

## 5. Deterministic verification performed

On exact baseline `744f5503871727f5a4cb46dc355a5bf4c85303f4`, the focused existing boundary suite passed **62/62**:

```text
tests/unit/test_loopbreaker_integration.py
tests/unit/test_smc_browser_action_v01.py
tests/unit/test_smc_browser_semantic_execute_v01.py
tests/unit/test_calib_a3.py
tests/unit/test_tool_execution_restart.py
tests/unit/test_external_execution_restart.py
tests/unit/test_continuity_kernel_final.py
```

The suite exercises generic repeat-observation non-blocking behavior, Browser action reservation /
version / receipt semantics, A3 Action-Plane guards, tool-execution recovery receipts, and durable
external-execution lifecycle facts. It was run locally with the existing shared project virtualenv and
the isolated worktree source explicitly on `PYTHONPATH`; no provider/model/network qualification was
started.

---

## 6. Step 4 exit ruling

**Step 4 = PASS as an audit / NO-CHANGE as an implementation.**

This is not “missing work was skipped”. It is a negative architecture result:

- the proposed generic non-adjacent hard rule is not mechanically justified by the generic trace;
- terminal/duplicate cases that *are* mechanically justified are already owned and enforced at the
  appropriate subsystem;
- no safe new owner/provenance field exists, so Envelope must remain unchanged.

The next planned phase is Step 5 A.5 structured declaration manifest + mechanical presence/coverage
repo review gate. Step 4 does not start that phase.
