# SMC Browser MF-5.3 — Deterministic Implementation Result — 2026-09-16

## 1. Status

**MF-5.3 deterministic implementation: QUALIFIED.**

**Live measured qualification: PENDING.**

**MF-6: DEFERRED.**

This result qualifies only the deterministic implementation contract and repository regression state. It does **not** claim that Ornith behavior is stable, that the live task Gate passes, or that the interface is ready for merge/deploy.

Final deterministic implementation HEAD:

`d415daa048ce8c96eddefe4fb06b1d996673e0d4`

No push, deploy, service restart, production cutover, or live model qualification was performed by this phase.

---

## 2. Architecture that is now mechanically true

MF-5.3 implements **Cognition-Preserving Semantic Actuation** as two normal Browser capabilities:

### `browser_perceive` — the eye

Provider-facing actions:

- `snapshot`
- `hydrate`
- `diff`
- `wait`

Provider-facing natural wait classes:

- `page_ready`
- `page_url`
- `object_state`
- `object_text`

Page waits mechanically bind the already host-bound page. Object waits require an exact previously observed `object_ref`. Runtime owns the default bounded timeout and polling cadence. The model does not provide `interval_ms`, fabricate a `scope_ref`, or select among pages.

### `browser_semantic_operation` — the hand

Provider-facing mutation verbs:

- `navigate`
- `click`
- `set_text`
- `append_text`
- `select`
- `scroll`

The normal form is **one already-decided mutation per call**. The provider contract has no `steps` wrapper and exposes no `wait`/`wait_text` branch.

Historical `steps` / legacy `clauses` execution remains as internal compatibility machinery so frozen MF-1..MF-5.2 evidence stays reproducible. It is not the normal provider-facing cognitive surface.

---

## 3. Actual Registry visibility

A final post-Gate audit found that class-level schemas were not enough: Factory still registered five typed wait tools plus `browser_action` and `browser_semantic_execute` as normal tools. That would have left the model with nine Browser concepts even though Perceive/Operate themselves were correct.

This was frozen by Factory-level RED at:

`1b74f609432fdd1eb0be3d9f9c45e1e92fd64b10` — `test(smc): freeze two-capability browser registry surface`

and fixed at:

`d415daa048ce8c96eddefe4fb06b1d996673e0d4` — `feat(smc): expose only perceive and operate browser capabilities`

Final Browser Registry contract:

| Browser mode | Normal provider-visible Browser tools |
|---|---|
| perception enabled, writes disabled | `browser_perceive` |
| perception enabled, writes enabled | `browser_perceive`, `browser_semantic_operation` |

Low-level mechanical classes remain in code:

- typed wait executors;
- `BrowserActionAdapter` / receipt store;
- `BrowserSemanticExecuteTool`;
- typed Predicate engine;
- exact perception / version / grounding machinery.

They are implementation dependencies, not separate normal cognitive concepts. `browser_wait_scope_count` remains available in code as a mechanical primitive but is intentionally not part of the current MF-5.3 provider facade.

---

## 4. Perceive tranche

Commit:

`dd0b697c6482ccf086620b61712c0a190250c60e` — `feat(smc): add cognition-preserving perceive wait facade`

Key properties:

- wait moved to read-only perception;
- `page_ready` / `page_url` use the unique host-bound page rather than a fabricated object identity;
- object state/text waits require exact observed refs;
- runtime owns polling mechanics;
- no navigation/mutation/fuzzy/latest/rebind/retry/task-completion authority;
- old procedural Method Card teaching was removed from Perceive.

A later metadata correction restored only the progressive-disclosure Method ref:

`e83807a61d0c0576663bfd4a968ba0e30ade792c` — `fix(smc): keep method ref without perception protocol`

Perceive now carries `method_ref=method:method-semantic-operation` without reintroducing `Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify` or naming low-level `browser_semantic_execute` in its normal stable-prefix guidance.

---

## 5. Operate tranche

Commit:

`3597b4f831ba239df51f7df8f6f8d9e4afc41626` — `feat(smc): make semantic actuation direct and mutation-only`

Key properties:

- direct root single-action provider wire;
- mutation-only provider verbs;
- no provider `steps:[single]` wrapper;
- no provider wait grammar;
- existing exact grounding/version guard/action-id/single-dispatch executor reused;
- no fuzzy/best-match/auto-target/latest/rebind/retry/completion judgment.

Historical compatibility surface is explicitly frozen as `_HISTORICAL_STEPS_PARAMETERS`, preserving old deterministic evidence without teaching the old grammar to the model.

---

## 6. Compact delta tranche

Commit:

`31376dc1fb0d05b46ab411922d5dad84e57bf572` — `feat(smc): expose compact semantic delta sufficiency`

After a successful mutation, the action adapter already post-captures and persists an exact canonical diff. MF-5.3 does **not** capture again. The compact semantic-operation result exact-hydrates that already-persisted diff and exposes bounded mechanical facts:

- `ref`
- `comparable`
- `scope_relation`
- `complete`
- bounded reason codes
- created/removed/changed counts

If exact diff hydration unexpectedly fails, the compact result exposes incomplete/unknown evidence state rather than hiding the failure.

These facts never mean “the task succeeded”. `task_completion` remains `not_evaluated`.

The resulting observation ladder is:

```text
operate
  -> compact local delta
  -> exact hydrate already-captured diff/receipt when more local evidence is needed
  -> fresh snapshot only when world/scope evidence is incomplete/changed
     or the model semantically needs broader current context
```

