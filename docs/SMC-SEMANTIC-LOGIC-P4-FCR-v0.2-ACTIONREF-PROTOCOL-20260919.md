# SMC Semantic Logic P4-FCR v0.2 — ActionRef Provider-Surface Protocol

> Date: 2026-09-19
> Status: FROZEN CANDIDATE / DECLARATION-ONLY / NO REAL MODEL YET
> Parent negative result: 52d5e78e650e1693db3453285febf36e8ab9cb68
> Execution Binding contract evidence: 3b7163a11dca88e7a4e2bd6c6b7146e5925adc31
> P1 evidence anchor: d0af187baa2819b76a6df31a962f3c0f0fa6c814
> P1.1 evidence anchor: 5d11c5866e0e9349163577a1382b8469c32dca51

## 1. Problem

P4-FCR v0.1 is immutable and NOT_QUALIFIED.

Arm B reached 20/20 structural validity but only 16/20 mechanical validity. All four mechanical failures were select declarations that changed the exact opaque target from:

grounding://browser/v0.1/p4fcr-snapshot/object/el_33333333333333333333

to:

ground://browser/v0.1/p4fcr-snapshot/object/el_33333333333333333333

The provider declaration already contained the changed bytes. The v0.1 scorer did not normalize them, and the P4-D compiler only forwarded declared refs. Therefore the defect is model-facing exact opaque-ref reproduction, not Browser execution or compiler mutation.

## 2. Treatment

Arm A remains the current control surface:

- browser_semantic_execute(verb, target_ref, args)
- target_ref remains the full exact GroundingRef.

Arm B keeps the five typed semantic tools but replaces object_ref/resource_ref with one uniform short opaque field:

- browser_semantic_click(action_ref)
- browser_semantic_fill(action_ref, text, mode)
- browser_semantic_select(action_ref, value)
- browser_semantic_scroll(action_ref, delta_pages)
- browser_semantic_navigate(action_ref, url)

The model still chooses:

- which tool/semantic verb;
- which observed ActionRef handle;
- semantic values such as text, mode, value, delta_pages and URL.

The program may only:

- exact-resolve the chosen ActionRef through a frozen binding record;
- validate mechanical session/scope/version/retention facts;
- hydrate the bound exact GroundingRef;
- delegate canonical compilation to the already-qualified Browser semantic compiler.

The program MUST NOT:

- select a target for the model;
- rank candidates;
- fuzzy match;
- similarity match;
- rebind;
- silently refresh;
- substitute a successor ref;
- retry;
- normalize a malformed handle;
- change semantic arguments;
- decide task completion.

## 3. Pair fairness

The core matrix remains five task families x four repeats x two arms = 40 rows with the same rotation and A/B order as v0.1.

Each A/B pair receives byte-identical user task text.

The shared task text exposes both mechanical identities for the already-observed target:

- grounding_ref = the current full GroundingRef;
- action_ref = the short opaque ActionRef bound to that exact target.

The tool schema determines which identity the arm must declare:

- Arm A uses target_ref with the GroundingRef;
- Arm B uses action_ref.

No arm-specific instruction text is added.

## 4. Frozen ActionRef bindings

The v0.2 declaration fixtures use five opaque handles with no semantic verb in the handle:

| Target | ActionRef |
|---|---|
| page resource | ar_5f8c2a |
| object el_111... | ar_a17d93 |
| object el_222... | ar_c42e11 |
| object el_333... | ar_7b31f0 |
| object el_444... | ar_d9054c |

Each binding record mechanically includes:

- session_id;
- domain;
- scope_ref;
- semantic_object_id;
- observation_ref;
- observed_version;
- authority_scope;
- exact GroundingRef;
- logical issued_at and expires_at;
- integrity digest.

TTL remains retention-only. Exact observed-version matching is a separate admission fact.

## 5. Deterministic ActionRef hydration

Qualification-only hydration accepts:

- current session facts;
- current logical time;
- current observed version;
- the model-selected ActionRef.

It returns the bound GroundingRef only when all exact mechanical checks pass.

It rejects:

- unknown handle;
- wrong session/authority;
- integrity mismatch;
- expired retention;
- stale version;
- kind mismatch between resource/object binding class where mechanically required.

Multiple simultaneous faults do not define a new global reason-precedence contract.

## 6. FCR scoring

P4-FCR v0.2 remains declaration-only.

No Browser tool is executed. No ActionRef is hydrated during a formal model row.

Offline scoring checks the raw first semantic declaration.

Arm B is mechanically valid only when:

- expected typed tool is selected;
- action_ref is byte-exact;
- all semantic args are byte/value exact;
- no undeclared semantic fields are injected.

The frozen hard gate remains:

- Arm B structural = 20/20;
- Arm B mechanical = 20/20;
- targeted P4-X01/P4-X02/P4-X06/P4-X07 total = 0;
- tool execution = 0;
- Browser runtime rows = 0;
- fallback = 0;
- normalization = false;
- retry = false;
- task-completion judgment = false.

## 7. Deterministic qualification before any real model

Before the first model request, v0.2 MUST prove:

1. fresh independent 40-row plan and protocol identity;
2. v0.1 artifacts are unchanged;
3. Arm A provider schema remains current control;
4. all five Arm-B schemas use action_ref and no object_ref/resource_ref;
5. pair prompts are byte-identical;
6. frozen ActionRef records are unique and integrity-valid;
7. exact hydration recovers the v0.1 GroundingRefs;
8. unknown/cross-session/stale/expired/wrong-kind inputs reject with zero Browser dispatch;
9. canonical typed compilation after hydration is equivalent to the existing P4-D canonical action;
10. no Factory/registry/production consumer is added;
11. focused/adjacent tests, Ruff, Pyright, security and full CI pass;
12. preflight reports model_requests=0 and tool_execution_total=0.

Because replacing full GroundingRef with ActionRef is a material provider-visible protocol change, completion of these deterministic gates MUST stop at a human checkpoint before the first real v0.2 model request.

## 8. Non-claims

Deterministic qualification does not prove:

- the model will copy ActionRef correctly;
- P4-FCR v0.2 will qualify;
- ActionRef improves all models/providers;
- P4-LIVE is safe;
- production Browser ActionRef wiring is ready.

Those require later independent evidence.
