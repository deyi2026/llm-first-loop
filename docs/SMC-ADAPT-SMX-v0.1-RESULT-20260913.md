# SMC-ADAPT-SMX v0.1 Result — 2026-09-13

> Contract: `docs/SMC-CONTRACT-v0.1.md`
> Historical baseline: `docs/SMC-CONFORMANCE-v0.1-20260912.md`
> Adaptation code tip: `79156fb5` (`feat(smc): project canonical SMX observations`)
> Nature: **post-A/B mechanical contract adaptation result**. This report does not replace or rewrite the 2026-09-12 baseline.

## 1. Decision boundary

The implementation order was changed after the completed SMX focused v1.2 A/B from the pre-experiment `P7 → P4 → P2` order to:

**P4 → P7 → P2 → P8 → P5 → P0**

The reason was empirical uptake, not contract weakening: wait/predicate was adopted in 5/6 focused ON wait runs and mechanically removed explicit sleep polling, while diff was adopted in 0/3 focused ON diff runs. Diff correctness remained normative work, but Predicate/wait had the strongest implementation ROI.

Throughout this adaptation:

- SMX remained opt-in;
- `smx_perceive` stayed perception-only; command execution remained on LFL's existing execution path;
- no semantic tool routing, task-value judgment, completion judgment, silent retry, or auto-recovery was added;
- no new model matrix was run;
- the already published SMX focused v1.2 result remains historical behavioral evidence for the **pre-adaptation** treatment.

Any future behavioral qualification of the code below requires a newly versioned protocol/freeze; it must not be called a rerun of SMX focused v1.2.

## 2. Baseline → post-adapt matrix

The historical R1 baseline was **3 PASS / 6 GAP / 0 FAIL**. After this adaptation, the same measured P0–P8 probe set is **9 PASS / 0 GAP / 0 FAIL**.

This is **not a maturity score** and does not mean “SMC is 100% complete.” It means only that the nine currently mechanical Domain-0 probes now satisfy their frozen v0.1 acceptance semantics.

| Probe | 2026-09-12 | 2026-09-13 | Commit | Mechanical evidence |
|---|---|---|---|---|
| P0 canonical contract surface | GAP | **PASS** | `79156fb5` | legacy tool envelope preserved; nested canonical WorldSnapshot / SemanticDiff / wait ActionReceipt+Predicate added; raw receipt remains noncanonical |
| P1 complete diff fidelity | PASS | **PASS** | baseline + regression | same-scope complete snapshots still expose true create/remove/change facts; canonical field completeness is all true |
| P2 incomplete diff field completeness | GAP | **PASS** | `eeee6a7b` | created/deleted/total stay unknown under incomplete observation; observed modified facts are explicit non-exhaustive lower bounds |
| P3 blind-spot honesty | PASS | **PASS** | baseline + regression | missing root, budget truncation, lstat/walk errors remain explicit mechanical facts |
| P4 Predicate honesty | GAP | **PASS** | `af87c8c1` | satisfied/unsatisfied/indeterminate tri-state; capped negative and observer error are indeterminate; polling sample/error facts exposed |
| P5 snapshot hydration + integrity | GAP | **PASS** | `b780b4d6` | new snapshots carry independently recomputable `content_sha256`; tampered stored observation is rejected |
| P6 running honesty | PASS | **PASS** | baseline + regression | running is still not terminal; no completion/diff is fabricated while async work is running |
| P7 diff scope comparability | GAP | **PASS** | `5114326b` | capture-time roots/depth scope bound to snapshot; incompatible scopes return `comparable=false` and suppress change claims |
| P8 canonical vs raw grounding | GAP | **PASS** | `477f2e18` | raw CLI receipt/diff hydration remains available but is explicitly `canonical=false`; `full=true` cannot bypass canonical completeness |

R2 LFL precedent anchors L1–L5 remain **5/5 PASS** and were not redefined to make R1 green.

