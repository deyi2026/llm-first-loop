# SMC P4-LIVE ActionRef — G2-S3 GREEN Freeze v0.1

> Date: 2026-09-20
>
> Status: **G2-S3 QUALIFIED / RECOVERY-ONLY / ZERO REPLAY**
>
> Exact parent G2-S2: `dee507cd7aa69bc5425b57953a581f9b062f35b6`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## Scope

G2-S3 adds only crash correlation between the existing outer `ToolExecutionJournal`, the
S1 immutable ActionRef execution bridge, and exact Browser ActionReceipt history. It adds
no physical dispatch capability, no provider surface, no typed ActionRef mutation tool,
and no model/Browser/live execution.

Production changes are limited to:

- `browser/action_ref_execution.py` — create-only receipt cursor sidecar;
- new `browser/action_ref_recovery.py` — exact crash correlator;
- `core/tool_execution_journal.py` — optional recovery hook for started/no-finished WAL rows;
- `core/loop/events.py` — main-loop recovery wiring only when ActionRef execution state exists;
- `subagent/runner.py` — equivalent inert-until-state-exists recovery wiring.

## Exact-correlation amendment

S1 joined `execution_id -> inner action_id`, but inner action ids are intentionally
deterministic across duplicate exact requests. Therefore an old terminal receipt for the
same action id cannot by itself prove that the current outer execution reached Browser.

S3 closes this ambiguity mechanically with a second immutable cursor record, written
after PREPARED and before future S4 Browser entry:

`execution_id + bridge_id + session + tool_call_id + inner_action_id + receipt_seq_before`

Recovery reads only receipts for the exact bound action id whose `receipt_seq` is greater
than that baseline. No target/name/URL/latest/successor search is performed.

If the cursor is absent, future S4 ordering proves Browser entry was not reached and
recovery is `prepared_before_browser_running` / `executed=false` / no replay.

## Recovery states

- PREPARED, cursor absent or no post-cursor Browser receipt:
  `prepared_before_browser_running`, executed=false, no dispatch, no replay.
- exact post-cursor running receipt, no terminal:
  `browser_running_outcome_unknown`, outcome unknown, no replay.
- one exact post-cursor terminal receipt:
  `browser_terminal_exact`; reconstruct the factual tool result from that exact receipt,
  append the recovered tool message, and settle the outer receipt-committed WAL fact.
- invalid/ambiguous receipt suffix:
  fail closed to the existing generic `started_outcome_unknown`; never replay.

The correlator has no BrowserActionAdapter, actuator, `.dispatch(`, selector, similarity,
latest-target, successor, search, or rebind surface.

## Deterministic qualification

Pre-GREEN expected-failure taxonomy SHA-256:

`a99e5462518c1bff7f06cf029557271469fb066b16d8bc6942007271c145b747`

Pre-GREEN evidence SHA-256:

`aeb12eb874c4d9ce686bd794c544e7e0b51dcdb1ade5f24e53bf039ab089ce8f`

GREEN evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S3-v0.1-20260920/EVIDENCE.json`

GREEN evidence SHA-256:

`08988602c4c21780ff9497ca69bf1c36c363056c0c51c0a7a4b633858d9101a3`

Focused S3 qualification is 12/12 PASS and includes fault cuts for PREPARED, running, and
terminal receipts, old-terminal exclusion, exact rejected-terminal recovery, ambiguity
fail-closed, cursor immutability, and inert legacy construction.

The GREEN-1/P4-LIVE frozen matrix remains intentionally unchanged at this slice boundary:
all end-to-end R10-R19 remain RED, including R16/R17/R18, because no typed ActionRef
mutation path consumes the S3 primitives yet. Their original failure taxonomy remains
exactly preserved.

## Stop boundary

G2-S3 stops before G2-S4. No physical ActionRef Browser dispatch exists yet. G2-S4 must
compose S1/S2/S3 only behind a separate default-OFF mutation exposure gate and must write
the S3 receipt cursor before entering `BrowserActionAdapter.execute()`.
