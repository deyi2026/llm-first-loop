# RG-3E E3A-E3C Resource Identity / Control-Plane Qualification — 2026-09-10

## 0. Verdict

**E3A discovery audit = PASS. E3B minimal local binding = PASS for DeepSeek standard API and MiniMax Token Plan; GLM deliberately remains unbound. E3C read-only schema qualification = PASS for DeepSeek account balance and MiniMax China Token Plan remains, with explicit qualified unknowns. E4 exact mapping is NOT IMPLEMENTED. RG-3E overall remains HOLD and RG-3F must not start.**

This qualification extends, rather than rewrites, the earlier bounded result in
`docs/QUALIFICATION-20260910-resource-governor-rg3e.md`.

No cloud admission/enforcement, routing, fallback, TrustDomain, cancellation, or model-visible prompt/tool behavior is changed by this qualification.

---

## 1. Qualified baseline

Feature branch at E3A start:

```text
feature/resource-governor-rg3e-authoritative-adapters-20260910
6db43f6  docs(resources): record RG-3E partial qualification
a31dbbb  feat(resources): add RG-3E authoritative adapters
9d09a09  docs(resources): record RG-3D qualification
```

The local operator binding is intentionally stored under ignored `data/` and is not a Git artifact. It contains only non-secret aliases, exact local model identifiers, scope aliases, provenance refs, and version refs.

---

## 2. E3A — identity discovery audit

### DeepSeek

Current routing uses the official DeepSeek API surface and a local routing model id `deepseek-flash`.

Official DeepSeek documentation provides authenticated `GET /user/balance` and defines the returned balance schema. Public concurrency guidance cannot prove this account's exact concurrency because account-specific expansion is possible.

Therefore:

```text
standard API/account balance resource family   discoverable enough for read-only balance observation
local deepseek-flash -> documented pricing id  unproven
exact account concurrency                       unproven
exact RPM/TPM                                    unproven
```

### MiniMax

The current credential class is `sk-cp`; official MiniMax Token Plan material states that Token Plan subscription keys use this class and are separate from ordinary pay-as-you-go keys.

MiniMax publishes region-specific Token Plan control-plane endpoints. The current credential is accepted by the China endpoint and rejected by the global endpoint, so the resource binding may record `region=cn` without inferring Plus/Max/Ultra tier.

Therefore:

```text
product family       Token Plan
control-plane region cn
plan tier             unknown
exact model quota     not inferred from routing model
```

### GLM

Current routing uses the official Coding Plan API endpoint, but that fact alone does not prove the current LFL invocation's entitlement/tier or actual Coding Plan deduction. No authenticated GLM control-plane request was made in this phase.

Therefore GLM remains intentionally unbound.

---

## 3. E3B — minimal non-secret local binding

The ignored local manifest resolves exactly:

```text
deepseek / deepseek-flash
  product = standard-api
  product scope = primary:standard-api
  account scope = primary:account
  region = unknown

minimax / MiniMax-M3
  product = token-plan
  product scope = primary:token-plan
  account scope = primary:account
  region = cn

glm / glm-5.3
  UNBOUND
```

Important limits:

- `account_alias=primary` is a local non-secret alias, not the provider's raw account id;
- the binding says which local calls consume which resource family, not which plan tier is owned;
- DeepSeek model/pricing identity remains unproven even though the account resource is bound;
- MiniMax tier remains unknown;
- GLM is absent from the manifest;
- no base URL, endpoint, API key, token, Authorization header, cookie, or raw account identifier is stored in the manifest.

---

## 4. E3C — DeepSeek account-balance schema

One authenticated read-only request was sent to the official balance endpoint.

Observed transport result:

```text
HTTP status       200
content type      application/json
is_available      bool (observed true)
balance_infos     array (observed one row)
currency          CNY in this observation
total_balance     decimal string
granted_balance   decimal string
topped_up_balance decimal string
rate/reset headers observed  none
```

The response shape matches current official DeepSeek documentation.

Exact monetary values were deliberately not printed or persisted in qualification logs.

Qualified semantics:

- this is an account balance observation;
- `is_available` is a provider-returned availability fact;
- balance strings are monetary amounts in the row currency;
- absence of rate-limit headers does not mean unlimited rate;
- the balance endpoint does not prove exact account concurrency, RPM, TPM, or model pricing.

