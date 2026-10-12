# Evidence Recoverability R3 — Consumption Contract Result v1

Date: 2026-08-26
Input: `docs/RECOVERABILITY-R2-RESULT-v1.md`
Status: **OFFLINE DETERMINISTIC PASS**
Provider calls in R3: **0**
Production activation: **NO**

## Result

R3 implements the model-facing data-contract fixes exposed by the R2 FAIL without adding Action Guard, duplicate suppression, or anti-repeat prompt patches.

### Structured hydration

`read_evidence` now returns JSON schema `evidence_hydration_v2` with explicit separation between:

- `transport.evidence_ref` — role=`recovery_handle`, `is_domain_content=false`;
- exact hydrated domain bytes — only under `content`;
- `range.complete` and `range.next_start`;
- source kind/label/tool/coverage;
- freshness/currentness;
- blob/range integrity hashes.

This removes the R2 ambiguity where a provider could treat an `evidence://...` transport identifier as the requested business identifier, and makes incomplete pagination a typed state instead of a free-text convention.

### Safe stale FILE handling

For a probeable FILE whose captured version is now stale:

- default `read_evidence` returns FAILURE with a structured `evidence_hydration_blocked` envelope;
- stale bytes are not returned by default;
- `refresh_required=true` is explicit;
- exact old bytes remain available only through explicit `allow_stale=true` historical/audit access;
- historical access remains tagged `freshness=stale`, `currentness=historical_only`.

The contract therefore preserves historical evidence without letting probeably stale FILE bytes silently masquerade as current evidence on the default path.

### Recovery Manifest

Manifest entries now render currentness derived from durable freshness state:

- `verified_current -> current`
- `stale -> historical_only`
- `unknown -> unverified`

## Verification

- R3 semantic tests: **4/4 PASS**;
- R3 wire/schema assertions: PASS;
- Phase4-7 focused recovery tests: PASS;
- all Evidence tests: PASS;
- R0 aggregate gate: **PASS 12/12**;
- targeted Ruff: PASS;
- targeted Pyright: **0 errors / 0 warnings**;
- full repository non-real-provider suite excluding only stopped A3 broken-import test: **exit 0**.

Runtime remains:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

No production rollout was activated.

## Artifact hashes

- `src/llm_loop/tools/evidence_tools.py`: `2ef2ff4080765134c1497002fcd42717460de8199832ec422bd81cbb08d435e0`
- `src/llm_loop/memory/evidence.py`: `706120777747fad9a23ea428b330bb77fe4f575c12374015f1ad6a7579f6c9f1`
- `docs/RECOVERABILITY-R3-CONSUMPTION-CONTRACT-v1.md`: `7cb40eaa63296b8b368dc0787f2c87f02769b3eca59083b44bf40d3934c59180`

The final test-file hash is recorded below after the wire assertions were added.

## Decision

R3 closes the deterministic interface defects exposed by R2, but it does **not** override the R2 provider FAIL. Production enforce remains ineligible until a fresh provider holdout confirms that the production structured contract is actually consumed correctly across providers, including:

1. multi-page incomplete Evidence;
2. transport-ref/domain-value separation;
3. stale-current task requiring refresh;
4. explicit historical stale access without over-blocking.

The next holdout must use a new fixture family and invoke production Evidence tools directly; R2 fixtures/results must not be reused as confirmatory data.
