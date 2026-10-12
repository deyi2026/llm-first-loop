# Context Integrity P7 Qualification — 2026-09-14

## Verdict

**Gate D (Live Qualification): PASS.**

This report freezes the P7 evidence for the State Ownership / Run Ownership / Context Integrity implementation line. The qualified production baseline before this report is:

- branch: `fix/active-run-ingress-1214-20260914`
- pre-P7 HEAD: `69b084d7dd73c7523e23237aa7b249f4f3031824`
- provider/live qualification changes in this P7 commit: **none**
- P7 commit scope: qualification runner + adversarial tests + this report only

Gate E (official canary / restart / deployment / push / promotion) is **NOT RUN** in this report and requires a separate owner authorization.

## 1. Qualified implementation ancestry

| Phase | Commit | Mechanical boundary |
|---|---|---|
| P1 | `8e36d579` | preserve active run ingress across compaction |
| P1 | `96c7a00a` | conservative rebuild of invalid provider projections |
| P1 | `b478c968` | close final provider projection boundary |
| P1 | `44f76c15` | provider overflow is authoritative |
| P2 | `1daefa04` | missing-context authority fails closed |
| P3 | `3a95ed46` | late results fenced by run generation |
| P3 | `4ee45de9` | late child completion ownership qualified |
| P4 | `6d04158f` | process state lifetime bounded |
| P4 | `170f8833` | lifetime high-water retention eliminated |
| P5 | `1e854429` | exact provider-wire integrity enforced |
| P6 | `047bc054` | proven-dead legacy shared authority fallbacks retired |
| CI debt | `69b084d7` | authority/import ratchets restored without weakening boundaries |

No P7 live result was used to justify changing production semantics after measurement began.

## 2. Deterministic / adversarial concurrency

`tests/unit/test_p7_adversarial_context_integrity.py` exercises the physical provider boundary with one shared production `LLMClient`:

1. two Sessions are forced to overlap at the already-constructed `_client.stream`; each physical JSON packet must contain only its own ingress and each response must return only to its owning Session;
2. a second run for the same Session is attempted while the first is held at physical transport; it must fail with `SessionBusyError` before a second physical send.

Current-head stress result:

- serial repetitions: **20/20 PASS**
- crossed A/B physical packets: **0**
- same-session second physical sends: **0**
- transport-only `_active_run_ingress_ref` leakage: **0**
- transport-only `_provider_replay` leakage: **0**

The broader focused P7/1214/provider-wire suite is also green: **37/37 PASS**.

## 3. Real GLM-5.3 — delegated ingress + long-compaction

### 3.1 Runner contract

`scripts/qualify_p7_glm1214_live.py` replays the privacy-safe production incident shape through the current history projector and the production `LLMClient` final wire path.

The live packet is intentionally synthetic; the gate is mechanical, not answer-quality based. Each trial must prove all of the following:

- history compaction actually occurred;
- exactly one delegated active-run ingress survives;
- compaction still retains at least one complete assistant-tool atomic group;
- internal ingress markers are stripped before physical send;
- provider replay transport keys do not leak;
- tool declarations/results remain structurally paired;
- the provider accepts the **first** physical request; a hidden first-failure-then-retry cannot pass because `request_count` must equal 1.

The runner does not persist raw prompts, raw answers, provider bodies, or credentials. It persists only mechanical structure/counts, token/finish facts, lengths, and hashes.

Frozen inputs:

- incident fixture SHA256: `ae5a1dd7b9640a46ca31aa4128a3f7705f83f56072768bf5dcb80ca507f2d701`
- provider registry SHA256: `bf463c72a8cfcd9261ed2d8c11d4f8b3d4ed37569bb4f678d50566e231e6be4e`
- final privacy-safe live result SHA256: `3c853f07983749de7ad1802ac14e61e4a842c9590838372e3acbb6661dec49e9`

### 3.2 Result

| Trial | Result | Finish | Truncated | Physical sends | Compacted | Archived | Active ingress | Tool declarations/results | Wire marker | Wire violations |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | success | stop | false | 1 | true | 9 | 1 | 2 / 2 | 0 | 0 |
| 2 | success | stop | false | 1 | true | 9 | 1 | 2 / 2 | 0 | 0 |
| 3 | success | stop | false | 1 | true | 9 | 1 | 2 / 2 | 0 | 0 |

All three physical packets had the exact role shape:

`system → assistant → user(delegated ingress) → assistant(tool calls) → tool → tool`

