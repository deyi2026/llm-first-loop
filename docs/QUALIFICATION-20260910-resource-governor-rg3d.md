# QUALIFICATION-20260910: Resource Governor RG-3D Global Ledger Projection / Shadow Admission Facts

> Final ruling: **PASS / CLOSE**
>
> Qualified implementation: `30c379594368c534ad5ca3bb37b56ad09b7baf17`
>
> Qualified parent: `12f28f1014793cf74ba778f20f466fc362eda9d7`
>
> Branch: `feature/resource-governor-rg3d-ledger-projection-20260910`
>
> Date: 2026-09-10

## 1. Qualification question

RG-3D is qualified only for the following claim:

> LFL can maintain a rebuildable, cross-session projection of RG-3C provider-call
> settlement facts, bind those observations to explicit resource scopes and exact
> accounting windows, preserve completeness/freshness/coverage uncertainty, and
> expose shadow admission facts without changing provider selection, retry/fallback,
> user-visible prompt/tool surfaces, or Resource Governor enforcement.

RG-3D is **not** qualification for cloud rate/quota/cost enforcement.

It is also not qualification for any provider-specific account/product/plan mapping.

---

## 2. Parent state and implementation boundary

RG-3D starts from qualified RG-3C:

```text
12f28f1  docs(resources): record RG-3C qualification
4ae9255  feat(resources): settle RG-3C provider calls
```

RG-3D implementation is one independent commit:

```text
30c3795  feat(resources): project RG-3D settlement ledger
```

Diff against qualified parent:

```text
8 files changed, 2488 insertions(+), 4 deletions(-)
```

Files:

```text
M docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md
A docs/DESIGN-20260910-resource-governor-rg3d-ledger-projection.md
M src/llm_loop/core/loop/engine.py
M src/llm_loop/factory.py
M src/llm_loop/resources/__init__.py
A src/llm_loop/resources/ledger_projection.py
M src/llm_loop/resources/provider_settlement.py
A tests/unit/test_resource_ledger_projection.py
```

No RG-3D implementation change was mixed into the later qualification-document commit.

---

## 3. Architecture ruling

The decisive boundary is:

```text
per-call complete != account/window complete
```

RG-3C can prove whether one logical call and its physical transport attempts were
settled completely. It cannot prove that all calls for an account/project/product
inside a provider billing/rate window are present.

RG-3D therefore adds a derived global projection instead of promoting
`ProviderCallSettlementJournal.snapshot_call()` into an account ledger.

Data flow:

```text
provider transport
      |
      v
RG-3C EventStore settlement  <-- durable source of truth
      |
      +--> fail-open RG-3D projection sink
                 |
                 v
       rebuildable SQLite projection
                 |
                 v
       shadow mechanical facts only
```

The SQLite database is not a second source of truth. It may be deleted and rebuilt
from EventStore.

---

## 4. Qualified contracts

### 4.1 Exact accounting window

RG-3D freezes half-open windows:

```text
[start_at, end_at)
```

An attempt whose `started_at == start_at` is included; one whose
`started_at == end_at` is excluded.

The generic layer does not guess rolling-window semantics, provider reset timezone,
billing-cycle boundaries, or opaque reset units.

### 4.2 Explicit resource binding

`ProviderResourceBinding` binds:

```text
provider_id
model_id
resource_keys[]
product?              # only when explicitly known
provenance
validity
```

The generic layer does not infer account/product/project from:

```text
base URL
provider name
API credential contents
model family
historical pricing assumptions
```

### 4.3 Fact validity and freshness

Qualified states:

```text
validity kind:
  immutable_event
  open_ended
  bounded
  unknown

freshness:
  current
  expired
  not_yet_valid
  unknown
```

Unknown validity never means “valid forever.”

### 4.4 Source-set coverage vs provider-global coverage

These are independent facts.

Layer A:

```text
explicit LFL source-set coverage
```

Layer B:

```text
provider/account global coverage
```

An explicit LFL source set can be complete while provider-global coverage remains
unknown.

Provider-global `complete` or `partial` can only be represented with explicit
provenance plus non-unknown validity/version. A stale proof is surfaced as
`provider_global_coverage_not_current`.

### 4.5 Source coverage high-watermark

Known source-set coverage is bound to exact per-session EventStore watermarks:

```text
SourceSessionWatermark {
  session_id
  last_seq
  event_count
  skipped_lines
}
```

`ProjectionCoverage` mechanically recomputes and verifies:

```text
source_scope_ref
source_watermark_ref
```

from the supplied watermark tuple. A tampered reference is rejected.

Therefore:

> `source_set=complete` means complete through the captured EventStore high-watermark,
> not permanently complete after future events may be appended.

### 4.6 Shadow admission facts

`ShadowAdmissionFacts` exposes only:

