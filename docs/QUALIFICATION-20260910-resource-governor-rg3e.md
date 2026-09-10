# QUALIFICATION-20260910: Resource Governor RG-3E Authoritative Vendor/Product Adapters

## 0. Verdict

**RG-3E E0-E2 = PASS. RG-3E E3 = NOT QUALIFIED because the current operator resource-product manifest is absent. Overall RG-3E is NOT fully CLOSED, and RG-3F must not start yet.**

This is a deliberate authority boundary, not a runtime failure.

The implementation candidate proves that LFL can represent provider-published defaults,
explicit resource/product identities and already-authoritative provider facts without
turning any of them into admission policy. It also proves the negative case that is
currently true on this machine:

```text
provider routing configuration exists
+
resource-product binding is absent
=
product/account truth remains unbound
=
no product-specific control-plane request
=
no exact quota/cost/concurrency fact is emitted
```

The phase must not be called fully complete until an explicit non-secret product/account
binding exists and the corresponding provider control-plane schema is independently
qualified.

---

## 1. Qualified baseline and implementation

Base:

```text
integration/rg3-unified-20260910
9d09a09918298aa3dd3199cad83917907ff54991
```

Implementation:

```text
a31dbbbc7ec982e098f598a6e207b83ffbae8126
feat(resources): add RG-3E authoritative adapters
```

Implementation diff:

```text
14 files
+2280 / -2
```

No upstream is configured and nothing was pushed during qualification.

---

## 2. What E0-E2 now provide

### E0 — authority/applicability contract

Provider facts are split into mechanically distinct envelopes:

```text
ProviderPublishedResourceProfile
ProviderAuthoritativeSnapshot
ProviderGlobalCoverageProof
ProviderAdapterResult
```

A provider-published profile intentionally has no exact `ResourceKey`. Public
documentation can therefore state a published default without silently becoming the
current account's exact capacity.

Exact fact applicability is closed to:

```text
exact_product
exact_account
exact_project
```

`ResourceScopeKind.PRODUCT` was added because subscription/product quotas can span
multiple models without being equivalent to a whole ACCOUNT quota.

### E1 — explicit resource binding contract

`resource_bindings.py` is separate from provider routing configuration.

The closed binding accepts only non-secret resource identity data such as:

```text
provider_id
product_id
account_alias
exact model_ids[]
PRODUCT / ACCOUNT / optional PROJECT scope aliases
api_family / region (optional)
source_ref
version_ref
```

It rejects routing or credential fields including:

```text
api_key
api_key_env
token
secret
authorization
base_url
endpoint
```

Manifest resolution is exact `(provider_id, model_id)` only. Empty manifest means
unbound. Overlapping exact provider/model ownership is rejected.

### E2 — pure vendor normalizers

The current adapters are pure typed normalizers:

```text
DeepSeekResourceAdapter
GlmResourceAdapter
MiniMaxResourceAdapter
```

They perform no network I/O, do not load credentials and are not consumed by the
ResourceGovernor, ProviderCallCoordinator, LoopEngine or Factory.

DeepSeek:

- public account concurrency remains a published default;
- exact account concurrency requires live provider provenance;
- pricing requires explicit PRODUCT + exact model/product/key binding;
- local alias `deepseek-flash` is not guessed to equal a current documented v4 model.

GLM:

- public Coding Plan prompt counts described approximately are not normalized into
  exact quota;
- exact Coding Plan quota requires a PRODUCT key, explicit model binding and
  provider control-plane provenance;
- local `glm-5.3` is not guessed to equal a different currently documented model id.

MiniMax:

- approximate "N concurrent agents" guidance is not normalized into request
  concurrency;
- exact Token Plan quota requires a PRODUCT key, explicit model binding and
  provider control-plane provenance;
- pay-as-you-go pricing remains separate from Token Plan quota semantics.

---

## 3. Current official provider evidence used for contract design

Official provider documentation was checked on 2026-09-10 only to establish published
contract semantics. It was not treated as exact account truth.

