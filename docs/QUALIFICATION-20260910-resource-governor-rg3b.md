# RG-3B Transport Observation / Shadow — Qualification

> Date: 2026-09-10
> Implementation: `e901e61 feat(resources): observe RG-3B provider transport facts`
> Parent: `8c88218 docs(resources): record RG-3A qualification`
> Verdict: **PASS / CLOSE for RG-3B shadow scope**

## 1. Qualified scope

RG-3B qualifies only the transport-observation side channel:

- safe typed HTTP response facts;
- nullable provider usage facts;
- safe typed HTTP/SSE error facts;
- standard Retry-After normalization;
- narrowly proven generic request/token rate-limit header normalization;
- one bounded process-local recorder shared by default and routed LLM clients.

It does **not** qualify or enable cloud admission/enforcement, durable settlement, quota/cost accounting, fallback changes, TrustDomain, cancellation or model-selection policy.

## 2. Implementation boundary

Implementation commit changes exactly 9 files:

```text
docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md
docs/DESIGN-20260910-resource-governor-rg3b-transport-shadow.md
src/llm_loop/factory.py
src/llm_loop/llm/client.py
src/llm_loop/llm/pool.py
src/llm_loop/resources/__init__.py
src/llm_loop/resources/contracts.py
src/llm_loop/resources/transport_observation.py
tests/unit/test_resource_transport_shadow.py
```

`ResourceGovernor` and `resources/provider_calls.py` do not import or consume RG-3B shadow facts.

## 3. Safety / truthfulness properties

### 3.1 No raw transport retention

Typed shadow facts cannot contain raw headers, raw response body, prompt/messages, API key, Authorization, Cookie or task text.

The recorder receives raw header mappings only transiently for allowlisted parsing and stores only normalized typed facts.

### 3.2 Provider code is not error prose

HTTP-body provider code extraction accepts only structured JSON `error.code` or top-level `code`, then requires a short code-like scalar. A body such as:

```json
{"error":"private_diagnostic_tokenlike"}
```

produces `provider_code=None`; it is not reclassified as a code and is not retained by the shadow recorder.

For HTTP 200 + SSE error, RG-3B keeps HTTP status and provider code as separate facts. If the SSE event has no explicit provider code, shadow does not fabricate `500`; legacy exception behavior remains unchanged.

### 3.3 Unknown is not zero

Raw OpenAI-compatible usage is observed before the legacy `LLMResponse` accumulator:

```text
field absent/invalid -> None
provider reports 0  -> 0
provider reports N  -> N
```

A usage mapping with no valid typed value creates no usage fact.

### 3.4 Reset values are not guessed

Standard `Retry-After` delta-seconds and HTTP-date are normalized.

Generic `x-ratelimit-reset-*` values are normalized only when an explicit duration unit is present (`ms`, `s`, `m`, `h`). Bare numeric values stay unknown because providers may use duration or epoch semantics. Vendor-specific interpretation is deferred to RG-3D.

## 4. Deterministic tests

RG-3B regression coverage proves:

- reported zero usage survives as zero;
- unreported/invalid usage stays unknown;
- HTTP 429 maps to typed status/provider-code/Retry-After/rate facts;
- HTTP-date Retry-After normalization;
- HTTP 200 + SSE error preserves HTTP/provider identity layers;
- arbitrary error prose is not retained as provider code;
- raw/secret headers and body are absent from stored facts;
- observer failure is fail-open for both success and original HTTP error behavior;
- recorder is bounded;
- ambiguous bare numeric rate reset is not guessed;
- default + routed clients share one recorder;
- ResourceGovernor/provider admission do not consume shadow facts.

Broader provider/resource/fallback/factory/Learning/SubAgent adjacency suite: **PASS**.

## 5. Real cloud transport qualification

Credential availability was checked only as `present/absent`; no secret was printed or persisted. Each provider received at most one tiny request in the final committed qualification run. Prompt/answer/raw body/raw headers were not logged in the qualification output. No provider was intentionally driven into 429.

### DeepSeek

```text
configured model: deepseek-flash
transport HTTP status: 200
legacy call outcome: success
typed usage:
  input_tokens=34
  output_tokens=11
  cached_input_tokens=0
  reasoning_tokens=9
  total_tokens=45
Retry-After observed: no
generic proven rate/reset facts observed: no
```