```text
requirement
binding_freshness
coverage
aggregate?
gaps[]
```

It has no field equivalent to:

```text
admit
reject
defer
should_run
route_to
fallback_to
```

---

## 5. Projection implementation facts

`ProviderSettlementProjectionIndex` indexes all four RG-3C durable event classes:

```text
provider.call.opened
provider.call.settled
provider.transport.opened
provider.transport.settled
```

The projection stores logical call attribution and physical attempt identity,
lineage, actual provider/model target, typed nullable usage, normalized status/error
facts, and timestamps.

It does not store prompt/message/task payloads.

### 5.1 Open and settle are separate facts

A row existing in SQLite is not enough to call an attempt complete.

Qualified rule:

```text
attempt_complete
  iff durable transport.opened exists
  and durable transport.settled exists
```

A settled-only orphan may contribute a known usage lower bound, but it keeps:

```text
attempts_complete = false
usage_complete[field] = false
```

until its durable open fact is recovered.

### 5.2 Cross-session aggregation

Qualified aggregation spans provider-call producers such as:

```text
Task
SubAgent
Learning
Summarizer
MemoryExtractor
```

while preserving `execution_class_counts` and `purpose_counts` as mechanical
attribution only.

### 5.3 Cross-provider fallback attribution

A logical topology may be:

```text
primary  -> provider A / model X
retry    -> provider A / model X
fallback -> provider B / model Y
```

RG-3D accounts each physical attempt under its actual RG-3C transport provider/model,
not under the logical call's first target.

### 5.4 Known usage vs complete usage

For every typed token field:

```text
known_usage_sum[field]
usage_complete[field]
```

remain separate.

Unknown provider usage is never silently converted into zero.

### 5.5 Generic request counting deliberately absent

The generic projection does **not** produce a provider “requests consumed” value.

One physical HTTP send is not universally proven to equal one RPM/quota/billable
request across providers/products, especially for disconnects, 429, 5xx, streaming
interruptions, or provider-side retry behavior.

That mapping is deferred to authoritative provider/product adapters.

---

## 6. Durability and idempotency

The RG-3D SQLite projection is derived state.

Qualified behavior:

```text
same EventStore event replay   -> duplicate, no double accounting
same identity + same fact      -> duplicate
same call/attempt identity
  with conflicting topology    -> conflict, original fact not overwritten
projection sink failure        -> EventStore and provider call unaffected
historical rebuild             -> explicit reconcile only
startup                         -> no unbounded history scan
```

Factory constructs the projection handle lazily. Merely building an engine does not
create the SQLite file or scan all historical sessions.

Historical projection is explicit:

```text
reconcile_event_store(event_store, explicit_session_ids)
```

The reconcile result names the explicit source set and its high-watermark.

---

## 7. Privacy and authority audit

### 7.1 SQLite privacy boundary

The projection schema has no columns for:

```text
prompt
messages
raw response body
raw headers
Authorization
Cookie
API key
tool arguments
task text
hidden reasoning
```

Only RG-3B/RG-3C normalized mechanical facts are projected.

### 7.2 No vendor-specific policy in generic projection

The generic module contains no GLM/MiniMax/DeepSeek-specific branch or static plan
constant.

### 7.3 No enforcement consumer

Read-only source audit confirmed the RG-3D projection is not consumed by:

```text
ResourceGovernor
provider-call admission helpers
fallback service
1210 recovery service
```

No routing, retry, fallback, or admission behavior changed.

---

## 8. Deterministic qualification

### 8.1 Focused tests

Final focused group after high-watermark/tamper strengthening:

```text
50 / 50 PASS
```

Covered:

- validity current/expired/not-yet-valid/unknown;
- exact half-open window;
- explicit binding provider consistency;
- projection idempotency and EventStore rebuild;
- cross-session aggregation;
- execution-class/purpose attribution;
- actual-target cross-provider fallback accounting;
- opened/unsettled exposure;
- settled-only orphan incompleteness;
- nullable usage lower-bound semantics;
- identity conflict no-overwrite;
- source-set coverage distinct from provider-global coverage;
- corrupt EventStore line degrades source coverage to partial;
- provider-global proof requires provenance + validity;
- stale provider-global proof produces not-current gap;
- exact source-set high-watermark;
- source/watermark digest tamper rejection;
- projection sink fail-open;
- Factory no startup history scan;
- generic projection does not invent request quota/RPM;
- no sensitive SQLite columns;
- no vendor hardcode;
- no Governor/provider-calls/fallback projection consumer.

### 8.2 Broad adjacent regression

Final broad + architecture suite after high-watermark strengthening:

```text
290 / 290 PASS
```

Coverage included RG-3A/RG-3B/RG-3C/RG-3D contracts and runtime, EventStore
model/replay/stream, Factory, fallback, Learning, Summarizer, MemoryExtractor, and
SubAgent topology/delivery/restart/settlement.

