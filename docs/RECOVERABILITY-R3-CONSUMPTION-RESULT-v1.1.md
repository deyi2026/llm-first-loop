# Evidence Recoverability R3 — Consumption Contract Result v1.1

Date: 2026-08-26
Supersedes: `RECOVERABILITY-R3-CONSUMPTION-RESULT-v1.md`
Contract: `RECOVERABILITY-R3-CONSUMPTION-CONTRACT-v1.md` + `RECOVERABILITY-R3-CONSUMPTION-AMENDMENT-v1.1.md`
Status: **OFFLINE DETERMINISTIC PASS**
Provider calls in R3: **0**
Production activation: **NO**
A3: **STOPPED**

## What v1.1 closes

R3 v1 introduced structured hydration and safe-by-default stale FILE reads. A production-control-plane audit then found a horizontal bypass: `search_evidence` refreshed a stale FILE's freshness but still returned the stale match snippet, and `search_archive` inherited that path.

v1.1 makes freshness semantics consistent across recovery entry points.

### `read_evidence`

- JSON `schema=evidence_hydration_v2` separates transport identity from domain content.
- `transport.evidence_ref` is explicitly `role=recovery_handle`, `is_domain_content=false`.
- pagination is typed as `range.complete` + `range.next_start`.
- probeable FILE + `stale` is blocked by default with no old content.
- explicit `allow_stale=true` restores exact historical bytes while retaining `currentness=historical_only`.

### `search_evidence` and `search_archive`

- both expose `allow_stale: boolean`, default false.
- a stale probeable FILE hit defaults to metadata only:
  `freshness=stale currentness=historical_only content=blocked historical_search_requires=allow_stale=true`.
- the stale match snippet is not exposed on the default path.
- explicit `allow_stale=true` may return the historical snippet, still marked stale/historical-only.
- owner isolation, lexical grammar and non-stale search behavior are unchanged.

### Recovery Manifest

Every entry carries currentness derived from durable freshness:

- verified_current -> current
- stale -> historical_only
- unknown -> unverified

## Verification

- R3 v1.1 semantic/wire tests: **5/5 PASS**.
- all Evidence tests: **104/104 PASS**.
- R0 aggregate: **12/12 PASS**.
- targeted Ruff: **PASS**.
- targeted Pyright: **0 errors / 0 warnings**.
- full repository non-real-provider suite excluding only the stopped A3 broken-import development test: **exit 0**.
- production `.env`: `EVIDENCE_MODE` remains unset -> off; `TOOL_PIPELINE_ENABLED=1`.

No provider confirmation is claimed from R3; R2 remains the last provider result and remains FAIL.

## Final artifact hashes

- `src/llm_loop/tools/evidence_tools.py`:
  `a4407ab27861fb4d32c1ed8a64ef55cdb053c6efdaf729bee371f9bf57293487`
- `src/llm_loop/memory/evidence.py`:
  `706120777747fad9a23ea428b330bb77fe4f575c12374015f1ad6a7579f6c9f1`
- `tests/unit/test_evidence_phase8.py`:
  `7d12456c4313aaceacbe57bb7b238d704f73fb44d65c35be03b5b10e87e12b32`
- `docs/RECOVERABILITY-R3-CONSUMPTION-AMENDMENT-v1.1.md`:
  `4593fe1dd2f230f530976a713ca612170d5a6dd8cf0705d563ad6d7a3d96d737`
- frozen original `ev_recov/spec.md` remains:
  `97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771`
- frozen original `ev_recov/design.md` remains:
  `95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b`

## Decision

R3 v1.1 is eligible for a **fresh holdout only**, not production enforce.

The next experiment must:

1. use an entirely new fixture family;
2. call production `EvidenceEnforcer`, `EvidenceReadTool`, `EvidenceSearchTool`, `EvidenceListTool`, freshness probes and Recovery Manifest rendering directly;
3. include multi-page evidence, transport/domain identity, current-stale refresh and explicit historical stale access;
4. mechanically prevent concurrent duplicate runners;
5. freeze fixtures, matrix, runner and scorer before the first provider request.
