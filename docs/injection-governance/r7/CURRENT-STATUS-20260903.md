# R7-v1 current status — historical diagnostic, not model governance

Date: 2026-09-03

## Decision

R7-v1 is retained as a **frozen historical injection-morphology diagnostic**. It is no longer an authority for:

- model `strong/weak` classification;
- primary-model admission or rejection;
- fallback capability floors;
- model-specific injection density;
- production defaults such as `REFERENCE_AUTO_TURNS`.

A failure on R7-v1 must not be interpreted as evidence that a model is weak. A pass must not promote a model to strong.

## Why the old interpretation was invalid

1. The runner mixed a mutable production `build_system_prompt()` into a supposedly frozen fixture. On Ornith, with the same R7-B payload and sampling parameters, the old live LFL system prompt completed **1/6**, while the fixture's own frozen short prompt completed **6/6**. The previous result therefore measured LFL prompt interference as model weakness.
2. R7-v1 calls an OpenAI-compatible chat endpoint directly. It does not exercise the current `LoopEngine`, actual tool discovery/execution, provider recovery lifecycle, compact/retrieval behavior, or current task-state machinery.
3. The A arm intentionally replays broken/polluted LFL prompt shapes. Resilience to LFL-created pollution is useful diagnostic evidence, but it is not a model capability requirement. LFL should remove the pollution rather than require every model to survive it.
4. The legacy `user_dominance_rate` is not an independent dominance measurement; for selected fixtures it is effectively derived from exact task completion.
5. The legacy mean `injection_share <= 0.20` threshold has no independent risk proof. It must not become a hard semantic gate.
6. The B arm's `hard_gate_pass` still permits program-origin reference text and exact user truth to be concatenated into one provider `role=user` envelope. Labels such as `[程序附录·非用户输入]` are visible text, not protocol-level provenance isolation. Therefore `hard_gate_pass` is a legacy morphology check, not proof of semantic separation.
7. The old T6/K=3 calibration used a synthetic tool-less memory dependency to justify blanket early-turn replay. Current LFL has retrieval/hydration capabilities and an agency-first rule: information that can be retrieved on demand does not gain automatic prompt-write authority merely because it was once relevant.
8. After freezing the runner to its own fixture prompt, the 2026-09-03 Ornith rerun produced **A=6/6, B=6/6, drift=0**. The deprecated composite gate still evaluated false because the shorter system prompt made `mean_injection_share` 72.54%, above the old 20% threshold. This is a pathological metric: padding unrelated system text would mechanically reduce the ratio without improving task behavior. The composite threshold therefore has zero current authority.

## What remains useful from R7

The frozen fixture may continue to detect regressions in historical morphology and compare prompt-interference sensitivity. The following invariants remain useful when they represent real provider/runtime facts rather than model policy:

- exact current user bytes are not rewritten or silently dropped;
- stale historical commands are not automatically replayed as current executable instructions;
- duplicate reference bodies are suppressible/retrievable by stable reference;
- assistant/tool protocol pairing and provider wire integrity remain runtime responsibilities;
- audit/storage truth remains retrievable even when it is not prompt-visible.

These are implementation properties of LFL. They do not justify a model strong/weak scalar.

## Current defaults / migration

- Universal system prompt: minimal static identity/responsibility boundary; no operator playbook, rule-read SOP, provider-wire workaround, retry count, archive SOP, or completion heuristic.
- `SYSTEM_PROMPT_EXTRA`, `LFL_SYSTEM_EXTRA_BUNDLE`, and `build_system_prompt(extra=...)`: no universal prompt-write authority.
- `REFERENCE_AUTO_TURNS=0` by default. `>0` is explicit compatibility/experiment opt-in only.
- **P1-B supersession (2026-09-04):** `TOOL_ELIGIBILITY_MODE` / promotion / capability-selection modes are retired. The fixed provider surface is all registered healthy tools; only mechanical runtime-health and explicit delegated-scope boundaries may reduce it. No shadow/enforce selector remains.
- P1-B live verification: GLM-5.3 / DeepSeek V4 Flash / MiniMax-M3 = 3/3 PASS; direct `model_catalog` works before schema lookup, lookup does not mutate later surface; current mirror registry=62, callable=60, Playwright pair quarantined by real runtime health; selector events=0. Evidence: `data/audit/p1b_tool_authority_live_canary_20260904.json`.
- R7-derived capability tiers have been invalidated. `unknown` means no conclusion and must not be treated as weak.
- R7 K/budget calibration is off by default in the runner; historical calibration requires explicit `--legacy-calibration`.
- Capability floor may reject only a model with affirmative independent `weak` evidence; unknown fails open.
- Model tier no longer maps to minimal/standard/full injection density. **P1-C (2026-09-04) retired the runtime Injection Profile recommendation/emitter entirely; historical `injection.profile.shadow` schema is read-compatible only.**

## Replacement evaluation doctrine

Do **not** replace R7-v1 with another broad hard behavior gate. New model evaluation should separate concerns:

1. **Protocol / integrity hard checks** — valid tool-call/result pairing, provider wire validity, data integrity, bounded real side effects, authorization/safety boundaries.
2. **LFL interference A/B** — compare a minimal stable contract against production assembly. If production assembly materially worsens behavior, treat it first as an LFL regression, not model weakness.
3. **Real agent capability measurements** — actual tool discovery/selection/execution, multi-step task completion, error recovery, long-session operation, compact/retrieval, truthfulness, and cache/runtime behavior on the real agent path.
4. **Safety/authorization checks** — independently scoped; they must not be expanded into task strategy or completion arbitration.
5. **Pollution resilience** — diagnostic only. A model may be robust to bad context, but LFL is not entitled to feed bad context merely because some models can withstand it.

Any future hard semantic gate or negative model classification carries reverse burden of proof: concrete recurring harm, evidence that the model/native protocol cannot handle it, and proof that the proposed program restriction is the smallest effective scope.