---

## 9. Static and committed-state gates

Final staged candidate:

```text
git diff --cached --check       PASS
staged security scan            PASS (8 files)
Ruff src + tests                PASS
Pyright                         0 errors / 0 warnings / 0 informations
architecture guards             PASS
changed-runtime py_compile      PASS
```

Clean committed implementation `30c3795`:

```text
git show --check                PASS
tracked-tree security scan      PASS (1504 files)
Ruff src + tests                PASS
Pyright                         0 errors / 0 warnings / 0 informations
focused+broad+arch              PASS
changed-runtime py_compile      PASS
```

No gate was bypassed with ignore/skip to obtain green status.

---

## 10. Prompt/tool surface identity

Final RG-3D candidate was compared against a detached RG-3C qualified parent
`12f28f1` using independent empty data directories and identical Settings.

### Registered tool schemas

```text
parent    count=62  bytes=21730
candidate count=62  bytes=21730
SHA256 = 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
```

### Projected schemas

```text
parent    count=60  bytes=21118
candidate count=60  bytes=21118
SHA256 = 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c
```

### Actual provider `tools` array

```text
parent    count=60  bytes=22978
candidate count=60  bytes=22978
SHA256 = d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
```

### Universal Prompt source

```text
parent SHA256    = 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
candidate SHA256 = 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
```

Result:

```text
SURFACE_IDENTITY_FINAL = PASS
```

RG-3D adds zero prompt/tool surface tax.

---

## 11. Full non-real-LLM regression

Project pytest configuration already fixes:

```text
-q --import-mode=importlib -m "not real_llm"
```

so qualification records the observed progress terminal and process exit rather than
inventing a passed-item count not emitted by the configured quiet reporter.

Final staged high-watermark candidate:

```text
[100%]
process exit = 0
elapsed ~= 224.7 s
```

Clean committed `30c3795`:

```text
[100%]
process exit = 0
elapsed ~= 226.6 s
```

A previous pre-high-watermark run was explicitly not reused as final evidence.

An earlier qualification invocation also reached `[100%]` but was terminated by an
outer command timeout before pytest returned its exit code; it was correctly not
counted as PASS and was rerun with a wider outer timeout.

---

## 12. Local projection overhead probe

Pure local mechanical microbenchmark, no provider/model request:

```text
20 logical calls:
  RG-3C baseline       ~0.554 ms/call
  + RG-3D projection   ~1.397 ms/call
  incremental          ~0.843 ms/call

100 logical calls:
  RG-3C baseline       ~0.471 ms/call
  + RG-3D projection   ~1.391 ms/call
  incremental          ~0.921 ms/call
```

Each logical call included the four RG-3C settlement events.

This is enough to reject an unnecessary second async queue/state machine at RG-3D,
but it is not treated as a universal production latency guarantee.

---

## 13. Real cloud projection canary

### 13.1 Safety/operation boundary

The canary used the existing operator provider registry read-only and loaded existing
credentials through the repository's standard environment-file loader into one
short-lived process.

It did not print or persist credential values.

Each provider used temporary data/EventStore/SQLite state, ran sequentially, and no
429 was intentionally generated.

The canary output contained only typed mechanical settlement/projection facts. It did
not print prompt text, answer text, raw headers, response body, or credentials.

There is no authoritative account/product binding in the current provider registry,
so the expected cloud resource result was:

```text
provider_global_coverage = unknown
account resource scope    = unbound
```

No account/product identity was inferred from URL, provider name, or credential.

### 13.2 DeepSeek

```text
provider/model            deepseek / deepseek-flash
HTTP                       200
logical outcome             success
physical attempts           1 opened / 1 settled / complete
input_tokens                34
output_tokens               13
reasoning_tokens            11
cached_input_tokens         0
total_tokens                47
EventStore -> projection    exact attempt match
EventStore -> projection    exact known-usage match
source-set coverage         complete through watermark
provider-global coverage    unknown
account scope               unbound
```

### 13.3 MiniMax

```text
provider/model            minimax / MiniMax-M3
HTTP                       200
logical outcome             success
physical attempts           1 opened / 1 settled / complete
input_tokens                180
output_tokens               32
reasoning_tokens            28
cached_input_tokens         128
total_tokens                212
EventStore -> projection    exact attempt match
EventStore -> projection    exact known-usage match
source-set coverage         complete through watermark
provider-global coverage    unknown
account scope               unbound
```

### 13.4 GLM qualification note and rerun

The first GLM canary deliberately shared the same very small `max_tokens=64` cap used
for the tiny probe. Transport itself returned HTTP 200 and RG-3D projection matched
EventStore exactly:

```text
input_tokens      16
output_tokens     64
reasoning_tokens  61
total_tokens      80
```

