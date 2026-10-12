# MF534-R2 Peer-Capability Routing — Compact Description Only Paired A/B v0.1

Status: **FROZEN BEFORE ANY MF534-R2 MODEL REQUEST**
Date: 2026-09-17

## Question

Does the deterministic RED's compact-description-only peer-binding hypothesis reduce real Ornith first-call Perceive/Operate routing failures on the frozen MF534 task family, without changing tool names, `action`/`do`, parameter schemas, runtime mechanics, grounding authority, or task/safety behavior?

This is a local model-behavior qualification, not a production change and not a cross-model generalization claim.

## Arms

- **A — current control:** exact current compact descriptions at production anchor `d908adbf`; no harness patch.
- **B — description-only treatment:** the worker appends only two peer-binding sentences to the compact descriptions:
  - `browser_perceive.action` is only `snapshot|hydrate|diff|wait`; navigation must use `browser_operate(do=navigate,url=...)`.
  - navigation is bound to `browser_operate(do=navigate,url=...)`; `browser_perceive.action` is for `snapshot|hydrate|diff|wait`.

B is applied only inside the isolated qualification worker process by replacing the two `_COMPACT_TOOL_DESCRIPTIONS` strings before `build_engine`. No tracked production file is edited.

## Frozen identity

- Routing RED anchor: `3fe30b5c07a34394b6c46234c554d5d7789ff47e`.
- Production compact-description anchor: `d908adbf58610e1c136ede69b33203acc7422207`.
- `src/` and `methods/` must be byte-identical to the production anchor.
- Model/runtime: the single existing Ornith MLX server on `127.0.0.1:8901`; prompt/decode concurrency `1/1`, max output 16000; no second local model and no fallback.
- Provider contract: input 184000, output 16000, temperature 0, top_p 1, top_k 0, min_p 0, OpenAI wire protocol.
- Browser mechanics, fixture, prompts, external oracles and max iterations=12 are inherited unchanged from MF534.

## Matrix

Twelve serial fresh-state rows. Each of the six MF534 task/repeat pairs appears once in A and once in B. Pair order alternates which arm runs first, matching the established MF5 paired ordering discipline:

1. click_commit-r1 A
2. click_commit-r1 B
3. fill_submit-r1 B
4. fill_submit-r1 A
5. delayed_wait-r1 A
6. delayed_wait-r1 B
7. delayed_wait-r2 B
8. delayed_wait-r2 A
9. fill_submit-r2 A
10. fill_submit-r2 B
11. click_commit-r2 B
12. click_commit-r2 A

Every row gets a fresh LFL session, DATA_DIR, Chrome profile and fixture state. No row replay under this protocol identity.

## Primary routing measurement

First Browser call is scored independently of later recovery and final task success. A cross-capability first call such as `browser_perceive(action=navigate, ...)` remains **routing FAIL** even if the next call correctly uses `browser_operate(do=navigate, ...)` and the external task oracle eventually passes.

Per arm report:

- first-call routing PASS / 6;
- cross-capability routing failures;
- later recovery count;
- protocol-repair episodes and `get_tool_schema` calls;
- task oracle PASS / 6;
- rounds, tokens, cache-hit tokens and tool calls.

## Measurement validity and treatment signal

Measurement is valid only when both arms complete 6/6 rows, both external task oracles are 6/6, exact surfaces are preserved, no fallback/SecurityAgent appears, and mechanical hard boundaries remain clean: zero operation failure/error, hidden atomic Browser call, duplicate successful mutation, automatic mutation retry, task-completion judgment, undeclared continuation and unparsed operation receipt.

Perceive failures caused by the very routing defect under measurement do **not** invalidate the experiment; they remain counted as routing/protocol-repair evidence.

Treatment signal is preregistered mechanically:

- `IMPROVED`: B has more first-call routing PASS rows **and** fewer cross-capability failures than A.
- `NO_OBSERVED_IMPROVEMENT`: the two routing counts are equal.
- `REGRESSED_OR_MIXED`: all other valid outcomes.
- `INVALID`: measurement validity fails.

This signal is descriptive for this frozen 6-pair sample only; it is not a statistical or cross-model claim.

## Zero-model preflight

`run_ab.py --max-new-rows 0` must make zero model generation requests and must prove before measured execution that:

- A/B tool names and parameter schemas are identical;
- full provider surface is identical;
- lazy provider surfaces differ;
- actual worker compact-description hashes match the deterministic A/B hypothesis;
- deterministic A remains RED and deterministic B is GREEN;
- current HEAD is clean and production code has not changed after `d908adbf`;
- 8901 identity and provider contract match the frozen values.