### DeepSeek

Current official material states that published concurrency is account-level rather
than per API key, and that accounts may request increased concurrency. That makes the
public table a valid published default but not sufficient proof of the exact current
account entitlement.

References:

- `https://api-docs.deepseek.com/quick_start/rate_limit/`
- `https://api-docs.deepseek.com/quick_start/pricing/`

### GLM / BigModel

Current official material distinguishes standard API access from Coding Plan,
including dedicated plan access. Coding Plan limits are expressed through rolling
5-hour / weekly concepts and public approximate prompt counts; approximate prompt
counts are therefore not exact quota facts.

References:

- `https://docs.bigmodel.cn/cn/coding-plan/overview`
- `https://docs.bigmodel.cn/cn/coding-plan/faq`
- `https://docs.bigmodel.cn/cn/coding-plan/quick-start`
- `https://docs.bigmodel.cn/cn/guide/develop/http/introduction`

### MiniMax

Current official material distinguishes ordinary pay-as-you-go keys from Token Plan
subscription keys and documents Token Plan usage concepts plus a read-only remains
endpoint. Public agent-count guidance is approximate and is not request concurrency.
Endpoint existence alone is not enough to freeze every raw response field as a stable
schema.

References:

- `https://platform.minimax.io/subscribe/token-plan`
- `https://platform.minimax.io/protocol/paid-agreement`

---

## 4. Current operator binding observation

The current operator `data/providers.json` contains routing information for all three
providers, but no separate qualified resource-product manifest.

A committed-state negative observation was run with the current routing defaults and
an empty resource manifest.

Result:

```text
DeepSeek / deepseek-flash
  binding_found=false
  product_unbound
  model_mapping_unproven
  control_plane_requested=false
  exact_fact_emitted=false

GLM / glm-5.3
  binding_found=false
  product_unbound
  model_mapping_unproven
  control_plane_requested=false
  exact_fact_emitted=false

MiniMax / MiniMax-M3
  binding_found=false
  product_unbound
  model name exact-match available
  control_plane_requested=false
  exact_fact_emitted=false
```

Verdict:

**PASS for the negative/unbound invariant.**

The implementation did not infer product identity from:

```text
base URL
credential variable name
provider id
model-family similarity
```

and therefore did not call a product-specific control plane.

---

## 5. Why no live product control-plane canary was sent

A MiniMax Token Plan endpoint exists, and GLM exposes product-specific plan surfaces,
but the current operator state does not mechanically prove that the configured
credential belongs to those products.

Calling a product-specific endpoint merely because a credential exists would violate
the same identity boundary RG-3E is meant to establish.

Therefore the absence of a live product control-plane request in this qualification is
intentional and correct.

This means the following claims are **NOT** made:

```text
this MiniMax key is Token Plan
this MiniMax key is paygo
this GLM credential is Coding Plan
this GLM credential is standard API
this DeepSeek account has the published default concurrency
provider-global usage coverage is complete
current account quota/cost/concurrency is known
```

---

## 6. Focused and adjacent validation

RG-3E focused contract coverage includes:

- PRODUCT as first-class resource scope;
- published default cannot become exact account truth;
- exact account/project live provenance requirements;
- explicit product binding for pricing/quota;
- exact model/product/resource binding consistency;
- provider-global coverage proof requires control-plane provenance and explicit
  scope/window/validity;
- closed resource manifest and forbidden routing/credential fields;
- exact resolver and overlap rejection;
- DeepSeek/GLM model aliases are not guessed;
- GLM approximate prompt limits remain approximate;
- MiniMax approximate agent count remains approximate;
- Token Plan quota and paygo pricing remain separate;
- no network I/O in vendor normalizers;
- no RG-3E consumer wiring into Governor/Coordinator/Engine/Factory.

Focused RG-3E + RG-3A contract runs passed 100% throughout implementation.

A broad committed-state suite covering RG-0 through RG-3E plus EventStore/replay,
Factory, fallback, Learning, Summarizer, Extractor and SubAgent adjacency passed 100%
with aggregate qualification `RC=0`.

