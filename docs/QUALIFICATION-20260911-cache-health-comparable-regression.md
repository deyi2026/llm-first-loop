# Cache Health Comparable-Regression Convergence Qualification — 2026-09-11

> **Verdict:** PASS / ADMIT the current-tree reconstruction.
> **Integration parent:** `integration/convergence-20260911@cae0b8558b81915054316ec93aad028d254d7853`.
> **Source evidence:** `fix/cache-health-comparable-regression@b051bb74191d65990927497d60035682e5b52ab6`.
> **Qualified implementation:** `875dcf08520698501daf5e145ed7fbd72930bd71`.

## 1. Why the source commit was not merged wholesale

The source commit was created on an older lineage. Its core purpose remains valid: a low cache-hit ratio by itself does not prove an application regression, and cold start, provider TTL expiry, model/provider changes, compaction and cache-boundary changes must not be reported as the same condition as a comparable absolute-hit drop.

The current integration tree now has the separately qualified cache-prefix double-axis contract. That contract distinguishes:

- `system_fp`: system-axis drift used by the existing reversible cache-head control;
- `tools_fp`: legal tool-surface change observation;
- combined `cache_gate_stable_fp`: the physical cache-boundary identity including the stable chat prefix and exact projected tool array.

Therefore cache-health comparability must consume the **combined** boundary identity without taking over double-axis drift policy.

## 2. Qualified mechanical contract

For each session, `PromptGuard` keeps only bounded process-local request/result shape facts. A transition is comparable only when all of the following are mechanically true:

1. the next result belongs to the immediately following round of the same run sequence;
2. provider is unchanged;
3. model is unchanged;
4. combined stable cache-boundary fingerprint is unchanged;
5. cache-prefix epoch is unchanged;
6. compaction epoch is unchanged;
7. provider cache TTL has not elapsed;
8. prompt token count has not shrunk.

If these conditions hold, the absolute cache-hit token delta is observed:

- negative delta -> `regression`;
- zero/positive delta -> `healthy`.

If the shape changed, the result is classified as `warmup` with a mechanical reason. Missing shape is `unknown`.

The regression output is a **WARN/telemetry fact only**. It does not select a model, choose a tool, block a task, change cache admission, alter completion judgment, or inject new semantic task instructions.

## 3. Current-tree fallback correction

The old source patch read `self._host._run_state()` directly inside `FallbackService`. Current full-suite qualification exposed that this creates an invalid hard dependency on a LoopEngine-private method for historical duck-host integrations.

The qualified reconstruction instead uses `_guard_cache_shape()`:

- real `LoopEngine` hosts expose RunState, so fallback requests receive the candidate request's combined cache-boundary fingerprint and epochs;
- the read occurs **after** the fallback request builder, so the shape belongs to the rebuilt fallback candidate rather than the failed primary request;
- duck hosts that do not expose RunState return unknown cache telemetry instead of failing the fallback availability path;
- any cache-shape read error is fail-open telemetry only.

This preserves fallback mechanics while keeping cache observability non-authoritative for availability.

## 4. RED -> GREEN evidence

A current-tree regression file was added before implementation. On the integration parent all four cases failed because `PromptGuard.check()` did not accept the required cache-shape facts.

Covered cases:

- comparable absolute hit drop -> regression + WARN;
- combined stable-prefix change -> warmup, not regression;
- compaction epoch change -> warmup, not regression;
- comparable absolute hit non-decrease -> healthy.

After the reconstruction these tests pass. An additional duck-host test proves that fallback cache-shape observation is optional and that a production-like RunState yields the expected exact tuple.

## 5. Provider-visible invariants

Actual `build_engine` parent/candidate comparison, with deterministic isolated settings and canonical JSON serialization:

```text
registered tool schemas
  parent    62 / SHA 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
  candidate 62 / SHA 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484

runtime-health projected provider tool params
  parent    60 / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  candidate 60 / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8

Universal Prompt
  parent    192 chars / SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
  candidate 192 chars / SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
```

No provider-visible prompt/tool delta is introduced.

## 6. Verification

Candidate-level gates:

```text
current-tree RED                           4/4 expected FAIL before implementation
cache focused/adjacent                    98/98 PASS after initial reconstruction
fallback compatibility RED                1 full-suite failure caught and fixed
post-fix focused duck/fallback             6/6 PASS
expanded cache/LLM/fallback/model-pool     202/202 PASS
Ruff changed Python                       PASS
py_compile changed Python                 PASS
Pyright repository                        0 errors / 0 warnings / 0 informations
git diff --check                          PASS
full pytest tests -q -m 'not real_llm'    RC=0 (~164s)
Git security hook                         PASS
```

The full run emitted only existing dependency/test-audit warnings.

## 7. Admission ruling

**PASS / ADMIT** `875dcf0` as the current-tree replacement for source `b051bb7`.

The source branch remains provenance only and is not a merge unit. The qualified behavior remains subordinate to the existing cache-axis contract: double-axis mechanics decide drift attribution, while this change only classifies whether returned cache-hit tokens are comparable across adjacent request shapes.