### GLM

```text
configured model: glm-5.3
transport HTTP status: 200
typed usage:
  input_tokens=16
  output_tokens=32
  cached_input_tokens=0
  reasoning_tokens=31
  total_tokens=48
Retry-After observed: no
generic proven rate/reset facts observed: no
```

The tiny canary deliberately capped output at 32 tokens. GLM's always-on reasoning consumed essentially the whole output budget, so the legacy client ultimately raised `LLMEmptyResponseError` because it had no visible final text. This is **not** an HTTP/resource failure and was not retried: RG-3B had already correctly observed the real HTTP 200 response and provider usage. The result is useful evidence that transport observation is independent of application-level visible-answer success.

### MiniMax

```text
configured model: MiniMax-M3
transport HTTP status: 200
legacy call outcome: success
typed usage:
  input_tokens=180
  output_tokens=21
  cached_input_tokens=128
  reasoning_tokens=0
  total_tokens=201
Retry-After observed: no
generic proven rate/reset facts observed: no
```

### Live interpretation

All three current provider paths produced typed transport observations on the committed implementation. None of the three returned a rate-limit/reset header whose meaning RG-3B can generically prove, so the correct result is **no rate/reset fact**, not a value copied from documentation or inferred from provider identity.

Real 429 was not intentionally induced. 429/Retry-After/error normalization is qualified deterministically with HTTP transport fixtures; a natural future 429 can be observed by the same shadow path without changing request behavior.

## 6. Model-visible invariants

Actual parent/candidate `build_engine` comparison:

```text
registered provider parameter surface
  parent    62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37
  candidate 62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37
  identical true

projected provider parameter surface
  parent    60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  candidate 60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  identical true

Universal Prompt source SHA
  parent    30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
  candidate 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
  byte-identical true
```

RG-3B therefore does not alter the model's prompt or tool surface.

## 7. Static and full regression gates

### Pre-commit candidate

```text
implementation files                    9
staged security                         PASS
git diff --check                        PASS
Ruff src/tests                          PASS
Pyright                                 0 errors / 0 warnings / 0 informations
py_compile changed runtime files        PASS
broader adjacency                       PASS
full pytest -m 'not real_llm'           100% / exit 0 / 154.7s
```

A first full run found exactly one architecture-guard failure: the new recorder import had been placed inside `build_engine`, increasing Factory's function-local import ratchet from 63 to 64. The fix moved that import to the module import section; the baseline was not raised and no exception/allowlist was added. The second full run then passed completely.

### Clean committed implementation `e901e61`

```text
git show --check                        PASS
Ruff src/tests                          PASS
Pyright                                 0 errors / 0 warnings / 0 informations
py_compile changed runtime files        PASS
tracked-tree security                   PASS (1496 files)
broader committed adjacency             PASS
full pytest -m 'not real_llm'           100% / exit 0 / 156.8s
real DeepSeek/GLM/MiniMax canary         PASS for transport-observation scope
```

## 8. Known boundaries carried forward

RG-3B intentionally leaves these open:

1. no durable call identity or idempotent usage ledger;
2. multiple usage chunks are observations, not a settled call total;
3. retry/fallback attempts are not yet grouped into one accounting topology;
4. Task/SubAgent/Learning/MemoryExtractor/Summarizer still lack one unified durable settlement record;
5. provider product/account/region identity is not inferred by transport shadow;
6. provider-private rate/reset header semantics are not decoded generically;
7. no rate/quota/cost enforcement;
8. no TrustDomain/cancel wiring.

These are not RG-3B failures; they define RG-3C/RG-3D entry conditions.

## 9. Final ruling

RG-3B meets its declared scope:

> **Real provider transport facts can now be observed safely and truthfully without changing provider-call behavior or giving ResourceGovernor new enforcement authority.**

Next architecture phase: **RG-3C Unified Provider-Call Settlement (shadow first)**, then RG-3D vendor/product adapters. RG-3C must not begin cloud enforcement; it should first establish one durable/idempotent accounting boundary across foreground Task, SubAgent, Learning and other provider-call users.
