# SMC Model-Friendly Semantic Operation — Execution Plan — 2026-09-16

Status: **MF-5 v0.1 NOT QUALIFIED / MF-5.2 IMPLEMENTED + ZERO-MODEL PREFLIGHT PASS / MEASURED LIVE PENDING / MF-6 DEFERRED**

Design authority: `docs/SMC-MODEL-FRIENDLY-SEMANTIC-OPERATION-DESIGN-v0.1-20260916.md`

Baseline: `lfl/main@2c4b9b087f5d2fad2cf2c5c026194038c7613c5c`

## 1. Work order

| Order | Work package | Change class | Required output | Stop condition |
|---:|---|---|---|---|
| 0 | MF-0 Interface Tax Audit | read-only | **COMPLETE** — audit report + frozen baseline metrics | unresolved authority ambiguity |
| 1 | MF-1 deterministic RED | tests only | **COMPLETE** — RED contract suite | proposed wire cannot preserve exact/fail-closed boundary |
| 2 | MF-2 narrow input compiler | production, narrow | **COMPLETE** — short semantic grammar -> existing qualified primitives | backend semantic behavior would need changing |
| 3 | MF-3 compact result projection | production, narrow | **COMPLETE** — compact projection + exact evidence refs | any evidence becomes non-recoverable |
| 4 | MF-4 Decision Boundary enforcement | production + tests | **COMPLETE** — explicit declared/undeclared transition boundary | boundary cannot be mechanically determined |
| 5 | MF-5 local A/B | qualification | **COMPLETE / NOT QUALIFIED** — efficiency PASS, hard gate FAIL | gate failure |
| 5.1 | MF-5.1 grammar regularization | narrow production + deterministic tests | **IMPLEMENTED at `d6ec0113`** — uniform `do`, including `do:"wait"` | any authority change beyond syntax |
| 5.2 | Cognition-preserving actuation qualification | design + qualification | **IMPLEMENTED + ZERO-MODEL PREFLIGHT PASS** — natural actuation surface, observable protocol-repair Gate; fresh 6-row measured live still pending | model still reasons about tool grammar |
| 6 | MF-6 independent confirmatory | qualification | **DEFERRED** until MF-5.2 hard PASS; fresh repeat, no pooling | gate failure |
| 7 | MF-7 portability/wider matrix | later | provider + broader tasks | local repeat stability not proven |

## 2. Parallelism rules

Do not run MF-2/3/4 in parallel before MF-1 freezes the contract. They touch the same model-facing authority boundary and parallel changes would make causal attribution weak.

MF-0 may collect measurements from existing FC2-C/FC2-B/semantic-execute traces without changing runtime.

No Vision or OS work is opened by this plan.

## 3. Release / Git discipline

- use an isolated worktree/branch from formal `lfl/main`;
- no production restart/deploy during MF-0/MF-1;
- implementation commits must stay separable by input compiler / output projection / boundary enforcement;
- qualification evidence must identify exact Git SHA and frozen fixture hashes;
- local green is not “stable”; require independent repeat;
- push/review/deploy follows normal LFL owner-controlled review process after local committed-state qualification.

## 4. Metrics to freeze in MF-0

Correctness/safety:

- external task oracle;
- first-call validity;
- exact target count behavior;
- stale/version blocker behavior;
- mutation replay/retry count;
- fuzzy/auto-target/rebind/latest count;
- boundary halt behavior;
- runtime task-completion judgment count.

Efficiency:

- model tool calls;
- model-visible results;
- explicit snapshots;
- explicit hydrates;
- `get_tool_schema`;
- serialized tool argument chars;
- serialized model-visible tool result chars;
- input/new-prefill tokens if available;
- cache hit tokens/rate if available;
- internal capture/poll counts, reported separately;
- SRTA for each frozen task.

## 5. Current human ruling encoded by this plan

The semantic operation surface must be designed for the model, not for internal API symmetry. The controlling rule is now **Cognition-Preserving Semantic Actuation**: do not make the model adopt a new thought format in order to use semantic operations.

Preferred optimization order:

```text
preserve native task reasoning
  -> expose natural action concepts at the moment of actuation
  -> remove redundant model fields
  -> remove duplicate model-visible observations
  -> compact success receipts with exact hydration
  -> batch only actions the model has already decided, when batching is natural
  -> halt exactly at semantic decision boundaries
```

Never invert that order by teaching a mandatory Semantic DSL/planning style or by adding more automatic strategy.


## 6. MF-5 v0.1 evidence update — 2026-09-16

Authoritative result: `docs/SMC-BROWSER-MODEL-FRIENDLY-MF5-v0.1-RESULT-20260916.md`.

MF-5 closed **NOT QUALIFIED** under the frozen Gate. The treatment nevertheless produced a strong efficiency signal: support calls -40.0%, model-visible operation chars -63.0%, input tokens -36.7%, output tokens -31.0%, rounds -11.1%, and task oracle 5/6 vs A 3/6. Safety invariants remained intact.

The dominant treatment failure is now specific rather than diffuse: 25/29 B contract failures are `short_operation_not_supported`, caused by the asymmetry between `do=...` mutations and the special top-level wait form. MF-5.1 therefore changed syntax only: one uniform `do` discriminator including `do:"wait"`; this is now implemented at `d6ec0113`. It did not add fuzzy target selection, target inference, retry/rebind, automatic latest/snapshot, or program task completion.

However, the user architecture ruling adds a higher bar: syntax regularity is necessary but not sufficient. MF-5 evidence contains repeated **protocol-induced reasoning** in which the model stops advancing the task and instead reasons about how the Semantic Operation grammar might work. MF-5.2 must therefore qualify cognition-preserving actuation, not merely grammar compliance.

MF-5.2 requirements:

- preserve ordinary model task reasoning; no mandated semantic-operation planning template;
- a semantically correct model decision must map to a natural tool-local call without schema guessing;
- classify turns as `task_reasoning`, `actuation_call`, `protocol_repair`, `evidence_inspection`;
- treatment target: `protocol_repair = 0` across the frozen task set;
- one-action calls are first-class; MDEH batching is optional and only for already-decided actions;
- runtime still owns exact grounding/version/polling/single-dispatch/receipt mechanics;
- no fuzzy/best-match/auto-target/latest/rebind/retry/task-completion authority.

MF-6 is explicitly deferred; do not run it until MF-5.2 hard qualification passes.


## 7. MF-5.2 implementation + zero-model preflight update — 2026-09-16

The cognition-preserving correction is now mechanically implemented and frozen for live qualification.

Implementation layers:

- `8273c11c` — common wait model surface becomes `do + exact target + until`, `within_ms` optional; deterministic compiler expands common state aliases to the existing typed Predicate path; `wait_text` preserves `name/value_text` comparison capability without exposing the generic Predicate bookkeeping on the common path.
- `ab99aac3` — provider **lazy stable-prefix** contract aligned with the same cognition-preserving semantics. This follow-up was required because `ToolRegistry.schemas(lazy=True)` uses `_COMPACT_TOOL_DESCRIPTIONS`, not the tool's full description. The stale lazy string still said `1..8 ordered steps / typed condition+within_ms`; a new RED test reproduced this and the compact string was fixed without changing execution behavior.

Deterministic qualification:

- MF1→MF5.2 semantic-operation chain: PASS;
- cognition-preserving focused tests: PASS;
- MF-5.2 Gate synthetic positive/negative suite: PASS;
- Ruff PASS; targeted Pyright 0 errors / 0 warnings; security scans PASS.

Frozen MF-5.2 harness: `evals/browser_smc_cognition_preserving_actuation_mf52/`. The release Gate does not inspect hidden chain-of-thought. `protocol_repair` is an observable proxy over semantic-operation contract failures plus schema lookup on this already-known surface.

Zero-model preflight at experiment HEAD `6e13c04ef7356eb6b0651cdf230b46e56610c4bc` and implementation `ab99aac3d6287a485f4d45646287242bc6a6ab07` passed with **model_requests=0**:

- plan SHA: `81fe0e21ffc511f3894f246c80423b2c9c014f86e450b74c2d40c614a4bceefe`;
- provider surface SHA: `106e302dac1f099594072cb76cfd26d7bd1a6961d61c5e615224c1e13b75aa6c`;
- model-visible tools: exactly `browser_semantic_operation`, `get_tool_schema`, `read_evidence`;
- provider root: `steps`; canonical branches include `wait` and `wait_text`;
- cognition-preserving lazy contract marker check: PASS;
- unique local model: Ornith on 8901, prompt/decode concurrency 1/1, max tokens 16000; no second local model started.

The next step is the fresh six-row treatment-only Ornith matrix. It is a major measured qualification boundary and must not begin until the explicit human checkpoint is crossed. No row may be replayed or repaired in place.

## 8. MF-5.2 v0.2 formal result — 2026-09-16

Authoritative report: `docs/SMC-BROWSER-COGNITION-PRESERVING-ACTUATION-MF5.2-v0.2-RESULT-20260916.md`.

MF-5.2 v0.2 closed **NOT QUALIFIED** under its frozen Gate. Infrastructure and all hard mechanical safety boundaries were valid, but external task correctness was 3/6 and cognition-preserving interaction did not stabilize:

- first operation contract-valid 5/6;
- 18 operation contract failures, of which 16 were `short_target_fields_mismatch` from scope/document waits being forced through an object-target surface;
- 20 observable protocol-repair episodes;
- 14 additional valid-syntax `target_not_found` halts;
- 53 semantic-operation calls over 72 rounds;
- 52 recognized single-action calls, zero multi-action calls;
- delayed_wait r2 failed despite protocol_repair=0;
- click_commit r2 repeated a successful click and ended at `commit_count=2`.

This closes MF-5.2. Do not patch/rerun it in place and do not start MF-6.

### MF-5.3 work order

MF-5.3 starts **read-only**. Before any new production code:

1. audit the existing `browser_perceive` provider surface and identify the minimum model-facing perception contract needed for unknown-world understanding and post-action verification;
2. audit replacing mandatory `steps:[single_action]` with a direct single-action normal form; keep batching only as an optional already-decided horizon;
3. define natural page/scope waits (for example readiness/URL state) that compile mechanically to existing scope Predicate primitives rather than fake document objects;
4. define the boundary between compact local actuation delta and explicit model-visible perception;
5. pre-register next qualification metrics, including target-not-found / grounding-probe amplification as a diagnostic, without weakening exact fail-closed grounding.

No production implementation begins until this architecture audit is reviewed.

## 9. MF-5.3 read-only architecture audit — 2026-09-16

Authoritative audit: `docs/SMC-BROWSER-MF5.3-READ-ONLY-ARCHITECTURE-AUDIT-20260916.md`.

MF-5.3 read-only audit is complete with no production change. The architecture ruling is now: **perception and actuation are peer capabilities; wait belongs to perception; one already-decided mutation should have a direct single-action normal form; action results should expose a bounded local delta and exact refs, with escalation to hydrate or fresh snapshot only when mechanically/semantically needed.**

Current implementation already contains the required mechanical substrate (`browser_perceive`, exact snapshot/hydrate/diff, typed waits, version guards, post-action capture/diff, single-dispatch receipts). The next phase is interface composition, not a new Browser engine.

MF-6 remains deferred. No RED or production implementation may begin until the MF-5.3 architecture checkpoint is explicitly crossed.

## 10. MF-5.3 deterministic implementation result — 2026-09-16

Authoritative result: `docs/SMC-BROWSER-MF5.3-DETERMINISTIC-IMPLEMENTATION-RESULT-20260916.md`.

MF-5.3 deterministic implementation is **QUALIFIED** at exact HEAD `d415daa048ce8c96eddefe4fb06b1d996673e0d4`; live measured qualification remains pending.

Implemented sequence:

1. `29884118` — cognition-preserving deterministic RED;
2. `dd0b697c` — Perceive wait facade;
3. `3597b4f8` — direct mutation-only Operate;
4. `31376dc1` — compact delta sufficiency;
5. `a2775aba` — perception contract test alignment;
6. `984264fa` — historical eval protocol import isolation;
7. `e83807a6` — progressive method ref without Perceive protocol teaching;
8. `1b74f609` — Factory two-capability visibility RED;
9. `d415daa0` — Factory exposes only `browser_perceive` and `browser_semantic_operation`.

Final deterministic evidence:

- MF-5.3 focused cognition contract: 12/12 GREEN;
- all Browser unit tests: 298/298 PASS;
- Factory unit tests: 24/24 PASS;
- Ruff PASS; targeted production Pyright 0/0; security and diff-check PASS;
- full `pytest tests -q -m 'not real_llm'`: exit 0, 0 FAILED / 0 ERROR;
- actual two-tool lazy provider surface: 4,054 chars, SHA256 `b2549e11adb78ca1cd1e7bb252d0ef928e0171fe1cc2c7918706c499f4e24017`.

The next phase is a fresh MF-5.3 measured qualification identity. First freeze its plan/manifest and run zero-model preflight; do not start measured Ornith rows until the next human checkpoint. MF-6 remains deferred.

## 11. MF-5.3 v0.1 formal measured result — 2026-09-16

Authoritative report: `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3-v0.1-RESULT-20260916.md`.

MF-5.3 v0.1 closed **NOT QUALIFIED** under the frozen hard Gate, but external task correctness reached **6/6**: click 2/2, fill 2/2, delayed-wait 2/2. The previous MF-5.2 failure classes were eliminated: Operate failures 0, Grounding Probe Amplification 0, duplicate successful mutations 0, schema lookups 0, and all mechanical safety boundaries remained intact.

The sole hard-Gate failure class is now Perceive contract repair: **8 browser_perceive failures**. Six are natural waits whose nested `condition` was emitted as a JSON string rather than an object; two are hydrate calls that carried the snapshot-only `projection_limit` field. This is a model-facing wire-shape problem, not a reason to weaken fail-closed validation.

The next identity is therefore **MF-5.3.1**, starting with deterministic RED for a root-direct Perceive schema: action-discriminated closed branches, wait fields flat at the root, and no cross-action fields. Low-level typed waits remain internal. After deterministic qualification, run a fresh measured identity. **MF-6 remains deferred.**

## 12. MF-5.3.1 deterministic implementation — 2026-09-16

Authoritative result: `docs/SMC-BROWSER-MF5.3.1-DETERMINISTIC-IMPLEMENTATION-RESULT-20260916.md`.

MF-5.3.1 root-direct Perceive regularization is deterministically complete at `1cb9ad2b`. The measured MF-5.3 failure taxonomy was translated directly into RED before implementation: nested `condition` and cross-action field leakage are removed from the provider contract, while fail-closed validation and all Browser authority boundaries remain unchanged.

The model-facing Perceive grammar is now seven closed root branches: snapshot, hydrate, diff, and four flat wait forms (`page_ready`, `page_url`, `object_state`, `object_text`). Lazy and full provider schemas carry the same branches; `interval_ms` remains runtime-owned. Historical nested-condition calls remain executable only as an internal compatibility path and are absent from provider surface.

Committed-state deterministic qualification is green: focused 30/30, Browser 316/316, Factory 24/24, Ruff/Pyright clean, security/diff-check PASS, and the full non-real-LLM test Gate exits 0 with no failures/errors.

Next phase is a **fresh MF-5.3.1 measured identity**, not reuse of MF-5.3 v0.1 evidence. Freeze protocol + manifest, run zero-model preflight, and stop at the human checkpoint before any model request. MF-6 remains deferred.


## 13. MF-5.3.1 v0.1 formal measured result — 2026-09-16

Authoritative report: `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3.1-v0.1-RESULT-20260916.md`.

