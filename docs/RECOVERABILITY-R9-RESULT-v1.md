# Evidence Recoverability R9 — Evidence-Aware Source Resolution Result v1

Date: 2026-08-26
Status: **OFFLINE PASS / SEALED**
A3: STOPPED
Production Evidence mode: unchanged/off

## Root cause addressed

R8 proved that a provider can precommit `search_evidence` and an overlapping `read_file` fallback in the same assistant tool-call batch. Function-calling protocol requires a result for every declaration, and provider-level parallel-call disabling is not portable. The prior registry therefore physically executed a source fallback even though durable current Evidence already covered the requested bytes.

R9 fixes the source-resolution layer rather than suppressing declarations.

## Implemented contract

In Evidence enforce mode, probeable FILE `read_file` requests are resolved before physical source I/O:

- same owner/source;
- FILE + PROBEABLE;
- `verified_current`;
- existing source-line coverage fully contains requested coverage;
- `force_refresh` is false.

When all hold, the declared `read_file` receives a truthful SUCCESS result with the existing EvidenceRef, `source_resolution_mode=evidence_reuse`, and `source_execution_performed=false`. The file is not physically read and no new EvidenceRecord is created.

Stale/unknown Evidence, coverage gaps, missing Evidence, or `force_refresh=true` still execute the file read and capture a new immutable EvidenceRecord. Off/shadow retain legacy execution behavior.

## Protocol properties

- No assistant tool call is deleted or rewritten.
- Every declared call still gets exactly one tool result.
- `execute_many()` remains capable of concurrent independent read-only calls.
- No repeat fingerprint, anti-repeat phrase or Action Guard is used.
- Commands/web/runtime sources are not auto-reused because their currentness cannot be proven by the existing freshness engine.

## Verification

TDD first RED: missing `llm_loop.tools.evidence_source_resolver` module.

Final verification:

- R9 source-resolution focused tests: PASS.
- Exact R8 mechanism offline reproduction: `search_evidence + overlapping read_file` in one `execute_many()` batch -> search succeeds; read_file resolves as Evidence reuse; physical read count remains 1; ledger count remains 1.
- stale -> physical new acquisition/new record: PASS.
- real coverage gap -> physical acquisition: PASS.
- `force_refresh=true` escape hatch -> physical acquisition: PASS.
- ToolResult -> Message structured source-resolution metadata: PASS.
- surrounding R3/R6/Evidence tests: PASS.
- targeted Ruff: PASS.
- targeted Pyright: 0 errors / 0 warnings.
- all Evidence tests: PASS.
- R0 aggregate: 12/12 PASS.
- full repository regression excluding only already-stopped A3 development test: EXIT 0 / 100% PASS.

## Remaining distinction

R9 removes redundant *physical source acquisition* and large repeated source observations. It cannot erase an assistant tool-call declaration that the provider already emitted in the same response; standard tool-call pairing requires a truthful result. Such a fallback now produces a small stable Evidence-reuse result instead of source I/O/new Evidence. R10 will measure this distinction on fresh real-provider traces.
