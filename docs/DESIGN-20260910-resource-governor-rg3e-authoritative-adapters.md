# DESIGN-20260910: Resource Governor RG-3E Authoritative Vendor/Product Adapters

> Status: **E0-E2 PASS; E3 not qualified (explicit product binding absent); overall HOLD / not fully closed**
> Base: `integration/rg3-unified-20260910@9d09a09`
> Branch: `feature/resource-governor-rg3e-authoritative-adapters-20260910`
> Prerequisite: RG-3D Global Ledger Projection / Shadow Admission Facts = PASS/CLOSE.

## 0. Ruling

RG-3E does one job:

```text
authoritative external/provider fact
        -> explicit resource/product scope
        -> versioned/freshness-aware typed RG fact
```

It does **not** decide whether a task is worth the resource, which model should run,
which fallback is better, or whether a provider call should be admitted.

RG-3E remains observation-only. The new facts are not consumed by:

```text
ResourceGovernor
ProviderCallCoordinator
fallback/recovery
Task Plane
SubAgent
Learning Plane
```

Cloud admission simulation is RG-3F. Limited enforcement is RG-3G and is forbidden
until RG-3F independently qualifies the relevant facts.

---

## 1. Why RG-3E needs an authority layer

RG-3D proved that LFL can reconstruct its own provider-call settlement across
Sessions, but deliberately leaves provider-global coverage unknown. That is correct:
LFL's EventStore cannot prove what happened outside LFL, what account/product a key
belongs to, or what the provider currently grants to that account.

Three different statements must therefore remain different:

1. **Published default**: what the provider currently publishes for a model/product.
2. **Explicit product binding**: which non-secret product/account/project aliases the
   operator says this LFL provider target belongs to.
3. **Exact live provider fact**: what an authoritative provider response/control plane
   says about that exact bound scope now.

A published default must never silently upgrade into exact account truth.

---

## 2. Provider documentation is authoritative about publication, not necessarily the account

An official documentation page is strong evidence for:

```text
"the provider published X at this captured version/time"
```

It is not automatically evidence for:

```text
"this exact account currently has X"
```

Reasons include:

- account-specific capacity expansion;
- plan/tier-specific quotas;
- dedicated subscription keys/endpoints;
- team/project entitlements;
- dynamic peak-hour limits;
- prices changing after the page snapshot;
- model aliases that differ between the local registry and current provider docs.

RG-3E therefore has two disjoint envelope types:

```text
ProviderPublishedResourceProfile
ProviderAuthoritativeSnapshot
```

`ProviderPublishedResourceProfile` intentionally has **no ResourceKey**. It cannot be
mistaken for a bound account/project resource.

---

## 3. First-class PRODUCT scope

RG-0 originally had:

```text
runtime / provider / account / project / model
```

Real provider products add an independently consumed scope:

```text
product
```

Examples include a subscription/Token Plan whose quota is shared across multiple
models. Encoding such a quota as MODEL would split one shared budget; encoding it as
ACCOUNT could incorrectly merge other pay-as-you-go resources.

RG-3E therefore adds:

```text
ResourceScopeKind.PRODUCT
```

The scope id is a non-secret operator alias, never a raw API key, account number, or
URL-derived guess.

---

## 4. Routing configuration is not resource identity

`data/providers.json` answers routing questions such as:

```text
provider id
base URL
credential environment-variable name
model catalog
wire protocol
context/output settings
```

It does not currently contain an authoritative product/account resource binding.
RG-3E must not reinterpret those fields as such a binding.

Forbidden inference examples:

```text
base_url contains /coding/ -> therefore Coding Plan
key env is MINIMAX_API_KEY -> therefore paygo
provider_id == deepseek -> therefore default concurrency applies to this account
model alias deepseek-flash -> therefore deepseek-v4-flash pricing
```

Even when one inference often happens to be correct, it remains an unproven identity
bridge and is not suitable for resource accounting/enforcement.

