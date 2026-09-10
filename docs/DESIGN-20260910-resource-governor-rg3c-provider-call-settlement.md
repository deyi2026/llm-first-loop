# RG-3C — Unified Provider-Call Settlement / Shadow-First

Status: implementation candidate under qualification
Date: 2026-09-10
Parent: RG-3B Transport Observation / Shadow (`4da2c06`)
Scope: mechanical call identity, physical transport-attempt topology, durable/idempotent accounting only

## 1. Decision

RG-3C introduces a durable, provider-agnostic settlement plane **without giving it admission, routing, fallback, retry, pricing, quota, or semantic authority**.

The core split is:

```text
ProviderCall
  = one logical model invocation owned by an execution surface

ProviderTransportAttempt
  = one actual physical transport send
```

A single ProviderCall may contain multiple physical sends:

```text
primary send
  -> internal disconnect resend
  -> ERR1210 transformed retry
  -> fallback provider/model send
```

Every physical send receives its own durable `attempt_id`. All of them may share one logical `call_id` when they are retries/fallbacks of the same model invocation.

RG-3C is shadow-first. Its facts are **not read by ResourceGovernor, routing, fallback eligibility/order, or retry policy**.

## 2. Authority boundary

Program-owned mechanical facts:

- logical call identity;
- execution owner / execution class / service priority / producer purpose;
- actual provider/model used by each physical send;
- physical-send ordering and parent attempt;
- caller-visible attempt kind and site index;
- hidden transport retry index;
- HTTP status / safe structured provider code / normalized Retry-After;
- typed provider usage that was actually reported;
- whether all physical attempts settled;
- whether a usage dimension is complete across all settled attempts;
- append-only durability and duplicate-settlement conflict detection.

Not owned by RG-3C:

- whether a task is important;
- whether a retry/fallback is semantically worthwhile;
- provider selection;
- fallback candidate order or eligibility;
- rate/quota/cost enforcement;
- pricing inference;
- trust-domain routing;
- task completion;
- Method/Skill applicability.

## 3. Identity model

### 3.1 Logical ProviderCall

`ProviderCallIdentity` contains:

```text
call_id
session_id
owner_ref
execution_class
service_priority
purpose
created_at
```

`call_id` is derived from:

```text
SHA256(session_id + mechanical idempotency key)
```

The raw idempotency key is runtime-only. Durable events contain only a non-reversible digest plus the resulting `call_id`.

Where an upstream durable identity exists, RG-3C reuses it mechanically:

```text
Task       -> session + current turn ref + round
SubAgent   -> child session + round
Learning   -> durable learning job + learning attempt
```

Where no upstream durable invocation identity exists, RG-3C does **not invent sameness**. Direct Summarizer and MemoryExtractor invocations receive fresh invocation identities. This deliberately avoids merging two independent calls that happen to have identical content/session/message counts.

This means cross-restart logical correlation is exact only where the owner already exposes a durable execution identity. Physical-send accounting remains durable regardless: an opened but unsettled send survives restart as unknown exposure rather than disappearing.

### 3.2 ProviderCallPurpose is not ExecutionClass

The Resource Governor keeps the six already-frozen execution classes. RG-3C does not add a seventh class merely to label accounting producers.

`ProviderCallPurpose` currently distinguishes:

```text
TASK
SUBAGENT
LEARNING
SUMMARIZER
MEMORY_EXTRACTOR
```

Purpose answers **who produced the model call**. ExecutionClass answers **which scheduling/service class the work belongs to**.

Examples:

```text
interactive Summarizer   -> FOREGROUND_TASK / SUMMARIZER
async Summarizer         -> BACKGROUND_LEARNING / SUMMARIZER
manual MemoryExtractor   -> FOREGROUND_TASK / MEMORY_EXTRACTOR
interval extractor       -> BACKGROUND_LEARNING / MEMORY_EXTRACTOR
Learning reflection      -> BACKGROUND_LEARNING / LEARNING
SubAgent                  -> SUBAGENT / SUBAGENT
```

In RG-3C these classes are accounting labels only for these auxiliary paths; no new admission behavior is introduced.

## 4. Physical transport attempt model

Immediately before every actual transport send, RG-3C opens a `ProviderTransportAttempt`:

```text
call_id
attempt_id
parent_attempt_id
attempt_kind
site_index
transport_retry_index
provider_id
model_id
started_at
```

### 4.1 attempt_id

Each actual send gets a fresh `pattempt:<uuid>`.

This is intentional: if a process sends a request, crashes before settlement, and later sends again, the two network sends are two distinct accounting exposures and must never collapse into one attempt.

### 4.2 parent_attempt_id

The parent is the previous actual send observed for the same logical call. It therefore forms a mechanical send lineage without inferring why a response was good/bad.

### 4.3 attempt_kind and site_index

Caller-visible categories are:

```text
PRIMARY
ERR1210_RETRY
FALLBACK
```

Task topology is currently:

```text
primary              site_index=0
ERR1210 retry        site_index=1
fallback candidate   site_index=1 + actual_1210_retry_count + fallback_send_index
```

Internal transport resend does not create a new caller-visible site. It creates another physical attempt with the same `attempt_kind/site_index` and an incremented `transport_retry_index`.

Example:

```text
call C
  A0 primary, site=0, transport_retry=0 -> ReadError
  A1 primary, site=0, transport_retry=1 -> HTTP 500
  A2 err1210_retry, site=1, transport_retry=0 -> error
  A3 fallback, site=2, transport_retry=0 -> success
```

All four are real sends and therefore all four remain visible to accounting.

## 5. Usage settlement semantics

### 5.1 Never sum streaming snapshots within one physical attempt

Some providers emit more than one usage-bearing SSE chunk. Those values may be snapshots, not deltas.

Within one physical attempt RG-3C therefore uses:

```text
for each typed usage field:
    last explicitly reported value wins
```

Missing fields do not erase previously observed fields.

It does **not** add repeated usage chunks together.

### 5.2 Across different physical attempts, known usage can be summed

Physical attempts represent distinct network sends and may each be billable. For a call snapshot RG-3C exposes:

```text
known_usage_sum[field]
usage_complete[field]
```

Example:

```text
attempt A0: input_tokens = unknown
attempt A1: input_tokens = 700

known_usage_sum.input_tokens = 700
usage_complete.input_tokens = false
```

The 700 is useful as a known lower-bound observation. It must **not** be presented as the complete call total.

Only when every settled physical attempt reports a given field may:

```text
usage_complete[field] = true
```

This distinction is a prerequisite for any later quota/cost enforcement.

### 5.3 Open/unsettled attempts

If `provider.transport.opened` exists without a matching terminal settlement, the physical send remains mechanically unresolved.

RG-3C does not assume:

- zero tokens;
- request never reached the provider;
- request was not billed;
- success or failure.

The call snapshot therefore exposes `attempts_opened`, `attempts_settled`, and `attempts_complete` separately.

## 6. Durable event model

RG-3C uses the existing EventStore as the append-only source of truth.

New events:

```text
provider.call.opened
provider.transport.opened
provider.transport.settled
provider.call.settled
```

`provider.transport.opened` is written **before** the physical send begins. This is necessary so crash-before-response cannot make a real send disappear from accounting.

`provider.transport.settled` contains only normalized safe facts:

```text
call/attempt identity
provider/model
attempt topology
outcome
normalized nullable usage
usage observation count
HTTP status if known
safe structured provider code if known
Retry-After if known
normalized typed rate-limit facts if known
exception class name if transport failed
```

It never stores:

```text
prompt/messages
response body
raw response headers
credentials/API keys
Authorization/Cookie
hidden reasoning content
raw idempotency key
```

## 7. Idempotency

### 7.1 Logical call open

Within one process/replay view, opening the same stable logical call returns the same call identity and does not intentionally create a second logical-call fact.

Identity conflicts on the same derived call ID are rejected rather than overwritten.

### 7.2 Physical settlement

`attempt_id` is the idempotency key for physical settlement.

A duplicate terminal settlement with identical normalized facts returns the existing settlement. A conflicting duplicate raises an accounting conflict and never overwrites the first durable fact.

### 7.3 Cross-process duplicate call-open events

EventStore is append-only and does not currently provide compare-and-swap conditional append. Two processes could therefore append duplicate identical `provider.call.opened` facts for the same call ID.

The reducer collapses them by call ID; physical attempt IDs remain unique per actual send, so usage accounting does not collapse two physical sends.

