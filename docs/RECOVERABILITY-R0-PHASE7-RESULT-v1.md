# Evidence Recoverability R0 Phase 7 Result v1

Date: 2026-08-26
Status: **PASS — 12/12 blocking R0 gates**
Provider API calls: **0 (network mechanically denied)**
Production activation: **NO configuration change**

## Purpose

Phase 7 is the frozen Full-R0 aggregate gate. It does not add another recovery mechanism; it proves
that the mechanisms established in Phases 1–6 jointly satisfy the original `R0-v1.1` oracle without
manual interpretation or near-pass override.

## Frozen inputs

- Oracle: `tests/fixtures/evidence_recoverability_r0.json`
- Oracle version: `R0-v1.1`
- Spec SHA-256: `97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771`
- Design SHA-256: `95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b`
- Gate map: `tests/fixtures/evidence_r0_phase7_gate_v1.json`
- Every R0 case is blocking; no near-pass/manual override exists.

## Aggregate runner

`scripts/evidence/run_r0_gate.py` validates that the gate map covers exactly R0-1..R0-12 and that
each case's `covers` set equals the frozen oracle clauses. It verifies the frozen spec/design hashes,
then runs each R0 case in an independent pytest process.

Every process loads `scripts/evidence/r0_no_network.py`, which replaces non-UNIX socket
`connect/connect_ex` with an assertion failure. Therefore the R0 statement "no real provider" is an
execution constraint, not a convention.

Machine-readable report:

`data/audit/evidence_r0_phase7_gate_v1.json`

## R0 results

| Gate | Result | Mechanical meaning |
|---|---|---|
| R0-1 | PASS | Large observation survives compression/rebuild/provider switch; exact hidden middle is hydrated; source executes once |
| R0-2 | PASS | Blob identity is physical; Evidence identity remains owner/capture scoped |
| R0-3 | PASS | Cross-owner read/list denied; BlobRef is not a model credential |
| R0-4 | PASS | Unicode char/line hydration, hard bounds, continuation and range hash are exact |
| R0-5 | PASS | Bounded queryless manifest rebuilds from durable Ledger |
| R0-6 | PASS | FILE freshness is probeable; command/web/runtime never fabricate currentness |
| R0-7 | PASS | Side-effect action truth survives capture failure and is never auto-rerun |
| R0-8 | PASS | Frozen AND/OR/phrase/middle-match/owner-isolation search gold is exact |
| R0-9 | PASS | Provider raw projections may differ while authorized ref set, ref→Blob mapping and manifest refs remain identical |
| R0-10 | PASS | Proven legacy owner migrates; orphan is model-invisible; shared blob deletes only after last owner |
| R0-11 | PASS | HOT is relevance, not forced FULL; large HOT Evidence may be excerpt+ref |
| R0-12 | PASS | No Action Guard, prompt anti-repeat patch, fixed-summary activation, semantic heuristic or provider call entered R0 |

Aggregate execution result: **PASS 12/12**.

## Strong R0-9 addition

Phase 7 deliberately tightened provider-switch validation beyond the earlier development test. The
new case constructs provider-dependent raw history visibility but performs no new compression
capture. Across DeepSeek -> MiniMax -> DeepSeek builds it asserts exact equality of:

1. authorized EvidenceRef set;
2. EvidenceRef -> BlobRef mapping; and
3. Recovery Manifest ref set.

This closes the gap between "provider switch did not duplicate an existing record" and the frozen
oracle's stronger requirement that provider projection does not alter semantic Evidence identity.

## R0-12 guardrail audit

The gate additionally proves:

- `EVIDENCE_MODE` defaults to `off`;
- no Action Guard implementation exists in production `src`;
- `src/llm_loop/core/prompt.py` contains no anti-repeat-query repair phrase;
- `fixed_summary` / `summary_chain` remain persistence fields and are not consumed by the core loop;
- no `extract_supports()` heuristic exists;
- spec/design hashes are unchanged; and
- provider/network access is denied by the runner plugin.

Post-run Git audit also shows no diff in `core/prompt.py`, the stopped A3 test, or the frozen ERC
spec/design documents.

## Verification layers

- Phase7 self-tests: PASS.
- Aggregate runner: **12/12 PASS**.
- All Evidence tests (89 tests) under no-network plugin: **PASS**.
- Phase7 Ruff: PASS.
- Phase7 Pyright: **0 errors / 0 warnings**.
- Full repository non-real-LLM suite:
  `PYTHONPATH=src .venv/bin/pytest -q --ignore=tests/unit/test_action_guard_a3.py` -> **exit 0**.
- A3 is the previously stopped development artifact with an unrelated broken import and remains
  outside this R0 line.

## Runtime boundary

Current `.env` remains:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

The existing enforce+enabled ToolExecutionPipeline combination is intentionally fail-closed until
post-hook/capsule ordering is explicitly integrated. Phase 7 does not weaken that gate.