---

## 5. Explicit operator resource binding

RG-3E introduces a closed non-secret binding object, separate from provider routing.
It requires:

```text
provider_id
product_id
account_alias
model_ids[]                  # exact strings, no alias expansion
scopes.product              # explicit PRODUCT scope alias
scopes.account              # explicit ACCOUNT scope alias
project_alias? + scopes.project?
api_family?
region?
source_ref
version_ref
```

It explicitly rejects routing/credential fields including:

```text
api_key
api_key_env
token
secret
authorization
base_url
endpoint
```

The parser performs no file or network I/O. It only materializes:

```text
ResourceProductIdentity
ResourceKey(PRODUCT/ACCOUNT/PROJECT)
ProviderResourceBinding per exact model id
```

with `OPERATOR_CONFIG` provenance and versioned open-ended validity.

A future loader may persist such a manifest, but RG-3E does not add a Factory/runtime
loader before the contract is qualified.

---

## 6. Fact applicability

RG-3E uses a closed applicability vocabulary:

```text
published_default
exact_product
exact_account
exact_project
```

Rules:

- `published_default` uses `ProviderPublishedResourceProfile` and carries no ResourceKey;
- `exact_product` requires a PRODUCT key;
- `exact_account` requires an ACCOUNT key;
- `exact_project` requires a PROJECT key and explicit project alias;
- exact account/project facts require live provider provenance (`PROVIDER_CONTROL_PLANE`
  or `PROVIDER_RESPONSE`), not provider documentation alone;
- every exact snapshot requires non-unknown validity/version facts.

---

## 7. Published facts

`ProviderPublishedResourceProfile` can preserve exact published facts such as:

```text
provider/model/product label
published account-level default concurrency
exact published rate limit (only if semantics are explicit)
exact published quota (only if the unit/window/value are exact)
pricing rules
whether account override is explicitly documented as possible
```

It must not normalize approximate provider marketing guidance into an exact hard limit.

For example:

```text
"run approximately 3-4 agents"
"up to about 80 prompts"
```

is not converted into `max_concurrency=4` or an exact `QuotaSpec(limit=80)`.
RG-3E reports:

```text
approximate_value_not_normalized
```

instead.

---

## 8. Exact provider facts

`ProviderAuthoritativeSnapshot` is one exact bound resource observation. It contains:

```text
provider_id
applicability
resource_key
product
provenance
validity
bindings[]
declared_profile?
observed_state?
pricing_schedules[]
accounting_windows[]
coverage_proofs[]
```

All nested keyed profiles must use the same exact ResourceKey. All products and
bindings must use the same provider identity.

The envelope is still only a fact object. It has no admission outcome or policy field.

---

## 9. Provider-global coverage proof

RG-3D keeps provider-global coverage unknown unless an external proof exists.
RG-3E defines such a proof narrowly:

```text
ProviderGlobalCoverageProof
  key
  exact AccountingWindow
  coverage = complete | partial
  provenance = PROVIDER_CONTROL_PLANE
  validity != unknown
```

Provider documentation alone cannot prove provider-global usage coverage.
An operator binding alone cannot prove provider-global usage coverage.
A successful ordinary chat completion alone cannot prove it either.

A provider control-plane endpoint can produce a proof only after its semantics are
qualified to mean complete/partial usage for that exact scope/window.

---

## 10. Adapter gaps are facts, not decisions

Closed gap vocabulary includes:

```text
product_unbound
account_scope_unbound
project_scope_unbound
model_mapping_unproven
documentation_only
approximate_value_not_normalized
control_plane_schema_unproven
provider_global_coverage_unproven
fact_not_current
```

A gap never means "reject the task". In RG-3E it means only that the requested fact
cannot be mechanically proven at the requested scope.

---

## 11. Vendor adapter contract

Vendor adapters are pure normalizers in RG-3E:

```text
explicit already-acquired fact -> typed result
```

They do not:

```text
perform network I/O
load API keys
select models
select providers
retry calls
alter chat payloads
change fallback
call ResourceGovernor
infer product from routing config
```

Network/control-plane acquisition is kept outside the normalization core so it can be
qualified separately for authentication, privacy, rate behavior, and schema drift.

---

## 12. DeepSeek adapter ruling

Official DeepSeek documentation captured on 2026-09-10 states that concurrency is
account-level and independent of API key, publishes current model defaults, and also
states that accounts may request increased concurrency.

Therefore:

```text
public concurrency table -> published_default
account expansion/live limit -> exact_account only with live provider provenance
```

The current local registry contains the alias `deepseek-flash`, while current official
model documentation exposes names including `deepseek-v4-flash` and
`deepseek-v4-pro`. RG-3E does not guess that the local alias equals either documented
model for pricing/capacity purposes.

The adapter provides:

```text
model_mapping_gaps()
published_account_concurrency()
exact_account_concurrency()
product_pricing()
```

Pricing is materialized only after an explicit PRODUCT binding and a versioned
provider-documentation fact.

Official references captured for qualification:

- https://api-docs.deepseek.com/quick_start/rate_limit/
- https://api-docs.deepseek.com/quick_start/pricing/

---

## 13. GLM / BigModel adapter ruling

Official GLM documentation captured on 2026-09-10 distinguishes standard API access
from GLM Coding Plan and documents dedicated Coding Plan endpoints/keys. Coding Plan
usage is described with a rolling 5-hour window and weekly quota, but public plan
limits use approximate "prompt" language and differ by plan/tier/model/time.

Therefore public approximate prompt counts are not normalized into exact QuotaSpec.
Exact Coding Plan quota/usage is accepted only when an already-acquired provider
control-plane observation gives explicit values, units and windows.

The current local registry model string is `glm-5.3`, while the current official pages
captured for this phase expose other exact model names such as GLM-5.2. No model alias
bridge is invented.

The adapter provides:

```text
model_mapping_gaps()
published_coding_plan()
exact_coding_plan_quota()
```

Official references captured for qualification:

- https://docs.bigmodel.cn/cn/coding-plan/overview
- https://docs.bigmodel.cn/cn/coding-plan/faq
- https://docs.bigmodel.cn/cn/coding-plan/quick-start
- https://docs.bigmodel.cn/cn/guide/develop/http/introduction

---

## 14. MiniMax adapter ruling

Official MiniMax material captured on 2026-09-10 separates standard pay-as-you-go API
keys from Token Plan subscription keys and says they are not interchangeable. Token
Plan documentation exposes 5-hour rolling and weekly quota concepts and an official
read-only usage endpoint:

```text
GET https://www.minimax.io/v1/token_plan/remains
```

The public plan page also uses approximate agent-concurrency guidance. That guidance
is not converted into an exact concurrency limit.

The endpoint existence is documented, but its full response schema is not treated as
stable merely from community examples. RG-3E therefore requires separate live schema
qualification before raw control-plane fields are mapped to exact quota/coverage
semantics.

The adapter provides:

```text
model_mapping_gaps()
published_token_plan()
exact_token_plan_quota()
paygo_pricing()
```

The exact Token Plan method accepts already-qualified typed quota facts. It does not
parse an unqualified raw provider body.

Official references captured for qualification:

- https://platform.minimax.io/subscribe/token-plan
- https://platform.minimax.io/protocol/paid-agreement

---

## 15. Initial operator state was intentionally unbound

At RG-3E start, the current `data/providers.json` has routing entries for DeepSeek,
GLM and MiniMax, but there is no separate qualified resource-product manifest.

Consequences:

```text
DeepSeek account/product identity: not mechanically bound
GLM standard-vs-Coding resource identity: not mechanically bound
MiniMax paygo-vs-Token-Plan resource identity: not mechanically bound
```

Even if routing URLs or key prefixes appear suggestive, RG-3E must report unbound/
unknown until an explicit operator resource manifest exists.

