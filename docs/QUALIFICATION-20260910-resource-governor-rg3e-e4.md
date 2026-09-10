# RG-3E E4 Exact Typed Mapping Qualification — 2026-09-10

## 0. Verdict

**RG-3E E4 exact typed mapping = PASS. RG-3E E0-E5 = PASS/CLOSE.** DeepSeek account balance/availability maps to an independent exact-account fact and is not represented as CostBudget/CostUsage. MiniMax China Token Plan remains maps exact current response windows, limits, usage, and resets into product-level provider-unit quota facts. GLM deliberately remains a qualified unbound/unknown resource identity. No Governor/admission/enforcement consumer is added.

RG-3E closes with both qualified facts and qualified unknowns, exactly as required by the phase design. Closing RG-3E authorizes only the next **RG-3F shadow-admission simulation** phase; it does not enable cloud enforcement.

## 1. DeepSeek mapping

The qualified `/user/balance` schema maps to `ProviderAccountBalance` with `ProviderBalanceEntry` rows using `MoneyAmount(Decimal, currency)`. The authoritative snapshot has exact-account applicability. No `DeclaredResourceProfile.cost_budget` or `ObservedResourceState.cost_usage` is produced. Raw response bodies, raw headers, authorization values, API keys, and exact balance amounts are not part of the durable typed contract or qualification output.

## 2. MiniMax mapping

The mapper requires an explicit MiniMax `token-plan`, `region=cn` product binding, `PROVIDER_CONTROL_PLANE` provenance, and business `status_code=0`. For every returned provider bucket it maps current and weekly count pairs into `QuotaMetric.PROVIDER_UNITS`. `provider_unit` preserves the provider bucket/window identity. Exact window bounds come from response epoch-ms start/end; `reset_at` equals the observed end timestamp.

Zero quota ceilings are legal and remain distinct from unknown. This also fixes the generic RG-3A contract to match its original SoT rule that quota facts are non-negative and zero must not be collapsed into unknown.

The mapper deliberately does not derive anything from `remaining_percent`, does not interpret provider status enums, does not emit a provider-global coverage proof, and does not hard-code a recurring interval duration. E3C observed a 18,000-second general current window; E4 later observed 14,400 seconds. These are exact snapshot facts, not evidence of a fixed product schedule.

## 3. Live observation evidence

Sequential authenticated read-only GET canary on the E4 candidate:

- DeepSeek: HTTP 200; exact account balance mapping succeeded; provider availability was typed; one CNY balance row was present; no cost-budget/cost-usage fact was emitted. Exact money values were not printed.
- MiniMax China Token Plan: HTTP 200; four provider-unit quota facts were emitted for `general/video × current/weekly`; all had exact reset timestamps; usage did not exceed limit; at least one zero limit was preserved; no provider-global coverage proof was emitted. Observed window lengths included 14,400, 86,400 and 604,800 seconds.
- GLM: no request sent; binding remains absent/unbound.

The live canary does not prove provider status-enum semantics, remaining-percent arithmetic semantics, recurring window-policy semantics, or provider-global exhaustive coverage.

## 4. Authority boundary

E4 remains observation-only. It does not:

- admit, defer, or reject a request;
- modify ResourceGovernor limits;
- select/switch providers or models;
- change fallback/retry behavior;
- infer GLM product identity;
- enable TrustDomain/cancel policy;
- add prompt text or provider-visible tools.

## 5. Qualification gates

Implementation commit:

```text
b293039bc65e04627a6c4f345f364e9f389b497a
feat(resources): map RG-3E E4 provider facts
parent = b35096e
8 files / +659 -5
```

Static and committed-state evidence:

- staged security: 8 E4 files PASS;
- detached committed tracked-tree security: 1519 files PASS;
- Ruff: PASS;
- Pyright: 0 errors / 0 warnings / 0 informations;
- resource/factory/event broad regression: 100% PASS;
- arch/resource focused regression: 100% PASS;
- `git show --check`: PASS;
- changed-runtime `py_compile`: PASS;
- staged full `pytest tests -q -m 'not real_llm'`: 100% / explicit RC=0 using the repository venv;
- detached clean committed full: 100% / explicit RC=0 using the repository venv.

One earlier full command was accidentally launched with system Python and stopped during collection with missing optional repository dependencies (`lark_oapi`, `pypdf`, PIL, zstandard). It executed no tests and is classified as an execution-environment error, not a candidate result. The corrected repository-venv staged and committed runs both exited 0.

## 6. Prompt / tool surface identity

Exact parent `b35096e` versus E4 candidate comparison:

```text
registered lazy schemas  62 / 21730 bytes / SHA 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
projected schemas        60 / 21118 bytes / SHA 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c
provider tools           60 / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
prompt.py SHA            30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
```

All are byte-identical.

## 7. Clean committed live mapper canary

The final canary imported source from detached clean commit `b293039` and used the existing ignored non-secret binding manifest. Authenticated requests were sequential read-only GETs and output was sanitized.

DeepSeek:

```text
HTTP 200
mapped = true
availability typed
balance rows = 1
currency set = {CNY}
cost fact emitted = false
```

MiniMax China Token Plan:

```text
HTTP 200
mapped = true
provider units = general/current, general/weekly, video/current, video/weekly
observed exact window seconds included 14400 / 86400 / 604800
zero limit preserved = true
all reset_at present = true
usage <= limit = true
coverage proof count = 0
```

Explicit retained gaps:

```text
provider_global_coverage_unproven
provider_status_semantics_unproven
remaining_percent_semantics_unproven
window_policy_semantics_unproven
```

GLM:

```text
binding = unbound
request_sent = false
```

No exact account balance amount, quota count, API key, authorization header, raw response body/header, account identifier, prompt, or user content was written to qualification output.

## 8. Final phase ruling

```text
E0 authority/applicability contract          PASS
E1 explicit resource binding contract        PASS
E2 pure vendor normalizers                   PASS
E3 identity/control-plane observation        PASS with qualified unknowns
E4 exact mapping of independently proven data PASS
E5 committed-state + safe live qualification PASS
RG-3E overall                                PASS / CLOSE
RG-3F                                        MAY START SHADOW ONLY
cloud enforcement                            NOT ENABLED
```

GLM remaining unbound does not falsify RG-3E completion. The RG-3E exit contract explicitly permits qualified unbound/unknown facts and forbids inventing identity merely to make every provider look complete. Future GLM binding can be added when authoritative product/account evidence exists.