A future E4 mapping must not turn account balance into a time-window `CostBudget` unless an independent provider/operator contract proves that meaning.

---

## 5. E3C — MiniMax Token Plan schema

### 5.1 Region qualification

The same `sk-cp` credential was tested sequentially against the provider-documented global and China Token Plan remains endpoints.

Observed results:

```text
global endpoint: HTTP 200, business code 2049, sanitized message = invalid api key
China endpoint:  HTTP 200, business code 0, sanitized message = success
```

No raw credential or response body was persisted.

This supports the exact narrow conclusion that the current credential's qualified Token Plan control-plane region is `cn`. It does not prove a Plus/Max/Ultra tier.

### 5.2 Success schema

The successful China response contains:

```text
base_resp.status_code
base_resp.status_msg
model_remains[]
```

Observed `model_remains` bucket names:

```text
general
video
```

Each row exposes:

```text
current_interval_total_count
current_interval_usage_count
current_interval_remaining_percent
current_interval_status
start_time
end_time
remains_time
current_weekly_total_count
current_weekly_usage_count
current_weekly_remaining_percent
current_weekly_status
weekly_start_time
weekly_end_time
weekly_remains_time
```

### 5.3 Window and unit qualification

Mechanical live checks for the **E3C observation** established:

```text
general current interval = 18,000 seconds in that snapshot
video current interval   = 86,400 seconds in that snapshot
weekly window            = 604,800 seconds in that snapshot
start/end fields          epoch milliseconds
remains_time              milliseconds remaining until current interval end
weekly_remains_time       milliseconds remaining until weekly end
```

These values qualified the response-field units and the exact bounds of that observation; they did **not** prove a fixed recurring product policy. A later E4 live observation returned a 14,400-second `general` current window while preserving the same start/end schema. The recurring interval rule is therefore explicitly unqualified; consumers must use the response's exact current window rather than a hard-coded 5-hour assumption.

`current_*_total_count` and `current_*_usage_count` were non-negative and usage did not exceed total in the observation.

Remaining-percent fields are provider observations in the 0..100 range. For the `general` bucket, the live value did **not** equal a simple `(total_count - usage_count) / total_count` transformation at observation time. Therefore RG-3E must not derive count from percent or percent from count.

Status values were observed but their general semantic enum is not qualified here.

### 5.4 Coverage limits

`general` / `video` are provider quota buckets, not exact LFL model ids. The response therefore does not justify a model-specific quota assignment to `MiniMax-M3`.

The endpoint is documented as Token Plan usage, but this qualification does not yet prove that the returned rows are an exhaustive provider-global coverage proof for every Token Plan entitlement dimension. `ProviderGlobalCoverageProof` therefore remains absent/unknown.

---

## 6. Privacy / safety evidence

All authenticated probes were read-only GET requests, sequential, and intentionally sanitized before output.

Not printed or durably stored:

```text
API keys
Authorization values
raw response bodies
raw response headers
exact DeepSeek balance amounts
provider account ids
cookies
prompt/messages/user content
```

No deliberate 429, quota exhaustion, concurrency saturation, purchase, subscription mutation, or billing action was induced.

---

## 7. Exact current qualification boundary

```text
E3A identity discovery audit                          PASS
E3B DeepSeek standard API/account binding            PASS (local non-secret alias)
E3B MiniMax Token Plan product + cn region binding   PASS (tier unknown)
E3B GLM binding                                      NOT DONE / deliberately unbound
E3C DeepSeek account balance success schema          PASS
E3C MiniMax China Token Plan remains success schema  PASS
E3C MiniMax global endpoint current-key applicability NOT APPLICABLE (business 2049)
E3C GLM live control-plane schema                     NOT QUALIFIED
E4 DeepSeek exact typed balance mapping               NOT IMPLEMENTED
E4 MiniMax exact quota mapping                        NOT IMPLEMENTED
provider-global complete coverage                     UNKNOWN
RG-3E overall                                         HOLD / NOT FULLY CLOSED
RG-3F shadow admission                                DO NOT START
```

The next safe phase is **E4 exact typed mapping only for fields proven above**. DeepSeek balance should remain a balance/availability observation rather than being mislabeled as a spending budget; MiniMax may map the exact product-level count/window fields as provider-defined quota units while retaining bucket/status/coverage unknowns. GLM remains untouched until independent account/product evidence exists.