## 3. P4 — Predicate/wait

Commit: `af87c8c1 feat(smc): make wait predicate observations tri-state`

The Domain-0 wait observer now emits mechanical three-state evaluation:

- `satisfied`: decisive positive witness;
- `unsatisfied`: valid sampled observation reached the deadline without satisfying the predicate;
- `indeterminate`: observation failure or insufficient negative coverage prevents a mechanical answer.

The receipt exposes:

- `evaluation_mode=polling`;
- `interval`;
- `sample_count`;
- `observer_error_count`;
- `coverage_complete`;
- `sampling_semantics=discrete_samples_only`.

A capped `file_contains` negative no longer becomes false merely because the first 8 MiB lacked the needle. A positive witness inside the observed region may still satisfy the predicate even when total coverage is partial.

The program reports these observation facts only. It does not decide whether the model should retry, widen the observation, or change strategy.

## 4. P7 — Scope comparability

Commit: `5114326b feat(smc): guard diff scope comparability`

Snapshots bind a capture-time mechanical scope:

```text
absolute roots + depth
```

Diff first compares the two observation scopes. Same scope may yield change facts. Different roots, different depth, or unknown legacy scope yields:

```text
comparable=false
scope_relation=<mechanical relation>
created/deleted/modified/total_changes=null
display_rows=[]
```

No hidden re-snapshot or scope correction occurs. Whether the model wants another observation under a common scope remains a model decision.

## 5. P2 — Field-level completeness

Commit: `eeee6a7b feat(smc): expose diff field completeness`

For complete comparable observations, all diff fields are exhaustive.

For truncated/walk-incomplete observations:

- `created/deleted/total_changes` are unknown (`null`);
- `+/-` presentation is suppressed;
- observed intersection modifications remain available as a truthful lower bound;
- `field_completeness` explicitly marks those facts as non-exhaustive;
- `modified_semantics=observed_lower_bound` prevents a lower bound from being read as the full set.

This keeps useful positive evidence without turning partial coverage into a false global claim.

## 6. P8 — Raw grounding is not canonical interpretation

Commit: `477f2e18 feat(smc): mark raw SMX receipt grounding noncanonical`

`receipt(full=true)` still hydrates the exact stored SMX CLI evidence, but the model-facing response adds:

```text
canonical=false
representation=raw_smx_receipt
```

and raw diff evidence is labeled `raw_smx_diff`, also noncanonical. The stored raw receipt is not rewritten.

This preserves auditability while preventing raw truncated counts from bypassing the P2 canonical completeness discipline.

## 7. P5 — Snapshot content integrity

Commit: `b780b4d6 feat(smc): verify snapshot content integrity`

New snapshots persist:

```text
content_sha256_basis=canonical_snapshot_content_v1
content_sha256=<64 hex>
```

The hash is independently recomputable from canonical stored observation content while excluding random snapshot identity and the token itself. `_load_snap` verifies the token and rejects stored-content tampering explicitly.

The token proves only that the captured snapshot content has not been rewritten. It does **not** prove that the world is still current or that the observation is relevant to the user's task.

Legacy snapshots without this token remain readable; they are not silently upgraded.

## 8. P0 — Additive canonical wire

Commit: `79156fb5 feat(smc): project canonical SMX observations`

The existing `smx_perceive` response remains the transport/compatibility envelope. A nested `smc` projection is additive for canonicalizable observation actions:

### snapshot → `smc.world_snapshot.v0.1`

The nested projection contains the v0.1 required mechanical fields:

- `schema/domain/snapshot_id/scope/observed_at`;
- `completeness`;
- capture `budget`;
- `grounding_version=content_sha256`;
- model-facing `projection` plus hydratable `objects_ref/full_ref`.

The referenced object representation is explicitly `raw_fs_entries_v1`; this does **not** claim that filesystem paths have become canonical physical SemanticObject identities. That remains G1 work.

### diff → `smc.semantic_diff.v0.1`