MF-5.3.1 v0.1 closed **NOT QUALIFIED** under its frozen Gate. Infrastructure and hard Browser safety remained valid, and the intended old Perceive wire failures disappeared, but external task correctness was 5/6. Observed Gate failures: Perceive failures/protocol repairs=3, first Browser call valid=3/6, Grounding Probe Amplification=1, task pass=5/6. Operate failures/errors, schema lookup, duplicate successful mutation, hidden atomic calls, auto retry, completion authority and boundary continuation all remained zero.

The remaining failure classes are new:

1. **capability routing:** navigation was sent to Perceive on first call in two rows; a third row used snapshot+URL;
2. **perception salience / identity choice:** `fill_submit-r2` selected a generic `Save code` AX text identity even though an enabled complete button identity was present; exact grounding correctly halted on two generic matches, after which evidence inspection exhausted the 12-round horizon.

### MF-5.3.2 work order

Start read-only. Do not change production yet.

1. audit provider tool names/order/compact descriptions for natural Perceive-vs-Operate routing, especially navigation, without teaching a thought protocol;
2. audit snapshot projection/object fusion/order so complete actionable parents are mechanically legible alongside AX text descendants while preserving exact evidence;
3. inspect evidence paging/round amplification only after the first two causes are bounded; do not use a larger iteration budget as the primary remedy;
4. preserve exact/fail-closed grounding, no fuzzy/best-match, no automatic target substitution/retry, and no task-completion authority;
5. only after the audit, freeze deterministic RED for the minimal next correction.

MF-6 remains deferred.


## 14. MF-5.3.2 read-only interface audit — 2026-09-16

Authoritative audit: `docs/SMC-BROWSER-MF5.3.2-READ-ONLY-INTERFACE-AUDIT-20260916.md`.

The audit is complete with **no production/test/provider/runtime change**. It separates two next corrections:

1. **MF-5.3.2A capability identity:** deterministic RED for one natural provider-visible eye/hand pair (preferred `browser_perceive` + `browser_operate`), navigation only on the hand, wait only on the eye, no duplicate old/new hand names, no routing decision tree;
2. **MF-5.3.2B evidence-quality projection:** deterministic RED for task-independent model-facing ordering by completeness/identity stability while preserving the canonical full object set, exact refs, hydration, fail-closed grounding and model choice.

Read-only evidence shows current object order is opaque Semantic ID order and generic tool Evidence uses a 5K 60%-head/40%-tail excerpt. In Row5 the partial AX `Save code` InlineTextBox was visible at the beginning while the complete enabled button was in the omitted middle. Across 63 frozen snapshots, current actionable index median=11 / mean=10.62 / max=24; complete+stable mechanical ordering yields median=1 / mean=1.52 / max=4, with all 73 actionable instances inside top5.

Do not yet implement global Evidence-budget changes, compact Browser cards, AX lineage/fragment merging, iteration-limit increases, fuzzy target repair or auto retry. Those are deferred until the narrow corrections are qualified.

Next phase requires a human checkpoint before any RED or production edit. MF-6 remains deferred.


## 15. MF-5.3.2 deterministic + measured result — 2026-09-16

Authoritative report: `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3.2-v0.1-RESULT-20260916.md`.

Implemented and qualified deterministic sequence:

1. A RED `7723a271` -> A provider peer identity `dfca4c95`;
2. B RED `5da9d8a8` -> B evidence-quality projection `05d0f36c`;
3. Browser/Factory 363/363 PASS; full non-real test Gate 100% exit 0; Ruff/Pyright/security/diff checks green;
4. fresh measured protocol `5dffb6b3`, identical 6-row tasks/prompts/fixture/oracles/hard Gate;
5. zero-model preflight PASS;
6. fresh six-row live treatment completed without selective replay.

Formal result: **NOT QUALIFIED**. External oracle is 6/6 and Grounding Probe Amplification is 0, but one task-correct row hit the frozen 240s worker timeout and four completed rows still contain first-call Perceive routing repair.

Do not rerun this identity, loosen the Gate, raise max iterations, add navigation to Perceive, fuzzy-resolve targets, or proceed to MF-6. The next phase is a read-only audit of (a) capability routing after peer naming and (b) post-success verification/evidence amplification. Production changes require a new deterministic identity after that audit.