---

## 7. Static / security / architecture gates

Clean committed `a31dbbb`:

```text
git show --check                 PASS
tracked tree security            PASS (1516 tracked files)
Ruff src/tests                    PASS
Pyright                           0 errors / 0 warnings / 0 informations
architecture guards              PASS (14/14)
changed runtime py_compile        PASS
git diff/check                    PASS
worktree                          clean
```

No secrets, runtime data or local private path artifacts were added by the RG-3E
implementation.

---

## 8. Full non-real-LLM regression

Clean committed `a31dbbb`:

```text
collected non-real-LLM items  5005
progress                      100%
explicit external rc file     RC=0
```

The earlier staged run also reached 100% and normal warnings-only teardown, but its
wrapper did not surface the shell `RC=` marker through the Runtime handle. This
qualification therefore relies on the later clean committed run with a separately
persisted explicit `RC=0`, not on an inferred staged exit code.

---

## 9. Prompt / tool surface identity

Parent `9d09a09` versus clean committed `a31dbbb`:

```text
registered schemas
  count 62
  bytes 21730
  SHA256 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484

runtime-health projected schemas
  count 60
  bytes 21118
  SHA256 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c

provider tools parameter array
  count 60
  bytes 22978
  SHA256 d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8

Universal Prompt source
  SHA256 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
```

All four are exact-identical between parent and candidate.

RG-3E therefore adds no prompt tax and no model-visible tool/schema tax.

---

## 10. No-enforcement proof

Static inspection confirms zero RG-3E consumer references in:

```text
src/llm_loop/resources/governor.py
src/llm_loop/resources/provider_calls.py
src/llm_loop/core/loop/engine.py
src/llm_loop/factory.py
```

The new vendor adapters also contain no `httpx`, `requests` or `urllib.request`
network acquisition path.

Thus RG-3E currently cannot alter:

```text
admission
routing
fallback
retry
task completion
provider payload
current user response
```

---

## 11. Qualified unknowns retained deliberately

The following unknowns are **part of the correct qualification result**:

```text
DeepSeek exact account entitlement          unknown/unbound
DeepSeek local alias -> current doc model   unproven
GLM exact product identity                  unknown/unbound
GLM local alias -> current doc model        unproven
MiniMax paygo vs Token Plan identity        unknown/unbound
provider-global usage coverage              unknown
exact current quotas                        unknown
exact current account concurrency           unknown
exact current cost exposure                 unknown
```

They must not be filled by convenience defaults.

---

## 12. Remaining E3/E4 qualification

Before RG-3E can fully CLOSE, an explicit non-secret resource manifest must bind the
actual products/accounts/models to local aliases.

Only after that binding exists may RG-3E run read-only sequential provider-specific
control-plane observations.

For each such provider/product observation, qualification must establish:

1. credential/product applicability;
2. raw field schema and scalar units;
3. timestamp/window semantics;
4. used versus remaining versus total semantics;
5. exact product/account/model coverage;
6. zero-versus-absent semantics;
7. provider error/status behavior;
8. safe sanitized logging;
9. version/freshness policy;
10. whether a `ProviderGlobalCoverageProof` is justified at all.

Unknown or approximate fields remain unnormalized.

---

## 13. Final phase ruling

```text
RG-3E E0 authority/applicability contract       PASS
RG-3E E1 explicit resource binding contract     PASS
RG-3E E2 pure vendor normalizers                PASS
RG-3E negative unbound observation              PASS
RG-3E E3 live product control-plane schema      NOT QUALIFIED (binding prerequisite absent)
RG-3E E4 exact live provider mapping            NOT QUALIFIED
RG-3E overall                                   HOLD / NOT FULLY CLOSED
RG-3F shadow admission                          DO NOT START
```

The next action is not to guess account/product identity and not to turn on cloud
admission. The next action is to establish the explicit product/account binding, then
continue E3 with sanitized read-only observation.