The nested projection contains:

- `from_version/to_version`;
- `diff_semantics=snapshot_pair_net`;
- canonical `comparable/scope_relation` plus adapter relation;
- full `created/removed/changed` mechanical lists when exhaustive;
- incomplete lower-bound behavior when not exhaustive;
- `completeness/field_completeness`.

For live comparison without an explicitly persisted current snapshot, `to_version` is a content-bound `live-sha256:*` observation version; it is not misrepresented as a persisted snapshot ID.

### wait → `smc.action_receipt.v0.1` + `smc.predicate.v0.1`

The canonical wait receipt separates action mechanics from predicate truth:

- tool/action `status=ok` may coexist with `predicate_result.result=unsatisfied`;
- normal file predicates are `operation_class=observe`;
- loopback port-connect predicates are `operation_class=probe`;
- Predicate target/property/operator/value are derived only from the explicit mechanical wait arguments;
- raw SMX receipt remains the grounding reference.

No task completion or semantic correctness is inferred from the predicate result.

### receipt action stays raw

`smx_perceive(action=receipt)` intentionally does **not** receive a fake canonical `smc` object. P8 remains the governing boundary: raw receipt hydration is evidence and remains `canonical=false`.

## 9. What is now mechanically closed

Within the measured Domain-0 probe surface, the adaptation closes the previously observed gaps:

- G6 snapshot content-integrity token — P5;
- G7 Predicate observer-error tri-state — P4;
- G9 diff scope comparability — P7;
- G10 canonical SemanticDiff/observation wire — P0;
- G11 explicit model-facing `diff_semantics` — P0 for Domain-0;
- G12 Predicate sampling facts — P4;
- G13 partial-negative honesty — P4;
- G14 modified lower-bound field completeness — P2;
- G15 observation/projection canonical layering — P0;
- G16 raw hydrate vs canonical interpretation — P8.

“Closed” here means the current mechanical probe now has a conforming Domain-0 implementation. It does not imply cross-domain sufficiency.

## 10. Residual contract risks deliberately not claimed solved

The following remain outside the current Domain-0 proof:

- **G1 physical object identity continuity** — filesystem path remains a location key, not proof of physical identity across rename/path reuse;
- **G2 canonical mutation SemanticAction wire** — P0 canonicalizes observation snapshot/diff and wait receipt/predicate, not mutation dispatch;
- **G3 multi-sensor object coverage** — no DOM/AX/vision conflict or blind-spot fusion is exercised;
- **G4 high-frequency stale/identity pressure** — no rapid page/state churn qualification;
- **G5 spatial relations** — no visual/geometry relation contract has been stressed;
- **G8 async ActionReceipt append-only revision history** — the existing SMX CLI async receipt overwrite behavior is still a contract gap;
- **cross-domain G11** — Domain-0 now emits `snapshot_pair_net`, but Browser navigation/frame/tab semantics have not yet proven the enum sufficient.

Additional conservative boundaries:

- a WorldSnapshot `objects_ref` currently hydrates raw FS observation entries, not a solved cross-domain SemanticObject identity model;
- a live diff current-side version is content-bound but not independently persisted as a snapshot;
- the canonical wait receipt is an observation receipt, not evidence that canonical mutation actions are implemented.

## 11. Validation

### Focused + conformance + provider-schema regression

```text
tests/test_smx_perceive.py
tests/unit/test_smc_contract_v01_conformance.py
tests/unit/test_schema_lazy.py

54 / 54 PASS
```

Current conformance probe matrix:

```text
R1 / SMX P0–P8: 9 PASS / 0 GAP / 0 FAIL
R2 / LFL L1–L5: 5 PASS / 0 GAP / 0 FAIL
```

Again: this matrix is a set of measured contract probes, **not a quality/maturity percentage**.

### Adjacent regression

The combined bundle covered:

```text
tests/test_smx_perceive.py
tests/unit/test_smc_contract_v01_conformance.py
tests/unit/test_schema_lazy.py
tests/unit/test_model_protocol_schema.py
tests/unit/test_factory.py
tests/unit/test_evidence_phase8.py
tests/unit/test_file_service_versioning.py
tests/unit/test_source_synopsis.py
```

All collected cases passed.

### Static and repository gates

```text
Ruff (touched production/tests): PASS
Pyright (touched LFL production): 0 errors / 0 warnings / 0 informations
py_compile: PASS
git diff --check: PASS
whole-tree security: PASS — 1621 tracked files
scripts/ci_gate.sh: exit 0
  - repository Ruff: PASS
  - env-pin: 535 test files / 0 undeclared COMPACT_RATIO dependents
  - src Pyright: 0 / 0 / 0
  - tier0: PASS
  - xdist full suite: PASS
```

`tools/smx/smx.py` had pre-existing modernization lint debt outside the repository Ruff gate. During P4 it was checked as HEAD-vs-candidate differential: the candidate introduced no new lint and reduced the observed baseline count. No broad formatting/rewrite was performed.

No validation above calls the local model or requires a new 8901 workload.

## 12. Runtime / experiment governance

This adaptation changes the SMX treatment implementation after the already closed v1.2 A/B. Therefore:

- `SMX-FOCUSED-RESULT-v1.2.md` remains valid only for its frozen pre-adaptation treatment;
- the adaptation does not retroactively receive credit for v1.2 behavior;
- a future behavioral experiment must be a new version (for example v1.3) with a newly frozen executor, manifest, source hashes, and treatment surface;
- SMX remains opt-in by default;
- no service/model restart was required for this code qualification.

Long-running Web/Feishu processes are not claimed to have hot-reloaded these commits. If they need to exercise the new adapter later, restart qualification should be done as a separate runtime operation rather than folded into this contract result.

## 13. R3 Browser paper stress-test entry conditions

Before any claim that SMC v0.1 is cross-domain sufficient, R3 Browser must pressure at least these cases on paper first:

1. **Stable identity under DOM churn** — reorder, detach/reattach, duplicate text/role, locator reuse, and ambiguous continuity must never silently rebind one Semantic ID to another physical object.
2. **Scope/ref across tab/frame/navigation boundaries** — same-page updates vs navigation/iframe/tab changes must produce explicit scope relations before any diff claim.
3. **TOCTOU mutation precondition** — a Browser SemanticAction must revalidate `expected_version + version_scope` immediately before dispatch and reject stale targets mechanically.
4. **ActionReceipt revision semantics** — running → terminal receipts must be append-only/revisioned, not overwritten while old references pretend to remain immutable.
5. **DOM/AX/vision coverage conflict** — sensor absence, permission/viewport blind spots, conflicting attributes, and explicit model-requested vision must remain visible without program-side semantic arbitration.
6. **Browser diff semantics** — `snapshot_pair_net` vs navigation/event semantics must be sufficient to prevent “new page = old page deleted + new page created” misinterpretation.
7. **Browser Predicate honesty** — async wait/assert must preserve tri-state, sampling facts, observer errors, and negative-coverage discipline.
8. **Authority audit** — adapter may expose facts/capabilities/hard boundaries, but must not recommend elements, generate hidden action sequences, infer task completion, or silently retry semantic alternatives.

Only after this paper stress test should Browser Phase 1 implementation claim its schema is using a sufficiently stressed cross-domain contract.

## 14. Final ruling

> **SMC v0.1 已通过 Domain-0 可机械化与 LFL 先例验证；尚未通过 R3 Browser 跨域充分性验证。**

More precisely:

- the measured Domain-0 P0–P8 conformance gaps are now mechanically closed;
- LFL precedent anchors remain valid;
- SMC/SMX has **not** been proven as a complete cross-domain manipulation architecture;
- Browser R3 remains the next epistemic gate, not a documentation formality.