There were no HTTP/provider errors and no GLM 1214. Therefore this is not a retry-assisted false green.

**GLM P7 verdict: PASS (3/3).**

## 4. Real Ornith — Context Integrity / local long-agent non-regression

The existing 8901 runtime was reused without restart or model swap. Before and after qualification there was exactly one listener and the same Ornith process remained healthy. Runtime contract remained:

- model: `Ornith-1.5-35B-A3B-MLX`
- max tokens: 16000
- prompt concurrency: 1
- decode concurrency: 1
- reasoning contract observed by current client: `on / capable / chat_template / supported / requested=true`
- current universal system prompt: 380 chars
- no second local model loaded

The behavior protocol reuses the previously established Context Integrity canary in `docs/analysis/QUALIFICATION-20260911-common-governance.md` rather than inventing an easier smoke task.

Privacy-safe result SHA256: `8c7c827a41210dae90754bd956ef8e4b1e240b20914525dfb8137ba3ce3fa03b`.

| Probe | Required behavior | Result | Second-round cache hit |
|---|---|---|---:|
| success receipt | call `get_value` once; after success answer current 47 without repeat | PASS | 511 |
| current over stale | historical 12 must not beat current tool fact 88; no repeat | PASS | 520 |
| recent `继续` | bind to the unique recent pending action, not the old closed task | PASS | 568 |
| six old tasks + 8-step current chain | STEP1..STEP8 exactly once in first round; second round no tool; final contains VALUE-1..VALUE-8 | PASS | 794 |

The long-chain first response contained exactly eight `inspect_step` calls with STEP1 through STEP8, zero duplicates and zero omissions. The second response made zero tool calls and preserved all eight returned values.

The positive cache-hit facts on each second round provide a live stable-prefix reuse observation; no semantic pass criterion is inferred from the cache percentage itself.

**Ornith P7 verdict: PASS (4/4).**

## 5. P4 lifetime / memory plateau carried into Gate D

P4 was already closed before P7 on this same ancestry. The qualification established bounded lifetime behavior across RunState, Session/Event stores, provider/browser state, jobs, session caches, and SubAgent-related ephemeral state, including the planned 100 → 1K → 10K scale progression. The final EventStore high-cardinality path fix restored the 1K → 10K plateau to approximately +863 bytes instead of linear retained growth.

P7 did not re-open or weaken those lifecycle boundaries.

## 6. Gate C — static / security / committed-state

Before freezing this report, the pre-P7 production HEAD `69b084d7` had already passed the full repository gate after two historical test/architecture debts were repaired independently:

- repository Ruff: PASS
- env-pin audit: PASS (`569` test files / `0` undeclared)
- src Pyright: `0 errors / 0 warnings / 0 informations`
- tier0: PASS
- full pytest xdist: PASS
- architecture guards: PASS
- tracked-tree security scan: PASS

The exact final P7 three-file candidate is requalified again before commit. Final committed-state results are filled only after the exact candidate passes; no earlier run is substituted for a failing final tree.

Final exact P7 candidate result:

- repository Ruff: PASS
- env-pin audit: PASS (`569` test files / `0` undeclared)
- src Pyright: `0 errors / 0 warnings / 0 informations`
- tier0: PASS
- full pytest xdist gate: PASS
- one `tests/unit/test_job_registry.py` xdist distribution false red was serial-rechecked green under the repository's existing D-B2-09 policy and was explicitly non-blocking
- final `scripts/ci_gate.sh`: **PASS / exit 0**

**Final P7 candidate committed-state gate: PASS.**

## 7. Privacy and evidence boundary

The following are deliberately **not committed**:

- live GLM raw prompt or answer;
- live Ornith raw prompt, answer, or reasoning;
- provider HTTP bodies;
- credential values;
- temporary live result JSON files.

Committed P7 assets contain only the reproducible runner, deterministic adversarial tests, and this qualification report. Live result identity is preserved by SHA256 plus mechanical aggregate facts.

## 8. Gate status

| Gate | Verdict |
|---|---|
| A — deterministic/unit | PASS |
| B — focused integration / ownership boundaries | PASS |
| C — static/security/full CI | PASS |
| D — GLM + Ornith + adversarial + lifetime/cache observations | PASS |
| E — official canary / promotion | **NOT RUN — owner authorization required** |

No push, tag, service restart, deployment, or promotion action is part of this P7 local qualification commit.