Because almost the entire output allowance was consumed by reasoning, the final
visible body was empty and the higher-level LLM client reported
`LLMEmptyResponseError`.

This was not hidden or reclassified as a provider-call success. It was also not a
transport/projection mismatch.

To remove the output-budget ambiguity, **only GLM** was rerun with a canary output
allowance of 256 tokens. DeepSeek and MiniMax were not repeated.

Final GLM qualification:

```text
provider/model            glm / glm-5.3
HTTP                       200
logical outcome             success
physical attempts           1 opened / 1 settled / complete
input_tokens                16
output_tokens               61
reasoning_tokens            58
cached_input_tokens         0
total_tokens                77
EventStore -> projection    exact attempt match
EventStore -> projection    exact known-usage match
source-set coverage         complete through watermark
provider-global coverage    unknown
account scope               unbound
```

### 13.5 Real-canary ruling

Final provider result:

```text
DeepSeek    PASS
GLM         PASS
MiniMax     PASS
----------------
3 / 3       PASS
```

The canary proves RG-3D's stated scope only: real transport settlement facts can be
projected exactly while resource identity/completeness uncertainty remains honest.

It does **not** prove account quota, RPM/TPM, price, or billing truth.

---

## 14. Negative authority qualification

The following behavior was specifically not introduced:

```text
cloud concurrency/rate/quota/cost enforcement
provider/model selection policy
retry/fallback policy changes
semantic task-value scoring
provider-specific quota inference
automatic account/product inference
pricing calculation
billing-period inference
TrustDomain policy
provider cancellation/preemption
startup full-history rebuild
```

The Resource Governor does not consume RG-3D shadow projection facts in this phase.

---

## 15. Remaining limitations / deferred work

RG-3D closes with these limitations intentionally visible:

1. No authoritative GLM/MiniMax/DeepSeek account/product/project bindings yet.
2. Provider-global coverage remains unknown unless a later authoritative source proves it.
3. Source-set `complete` is only complete through its exact captured EventStore watermark.
4. A later event append makes an old watermark historical; callers needing currentness must refresh it.
5. Projection sink failure can make SQLite temporarily lag EventStore; explicit reconcile repairs derived state.
6. Generic RG-3D does not infer RPM/request-quota consumption from physical sends.
7. No provider-specific reset-window semantics beyond already normalized RG-3B typed facts.
8. No pricing schedule resolution or cost calculation.
9. No rate/quota/cost admission enforcement.
10. No account-wide usage reconciliation with provider control plane yet.
11. No cross-provider currency conversion.
12. No TrustDomain data-egress policy in this phase.
13. No provider cancellation/preemption integration.
14. No automatic all-history projection scan on startup.
15. Local projection microbenchmark is not a production SLA.

These are RG-3E/RG-3F/RG-3G entry conditions, not RG-3D qualification failures.

---

## 16. Final ruling

RG-3D satisfies the frozen phase contract:

```text
EventStore remains durable SoT                         PASS
SQLite projection is rebuildable + idempotent         PASS
projection failure is fail-open                        PASS
four provider settlement events are represented        PASS
open/settle completeness is not fabricated             PASS
cross-session aggregation works                        PASS
cross-provider fallback uses actual target             PASS
known usage != complete usage                          PASS
explicit binding only                                  PASS
exact accounting windows                               PASS
validity/freshness/version explicit                    PASS
source-set != provider-global coverage                 PASS
source-set complete bound to exact high-watermark      PASS
known provider-global proof requires provenance        PASS
generic request/RPM consumption not invented           PASS
shadow object has no admission decision                PASS
no enforcement consumer                                PASS
no prompt/tool surface change                          PASS
privacy/security gates                                 PASS
focused + broad regression                             PASS
staged full non-real-LLM                               PASS
committed full non-real-LLM                            PASS
real DeepSeek/GLM/MiniMax projection canary            PASS
```

Therefore:

> **RG-3D Global Ledger Projection / Shadow Admission Facts = PASS / CLOSE.**

---

## 17. Next architecture phase

Recommended next phase:

> **RG-3E Authoritative Vendor/Product Adapters — contract/observation first.**

RG-3E should translate verified provider/product facts into the already frozen generic
contracts, including where available:

```text
explicit provider product/account/project identity
rate/quota metric semantics
request-counting semantics
reset/window semantics
provider control-plane usage snapshots
pricing schedule identity/version
billing-cycle identity
provider-global coverage provenance
```

Adapter authority remains narrow:

```text
authoritative external/provider fact
    -> typed LFL mechanical fact
```

It must not own model selection, task value, retry/fallback strategy, Method
applicability, or completion judgment.

Even after RG-3E, cloud enforcement should remain off until **RG-3F Shadow Admission
Qualification** demonstrates that resource facts, windows, coverage, and accounting
are sufficiently complete and current for limited enforcement.