Adding a generalized EventStore conditional-append primitive is outside RG-3C and is not required for cloud enforcement because enforcement is still disabled.

## 8. Producer coverage

RG-3C candidate wiring covers:

### Task Plane
- primary provider send;
- internal transport resend;
- ERR1210 transformed retry;
- fallback provider/model candidates;
- logical success/error/interruption/blocked-before-transport.

### SubAgent
- each child model round has its own logical call;
- existing SUBAGENT / P1 resource lease remains unchanged.

### Learning Plane
- each durable learning job attempt has its own logical call;
- existing BACKGROUND_LEARNING / P3 resource admission remains unchanged;
- a reflection that exits before model transport is recorded as blocked-before-transport rather than fabricating usage.

### Summarizer
- synchronous path is accounted as foreground purpose=SUMMARIZER;
- asynchronous worker/backfill captures source session identity before thread handoff and uses background accounting labels;
- no new ResourceGovernor admission is introduced by RG-3C.

### MemoryExtractor
- manual invocation is accounted as foreground purpose=MEMORY_EXTRACTOR;
- interval invocation uses background accounting labels;
- each invocation is a distinct logical call unless a future upstream durable extractor-job identity is introduced.

## 9. Legacy request events remain separate

Existing events remain valid:

```text
request.meta
request.attempt
request.usage
```

Their role is not replaced in RG-3C.

- `request.meta` / `request.attempt` remain request/runtime diagnostics and now may carry `provider_call_id` for correlation.
- `request.usage` remains existing task/UI/runtime usage telemetry.
- `provider.transport.*` is the new physical-send durable accounting source.

RG-3C must not derive billing truth by adding legacy `request.usage` to transport settlements; that would double-count the same response.

## 10. Shadow-only invariant

RG-3C code must satisfy:

```text
settlement facts
    -> observation / audit / qualification only

NOT:
settlement facts
    -> ResourceGovernor admission
    -> provider selection
    -> fallback eligibility/order
    -> retry count/policy
    -> request mutation
```

No cloud rate, quota, or cost rejection is enabled here.

## 11. Qualification requirements

RG-3C may close only if all are true:

1. stable logical call ID where a real durable upstream identity exists;
2. independent invocation IDs where sameness cannot be proven;
3. each actual physical transport send receives a unique attempt ID;
4. internal disconnect resend is visible as a second physical attempt;
5. primary / ERR1210 retry / fallback can share one logical lineage;
6. physical parent topology is preserved in durable EventStore;
7. multiple usage chunks inside one send are not summed as deltas;
8. usage totals expose completeness separately from known sums;
9. open-but-unsettled sends survive restart as unknown exposure;
10. duplicate settlement is idempotent; conflicts do not overwrite;
11. EventStore rehydration reconstructs the same accounting view;
12. Task/SubAgent/Learning/Summarizer/MemoryExtractor reach the shared journal;
13. no raw prompt/body/header/credential is durable;
14. no settlement fact is consumed by Governor/routing/fallback;
15. prompt and provider tool surfaces remain byte-identical to RG-3B parent;
16. existing fallback/retry behavior remains unchanged;
17. focused + full non-real-LLM regression passes;
18. committed tiny live canary for DeepSeek / GLM / MiniMax shows one logical call with real physical-attempt settlement each, without deliberate 429 induction.

## 12. Explicitly deferred

RG-3C does not implement:

- RPM/TPM admission;
- quota enforcement;
- pricing or cost aggregation authority;
- cost budget rejection;
- trust-domain policy;
- provider control-plane polling;
- cancellation/preemption capability;
- vendor-specific ambiguous reset-header adapters;
- semantic retry/fallback ranking;
- generic durable job identity for every auxiliary component.

Those require later phases after settlement quality is proven.

## 13. Next dependency

The architectural dependency after RG-3C is **not automatically “turn on cloud enforcement.”**

The next step should first qualify an authoritative facts/ledger projection suitable for admission calculations, including:

```text
which usage dimensions are complete
how rolling windows are keyed
how Retry-After/reset facts expire
how provider/account/project/model scopes map
how pricing/quota facts are sourced and versioned
```

Only after those mechanical facts are independently qualified may a later phase consume them for shadow admission simulations and, eventually, enforcement.
