# R2 Infra-Only Runner Amendment v1.1

Date: 2026-08-26
Status: **ALLOWED INFRA-ONLY AMENDMENT AFTER FIRST REAL REQUEST**

## Trigger

The first frozen R2 real batch was paused after 13 persisted row files. Twelve rows were `COMPLETED`; `R2-011` (MiniMax, F4/E1) remained `INFRA_FAILURE` after the preregistered one infra retry.

The failure was:

`ValueError: invalid EvidenceRef prefix`

Trace inspection showed that MiniMax called `read_evidence` before it had acquired a valid EvidenceRef. The runner constructed `EvidenceRef(...)` directly and allowed this model-supplied invalid tool argument to escape into the run-level exception handler.

That classification was wrong: an invalid tool argument is a tool-level behavioral failure and must be returned to the model as a failed tool result. It is not provider or runner infrastructure failure and must not terminate the conversation.

## Amendment

Runner-only v1.1 change:

1. `read_evidence` invocation attempts are counted separately.
2. `EvidenceRef` validation / Evidence lookup errors caused by model-supplied arguments are converted into a deterministic failed tool result and appended with the original `tool_call_id`.
3. The model conversation continues after that failed tool result.
4. `evidence_hydration_count` increments only after successful exact hydration; invalid attempts cannot satisfy the frozen hydration gate.
5. `evidence_hydration_attempt_count` is added only as diagnostic telemetry.

No source action behavior, projection, freshness rule, provider parameter, task text, tool schema, or scoring rule changed.

## Frozen artifacts unchanged

The following SHA-256 values are unchanged from pre-real freeze:

- scorer: `3c00a0b13d252c2bcf9e5c0e53991555b485d19a920521f6a51da2b4af88ac82`
- matrix: `de47c6b4ce322561f12ffa6bd68eff815a828607833b4c899a6fcf8ed8205dcf`
- fixture bytes: `f00e268dc1fa3c621ad4e46346352f002f4e049b37808eeeebe23229b2ed0135`
- R2 pre-registration: `ca26b2c31fdf73f960755c1417032bbd0ab8b6ecb78d35d23c492295168e7be0`

Runner changes from pre-real SHA `50fbd1b041f699413eb7ccc386061b06cab1514a450d3da02dc4aef2b75e36f2` to v1.1 SHA `abb3cb57b268525386fbaabba1c9c12f0ce2b167333f4a078ed13486be618147`.

R2 test file becomes SHA `44a6d54e0afc4e3e77c7aed43b8e9601de7e1db2b23321edcaa431a32a172281` because it adds the regression proving invalid EvidenceRef input does not become `INFRA_FAILURE`.

## Verification before resume

- targeted R2 tests: **7/7 PASS**
- targeted Ruff: **PASS**
- targeted Pyright: **0 errors / 0 warnings**
- full frozen dry matrix with runner v1.1: **72/72 execution PASS**
- frozen scorer on v1.1 dry output: **PASS**

## Resume discipline

Completed pre-amendment rows are retained because the amended branch was not exercised in those completed traces. `R2-011` remains non-completed and therefore is automatically rerun under v1.1. All later rows run under v1.1. No completed behavioral row is reissued merely because of the infra-only amendment.