This means a live Token Plan control-plane request must not be issued solely because a
MiniMax credential exists. Product binding is a prerequisite to that qualification.


### 15.1 E3A-E3C qualification update (2026-09-10)

After the initial E0-E2 qualification, owner-authorized identity discovery and
read-only control-plane probes established a narrower mixed state:

```text
DeepSeek standard API/account resource  explicitly bound to local non-secret aliases
DeepSeek model/pricing identity          still unproven
MiniMax Token Plan product family        bound
MiniMax control-plane region             cn (live China endpoint success; global endpoint rejects current key)
MiniMax plan tier                         unknown
GLM product/account entitlement          unbound
```

DeepSeek `/user/balance` and MiniMax China `/v1/token_plan/remains` success schemas
are independently recorded in
`docs/QUALIFICATION-20260910-resource-governor-rg3e-e3c.md`.

This does **not** enable E4 mapping or admission. Product/account/tier facts absent
from authoritative evidence remain unknown.

---

## 16. Pricing

Provider pricing is dynamic and version-sensitive.

RG-3E rules:

1. never derive price from `cost_tier`;
2. never use a different model's price as a fallback;
3. exact model id must be proven;
4. explicit PRODUCT binding is required before pricing becomes an exact product fact;
5. source snapshot/version and validity must be carried;
6. recurring time bands must be materialized to an exact effective interval before a
   future cost calculation consumes them;
7. RG-3E does not yet calculate or enforce a cost budget.

---

## 17. Rate and concurrency

Rate, concurrency, quota and cost remain independent dimensions.

A product may have:

```text
known quota + unknown concurrency
known pricing + unknown rate
known account concurrency + unknown RPM/TPM
```

Approximate "agent count" is not the same as request concurrency.
A provider-published default account concurrency is not automatically the exact limit
for an expanded account.

---

## 18. Control-plane schema qualification

Before a vendor control-plane response can create exact quota/coverage facts, RG-3E
must prove:

1. which product/key type the endpoint applies to;
2. response fields and scalar units;
3. timestamp units/timezone;
4. whether counts are used, remaining, or totals;
5. whether a window is rolling or fixed;
6. whether the snapshot covers the complete bound product/account or only one model;
7. zero versus absent semantics;
8. error/status semantics;
9. whether the endpoint itself has meaningful rate limits;
10. that raw credential/header/body content is not durably logged.

Unknown fields remain unknown. Community examples may guide a probe but cannot alone
become provider contract authority.

---

## 19. Privacy and durability

Resource aliases may be durable only if they are non-secret local labels.

Never persist through RG-3E:

```text
raw API keys
Authorization headers
cookies
raw account identifiers unless explicitly approved as a safe alias
unredacted control-plane response bodies
prompt/messages/user content
```

Durable provenance should use safe source refs, captured timestamps, and version/hash
references.

---

## 20. Prompt/tool/cache neutrality

RG-3E adds no model-visible tool and no universal prompt text.

Qualification must compare parent `9d09a09` and candidate for:

```text
registered ToolRegistry schema bytes
runtime-health projected provider schema bytes
provider tools parameter bytes
Universal Prompt source bytes
```

All must remain exact-identical.

---

## 21. No enforcement invariant

Static qualification must prove that these modules are not imported/consumed by:

```text
src/llm_loop/resources/governor.py
src/llm_loop/resources/provider_calls.py
src/llm_loop/core/loop/engine.py
src/llm_loop/factory.py
fallback/recovery paths
```

Adding types/normalizers is allowed. Feeding the new values into admission is not.

---

## 22. RG-3E qualification matrix

RG-3E may close only if all of the following are proven:

1. PRODUCT is a first-class vendor-neutral ResourceScopeKind;
2. provider documentation profile has no exact ResourceKey;
3. documentation default cannot construct exact account/project truth;
4. exact account/project facts require live provider provenance;
5. exact product pricing requires explicit product binding;
6. provider-global coverage proof requires control-plane provenance;
7. coverage proof is bound to exact scope + exact window + explicit validity;
8. resource binding manifest rejects routing/credential fields;
9. binding manifest requires exact model ids and product/account scope aliases;
10. no URL/API-key/provider-name product inference exists;
11. DeepSeek bare local alias is not silently mapped to a different documented model;
12. GLM unmatched local model alias remains model_mapping_unproven;
13. GLM approximate public prompt limits are not exact quota;
14. MiniMax approximate agent counts are not exact concurrency;
15. MiniMax Token Plan exact quota requires explicit PRODUCT binding + control-plane fact;
16. MiniMax paygo pricing is isolated from Token Plan quota semantics;
17. vendor adapters perform no network I/O;
18. generic fact/binding modules contain no vendor hardcoding;
19. new modules contain no task semantics/admission decision fields;
20. Governor/Coordinator/Engine/Factory have zero RG-3E consumer wiring;
21. current routing config without resource manifest remains unbound;
22. focused + adjacent RG regression passes;
23. Ruff/Pyright/py_compile/diff/security gates pass;
24. prompt/tool surfaces are byte-identical to `9d09a09`;
25. full non-real-LLM regression exits 0;
26. any real control-plane canary is read-only, sequential and prints only sanitized typed facts;
27. an unavailable/unbound control-plane path yields a truthful gap, not guessed identity;
28. no deliberate 429/quota exhaustion test is induced.

---

## 23. Implementation sequence inside RG-3E

```text
E0  authority/applicability contract + PRODUCT scope
E1  explicit operator resource-binding contract
E2  pure vendor normalizers (DeepSeek / GLM / MiniMax)
E3  provider-specific control-plane schema observation where product binding is explicit
E4  exact typed mapping only for independently proven fields
E5  committed-state qualification + safe real canary
```

No E-step enables admission.

---

## 24. Exit and next phase

RG-3E exits with a set of **qualified facts and qualified unknowns**.

The most important acceptable output can be:

```text
product/account unbound
model mapping unproven
provider-global coverage unknown
```

That is better than a convenient but false quota/price/account mapping.

Only after RG-3E closes may RG-3F compare:

```text
RG-3D LFL settlement projection
+
RG-3E bound provider facts
```

in **shadow admission simulations**. RG-3F still does not enforce.

---

## 25. E4 exact typed mapping

E4 maps only fields whose product/scope/schema semantics were independently qualified in E3. It remains observation-only and adds no ResourceGovernor consumer.

### 25.1 DeepSeek account balance

`GET /user/balance` maps to an exact-account `ProviderAccountBalance` containing provider-returned availability plus currency-safe balance rows. This fact is deliberately separate from `CostBudget` and `CostUsage`: account balance is money currently reported by the provider, not a time-window spend ceiling or measured spend. Exact monetary values need not be logged for qualification.

### 25.2 MiniMax China Token Plan remains

For an explicit `token-plan`, `region=cn` product binding and successful control-plane response, each returned provider bucket is mapped mechanically into two `QuotaMetric.PROVIDER_UNITS` facts: current window and weekly window. `start_time`/`end_time` define the exact observed `AccountingWindow`; `reset_at` is the observed window end. Zero quota limits are valid mechanical facts and remain distinct from unknown.

The mapper does **not** infer quota math from `remaining_percent`, does not interpret provider status enums, does not assert provider-global exhaustive coverage, and does not assume a stable recurring window duration. E3C observed one `general` window of 18,000 seconds; a later E4 live observation returned 14,400 seconds. Therefore exact current window bounds are authoritative for that snapshot, while recurring window-policy semantics remain `window_policy_semantics_unproven`.

### 25.3 Deliberate non-wiring

E4 does not wire these facts into Governor/admission/enforcement, does not change routing/fallback, and leaves GLM unbound. RG-3F remains a later shadow-admission phase.
