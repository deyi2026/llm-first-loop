# RG-3C Qualification — Unified Provider-Call Settlement / Shadow-First

Date: 2026-09-10
Verdict: **PASS / CLOSE**

Implementation commit under qualification:

```text
4ae9255 feat(resources): settle RG-3C provider calls
```

Parent qualified baseline:

```text
4da2c06 docs(resources): record RG-3B qualification
```

## 1. Qualified scope

RG-3C qualifies only:

```text
logical provider-call identity
physical transport-attempt identity
retry/fallback attempt lineage
durable EventStore settlement
idempotent attempt accounting
completeness-aware typed usage aggregation
Task/SubAgent/Learning/Summarizer/MemoryExtractor accounting convergence
```

It does **not** qualify or enable:

```text
cloud rate enforcement
quota enforcement
cost enforcement
provider selection changes
fallback ranking/eligibility changes
retry policy changes
TrustDomain policy
cancel/preemption
vendor-specific ambiguous reset adapters
```

Settlement remains shadow-only.

## 2. Identity result

Qualified split:

```text
ProviderCall
  = one logical model invocation

ProviderTransportAttempt
  = one actual physical transport send
```

Every real physical send receives its own `attempt_id`, including an internal transport resend hidden below the caller-visible retry/fallback layer.

Where a durable upstream identity already exists, logical call identity is derived mechanically from it:

```text
Task       -> session + turn ref + round
SubAgent   -> child session + round
Learning   -> durable learning job + attempt
```

Where such sameness cannot be proven, auxiliary invocations receive a fresh call identity rather than being merged by content or coarse session counters. A regression specifically proves two manual MemoryExtractor invocations over the same session snapshot do not share a call ID.

Raw idempotency keys are not written into durable events.

## 3. Attempt topology result

Qualified caller-visible attempt kinds:

```text
primary
err1210_retry
fallback
```

Physical lineage fields:

```text
call_id
attempt_id
parent_attempt_id
attempt_kind
site_index
transport_retry_index
provider_id
model_id
```

Deterministic tests prove:

```text
primary site 0
  -> ERR1210 retry site 1
  -> fallback site 2
```

share one logical `call_id`, while each physical send has a distinct `attempt_id` and each parent points to the immediately preceding actual send.

An actual `httpx.ReadError` disconnect test also proves LLMClient's internal resend becomes:

```text
attempt A0 primary/site0/transport_retry0 -> error
attempt A1 primary/site0/transport_retry1 -> success
```

rather than disappearing behind the final response.

## 4. Durable accounting result

New EventStore facts:

```text
provider.call.opened
provider.transport.opened
provider.transport.settled
provider.call.settled
```

`provider.transport.opened` is appended before the network send. An opened-but-unsettled attempt therefore survives a crash as unresolved exposure instead of being silently treated as zero.

Terminal physical settlement is idempotent by `attempt_id`:

- identical duplicate settlement reuses the first fact;
- conflicting duplicate settlement is rejected and cannot overwrite the first fact.

A fresh `ProviderCallSettlementJournal` rebuilt over the same EventStore reproduces call topology, typed usage, completeness, and terminal outcome.

## 5. Usage semantics result

Within one physical send, multiple usage-bearing stream chunks are treated as snapshots:

```text
last explicitly reported value per typed field wins
```

They are not summed as deltas.

Across distinct physical sends, RG-3C exposes both:

```text
known_usage_sum[field]
usage_complete[field]
```

Therefore:

```text
attempt A0 input_tokens = unknown
attempt A1 input_tokens = 700
```

produces:

```text
known_usage_sum.input_tokens = 700
usage_complete.input_tokens = false
```

The known partial value cannot masquerade as a complete total. This is required before any future quota/cost authority can be considered.

Legacy `request.usage` remains separate telemetry and is not added to physical transport settlement, preventing double counting.

## 6. Producer convergence result

Direct settlement evidence covers:

```text
Task-style provider call
SubAgent
Learning
Summarizer
MemoryExtractor
```

Producer identity is represented by `ProviderCallPurpose`; this does not add a new Resource Governor execution class.

Qualified examples:

```text
SubAgent  -> SUBAGENT / P1 / purpose=subagent
Learning  -> BACKGROUND_LEARNING / P3 / purpose=learning
sync Summarizer -> FOREGROUND_TASK / P0 / purpose=summarizer
manual MemoryExtractor -> FOREGROUND_TASK / P0 / purpose=memory_extractor
```

Background Summarizer/Extractor reuse the existing background scheduling class only as an accounting label in RG-3C. RG-3C does not introduce new admission for those components.

## 7. Privacy / trust boundary result

Durable provider settlement contains only normalized mechanical facts.

Explicitly excluded:

```text
prompt/messages
assistant answer body
response body
raw response headers
credentials/API keys
Authorization/Cookie
hidden reasoning content
raw idempotency key
```

Staged security scan passed for the implementation candidate; committed tree security scan also passed.

## 8. Shadow authority result

Static consumer audit found no settlement accounting consumer in:

```text
ResourceGovernor
model routing
fallback eligibility/order
ModelClientPool routing
```