---

## 7. Deterministic RED -> GREEN evidence

Primary MF-5.3 cognition contract RED:

`29884118a9cf9411ab85cad2e2cb7b5ceefe6ae6` — `test(smc): freeze MF5.3 cognitive contract`

Initial state:

- 8 expected RED;
- 2 existing hard-boundary PASS.

The REDs mapped to:

- Perceive wait / no low-level protocol teaching: 3;
- direct mutation-only Operate: 3;
- compact delta sufficiency: 2.

After the three implementation tranches, the MF-5.3 focused contract reached **12/12 GREEN**.

A second RED was required when final Factory visibility inspection found the hidden nine-tool exposure:

`1b74f609432fdd1eb0be3d9f9c45e1e92fd64b10`

The three Factory visibility assertions were RED against the prior implementation and GREEN after `d415daa0`.

---

## 8. Regression evidence

### Browser unit surface

Exact final HEAD `d415daa0`:

- all `test_browser*.py` + `test_smc_browser*.py`: **298/298 PASS**;
- `tests/unit/test_factory.py`: **24/24 PASS**;
- Factory production Ruff: PASS;
- Factory targeted Pyright: **0 errors / 0 warnings / 0 informations**;
- `git diff --check`: PASS;
- staged security scans for each implementation/follow-up commit: PASS.

### Full non-real-LLM Gate

Exact final HEAD:

`d415daa048ce8c96eddefe4fb06b1d996673e0d4`

Command:

```text
PYTHONPATH=src <common-repo>/.venv/bin/python -m pytest tests -q -m 'not real_llm'
```

Result:

- exit code: **0**;
- completed to 100%;
- `FAILED`: **0**;
- `ERROR`: **0**;
- elapsed: approximately **230.6 s**.

No live provider/model request is part of this Gate.

---

## 9. Supporting regression/test maintenance

Two non-product defects/contract migrations surfaced during the broader Gate and were isolated rather than hidden inside feature commits:

- `a2775aba` — align stale perception provider-contract tests with the MF-5.3 facade;
- `984264fa` — isolate historical Browser recovery runner `protocol` imports so multiple eval packages cannot alias the same top-level module inside one pytest process.

The latter was a test/harness isolation bug, not Browser runtime behavior.

---

## 10. Final provider surface identity

At exact final HEAD `d415daa0`, serializing the two registered provider schemas with sorted compact JSON gives:

### Lazy surface

- names: `browser_perceive`, `browser_semantic_operation`;
- chars: **4,054**;
- SHA256: `b2549e11adb78ca1cd1e7bb252d0ef928e0171fe1cc2c7918706c499f4e24017`.

Individual lazy surfaces:

- `browser_perceive`: 679 chars, SHA256 `81e8b1489c4761f5cc6a8274c750302fe8405357519801025e0980ea056fed23`;
- `browser_semantic_operation`: 3,372 chars, SHA256 `039dcc8b53d556e5af46a19a5d55058a30f2e0be22f2d76f8fd2826870e9e878`.

### Full surface

- chars: **5,827**;
- SHA256: `46665de3bdf8ab0774981084fccced86676620fdc3cf969df737137f94823563`.

The read-only audit's ~3,560-char two-tool number was explicitly a design estimate. The implemented exact lazy surface is 4,054 chars. No qualification conclusion depends on beating that estimate.

---

## 11. Authority boundary after implementation

The implementation preserves the architecture ruling.

Program may:

- observe the already host-bound page;
- exact-hydrate emitted refs;
- mechanically bind the host-bound page for page wait;
- compile closed wait aliases;
- own bounded polling cadence/default timeout;
- exact-unique ground an explicitly declared object identity;
- check version/staleness;
- dispatch one declared mutation once;
- post-capture, diff, persist evidence;
- expose bounded comparability/completeness/boundary facts.

Program may not:

- choose a fuzzy/best target;
- choose among pages/frames for the model;
- silently latest/rebind;
- auto-retry/replay a mutation;
- infer task relevance/success/completion;
- decide that a compact delta semantically answers the task;
- use a failed wait/ground as authority to mutate.

The model still decides what the task means, what it needs to perceive, which action is intended, whether evidence is semantically sufficient, and whether the task is complete.

---

## 12. Next qualification boundary

MF-5.3 deterministic implementation is now frozen. The next work is **not** another implementation patch and **not** MF-6.

The next qualification identity should expose the actual two-capability surface to Ornith:

- `browser_perceive`;
- `browser_semantic_operation`;
- only the non-Browser support tools explicitly frozen by the qualification protocol.

It should preserve the same no-replay/no-mid-run-patch discipline and measure at least:

- external task oracle;
- first meaningful Browser call validity;
- protocol/schema repair;
- full snapshot / exact hydrate / wait usage;
- local-delta -> hydrate -> snapshot escalation;
- target-not-found / grounding-probe amplification;
- duplicate successful mutation count;
- low-level hidden Browser-tool calls = 0;
- auto mutation retry/replay = 0;
- runtime task completion judgment = 0;
- rounds/tokens/cache as diagnostics, not correctness substitutes.

Before any measured model row, freeze a fresh qualification plan/manifest, perform a **zero-model preflight**, and cross a human checkpoint.

MF-6 remains deferred until this new cognition-preserving treatment hard-passes.
