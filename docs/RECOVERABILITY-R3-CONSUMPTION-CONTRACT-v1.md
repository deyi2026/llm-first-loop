# Evidence Recoverability R3 — Consumption Contract v1

Date: 2026-08-26
Input evidence: `docs/RECOVERABILITY-R2-RESULT-v1.md`
Status: **OFFLINE CONTRACT — no provider request**
A3: **STOPPED**

## Why R3 exists

R2 proved two facts at the same time:

1. stable Evidence eliminated reusable-source re-execution in the E1 arm (0/30 vs B0 18/30), so R0/R1 recoverability continuity remains valid;
2. providers can still misuse the recovery interface: stop after an incomplete page, confuse a transport EvidenceRef with a domain value, or use stale file Evidence as current truth.

R3 fixes the model-facing Evidence **data contract**, not model behavior through an anti-repeat prompt.

## R3-C1 Structured hydration envelope

A successful `read_evidence` result MUST expose a machine-readable JSON object with:

- `schema=evidence_hydration_v2`;
- `kind=evidence_hydration`;
- `transport.evidence_ref`;
- `transport.role=recovery_handle`;
- `transport.is_domain_content=false`;
- `source.kind`, safe `source.label`, original `source.tool_name` and coverage;
- `freshness.state` and `freshness.currentness`;
- `range.type/start/count/next_start/complete`;
- blob/range integrity hashes;
- exact hydrated bytes only under `content`.

The EvidenceRef is therefore mechanically separated from domain content.

## R3-C2 Completeness is explicit state

For bounded hydration:

```text
next_start != null  <=>  range.complete == false
next_start == null  <=>  range.complete == true
```

The contract does not claim it can force an LLM to continue, but it removes ambiguity between "this page succeeded" and "the observation is complete".

## R3-C3 Probeable stale FILE is safe-by-default

`EvidenceFreshness.refresh()` already mechanically detects whether a version-token-backed FILE changed.

When a probeable FILE Evidence becomes `stale`:

- `read_evidence(... allow_stale omitted/false)` MUST NOT return the stale content;
- it returns a structured failure envelope with `currentness=historical_only`, `refresh_required=true`, and an explicit statement that historical hydration requires `allow_stale=true`;
- `read_evidence(... allow_stale=true)` may return exact old bytes, but the success envelope MUST retain `freshness=stale` and `currentness=historical_only`.

This preserves audit/history use cases while making stale-as-current unsafe by default.

Non-probeable command/web/runtime observations are not fabricated as current. Existing UNKNOWN semantics remain; R3 does not guess currentness.

## R3-C4 Recovery Manifest currentness

Every manifest entry MUST render a currentness class derived from durable freshness state:

- `verified_current -> current`;
- `stale -> historical_only`;
- `unknown -> unverified`.

This is state presentation, not a new instruction or Action Guard.

## Non-goals

R3 does NOT:

- add duplicate suppression or Action Guard;
- hide repeated tool calls from metrics;
- change cache prefix policy;
- alter R0 Evidence identity/Blob identity;
- make stale bytes inaccessible for explicit historical/audit use;
- run MiniMax/DeepSeek before deterministic offline tests pass.

## Offline exit gate

1. new R3 tests PASS;
2. Phase0-7 Evidence tests remain PASS;
3. targeted Ruff/Pyright PASS;
4. R0 aggregate 12/12 remains PASS;
5. production `EVIDENCE_MODE` remains unchanged.

Only after this gate should a fresh provider holdout be designed; R2 fixtures/results are not reused as confirmatory data.