RG-3C therefore observes and settles but does not steer requests.

No rate/quota/cost rejection was enabled.

## 9. Prompt / tool surface identity

RG-3B parent `4da2c06` and RG-3C candidate were built independently using the same isolated Settings and compared with the same serialization.

Registered provider tool surface:

```text
parent    62 tools / 21730 bytes / SHA 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
candidate 62 tools / 21730 bytes / SHA 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
identical true
```

Runtime-health projected provider tool surface:

```text
parent    60 tools / 21118 bytes / SHA 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c
candidate 60 tools / 21118 bytes / SHA 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c
identical true
```

Universal Prompt source:

```text
parent    SHA 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
candidate SHA 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
byte-identical true
```

Thus RG-3C did not buy accounting observability by adding prompt/tool tax.

## 10. Deterministic and regression qualification

RG-3C settlement-specific test file:

```text
tests/unit/test_provider_call_settlement.py
12 / 12 PASS
```

It covers:

- stable logical call IDs when upstream identity is stable;
- raw idempotency key not durable;
- multi-chunk usage snapshot merge;
- known sum vs completeness;
- physical settlement idempotency/conflict rejection;
- actual internal disconnect resend topology;
- EventStore rehydration;
- Summarizer purpose/accounting;
- MemoryExtractor purpose/accounting;
- distinct manual extractor invocations;
- SubAgent purpose/class accounting;
- Learning purpose/class accounting;
- primary -> ERR1210 retry -> fallback shared lineage.

Broad RG-3C suite includes Resource Governor, RG-3B transport, fallback, runtime causality, LLM client, SubAgent, Learning, Summarizer, MemoryExtractor, EventStore model/replay/stream and passed 100%.

Static/architecture gates:

```text
git diff/check           PASS
git show --check         PASS
staged security          PASS
committed tree security  PASS (1500 tracked files)
Ruff src/tests           PASS
Pyright                  0 errors / 0 warnings / 0 informations
arch guards              PASS
changed-runtime py_compile PASS
```

Full non-real-LLM regression:

```text
pre-commit staged candidate  100% / exit 0
clean committed 4ae9255      100% / exit 0
```

## 11. Real cloud canary

Committed `4ae9255` was exercised against the currently configured default models, sequentially, one tiny call per provider.

No deliberate 429/rate-limit failure was induced.

### DeepSeek

```text
model             deepseek-flash
logical calls      1
physical attempts  1 opened / 1 settled
attempt complete   true
call outcome       success
HTTP status        200
Retry-After        unknown / not reported
usage              input=34 output=13 cached=0 reasoning=11 total=47
usage completeness all five token dimensions = true
EventStore replay  equal to live reducer
```

### GLM

```text
model             glm-5.3
logical calls      1
physical attempts  1 opened / 1 settled
attempt complete   true
call outcome       success
HTTP status        200
Retry-After        unknown / not reported
usage              input=16 output=13 cached=0 reasoning=10 total=29
usage completeness all five token dimensions = true
EventStore replay  equal to live reducer
```

### MiniMax

```text
model             MiniMax-M3
logical calls      1
physical attempts  1 opened / 1 settled
attempt complete   true
call outcome       success
HTTP status        200
Retry-After        unknown / not reported
usage              input=180 output=19 cached=128 reasoning=15 total=199
usage completeness all five token dimensions = true
EventStore replay  equal to live reducer
```

The live qualification printed only typed settlement facts. Prompt text, answer text, raw headers, response bodies, and credentials were not emitted into qualification output.

An initial canary preflight resolved the isolated worktree's empty default data directory and stopped before constructing the first configured provider client. No provider request was sent in that failed preflight. The successful qualification explicitly used the operator repository's provider registry as read-only configuration while keeping the settlement EventStore in a temporary directory.

## 12. Known limitations retained deliberately

RG-3C closes the settlement substrate, not cloud enforcement.

Still deferred:

- generic durable upstream job identity for every auxiliary component;
- atomic compare-and-swap EventStore append for cross-process duplicate call-open suppression;
- provider-unit aggregation across attempts;
- vendor-specific ambiguous reset header interpretation;
- RPM/TPM rolling windows;
- account/project/model quota mapping;
- pricing/cost calculation authority;
- TrustDomain enforcement;
- cancellation/preemption capability.

For cross-process duplicate logical call-open events, the reducer deduplicates by call ID while physical attempt IDs remain unique. This preserves physical-send accounting; it is not presented as an atomic distributed call-open lock.

## 13. Final ruling

**RG-3C Unified Provider-Call Settlement / Shadow-First = PASS / CLOSE.**

The system now has a durable mechanical answer to:

```text
Which logical model invocation was this?
How many actual provider sends occurred?
Which send was a retry/fallback of which earlier send?
What typed usage was actually reported for each physical send?
Which aggregate dimensions are complete versus only partially known?
Can the same accounting view be reconstructed after restart?
```

It still does not answer or decide:

```text
Should this request be admitted?
Which provider should be selected?
Should fallback happen?
Is a task worth spending more resources on?
```

Those remain outside RG-3C authority.
