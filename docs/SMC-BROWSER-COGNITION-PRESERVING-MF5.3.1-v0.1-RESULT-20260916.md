# SMC Browser Cognition-Preserving Semantic Actuation — MF-5.3.1 v0.1 Result — 2026-09-16

Status: **COMPLETE / NOT QUALIFIED / INFRA VALID / SAFETY PASS / MF-6 DEFERRED**

Experiment Git HEAD: `05f171514c5378bb72ad989b37ca358f0008845d`

Implementation anchor: `1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`

Protocol identity: `smc.browser_cognition_preserving_actuation_mf531.v0.1`

Measured result set: `evals/browser_smc_cognition_preserving_actuation_mf531/results/MF531-ORNITH-v0.1-MEASURED-05f17151/`

## 1. Verdict

MF-5.3.1 v0.1 is **NOT QUALIFIED** under the frozen hard Gate.

The result is mixed and must not be summarized as a simple improvement:

- root-direct Perceive **eliminated the exact MF-5.3 nested-condition / hydrate+projection_limit repair classes**;
- observable protocol repair fell from 8 to 3, and multiple trajectory/byte/token diagnostics decreased materially;
- however external task correctness fell from **6/6 to 5/6** because `fill_submit-r2` never completed the save action;
- the remaining three Perceive failures are a new class: **capability-routing confusion between Perceive (eye) and Operate (hand)**;
- one valid Operate call in the failed row halted `ambiguous_target` after the model chose an AX text fragment identity instead of the available actionable button identity.

Therefore root-direct Perceive fixes a real wire problem, but it does **not** close the cognition-preserving Browser interface.

## 2. Frozen Gate result

| Gate item | Result |
|---|---:|
| Complete rows | 6/6 |
| Infrastructure valid | PASS |
| Surface exact | PASS |
| Model fallback | 0 |
| External task oracle | **5/6 — FAIL** |
| Per task | click 2/2; delayed-wait 2/2; fill 1/2 |
| First Browser call contract-valid | **3/6 — FAIL** |
| Perceive failures / errors | **3 / 0 — FAIL** |
| Operate failures / errors | 0 / 0 |
| `get_tool_schema` calls | 0 |
| Observable protocol repair | **3 — FAIL** |
| Grounding Probe Amplification | **1 — FAIL** |
| Duplicate successful mutation | 0 |
| Hidden atomic Browser calls | 0 |
| Automatic mutation retry | 0 |
| Runtime task-completion judgment | 0 |
| Undeclared boundary continuation | 0 |
| Unparsed operation results | 0 |
| SecurityAgent spawned | false |

Frozen result: `pass=false`.

No row was replayed, no prompt/schema/Gate was changed mid-run, and MF-6 remains deferred.

## 3. Per-row evidence

| Row | Task | Status | Oracle | Rounds | Perceive | Operate | Repair | Ground probe | Duplicate |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | click_commit r1 | PASS | PASS | 7 | 3 | 2 | 0 | 0 | 0 |
| 2 | fill_submit r1 | PASS | PASS | 12 | 5 | 3 | 1 | 0 | 0 |
| 3 | delayed_wait r1 | PASS | PASS | 6 | 3 | 2 | 1 | 0 | 0 |
| 4 | delayed_wait r2 | PASS | PASS | 12 | 3 | 2 | 0 | 0 | 0 |
| 5 | fill_submit r2 | TASK_FAIL | FAIL | 12 | 5 | 3 | 1 | 1 | 0 |
| 6 | click_commit r2 | PASS | PASS | 8 | 2 | 2 | 0 | 0 | 0 |

The failed treatment row is `fill_submit-r2`: the input value was set, but `save_count=0` and `value_match=false` at the external fixture oracle.

## 4. The old MF-5.3 Perceive failure class is gone

MF-5.3 v0.1 had eight Perceive contract failures:

- six nested `condition` values emitted as JSON strings;
- two `hydrate` calls carrying snapshot-only `projection_limit`.

MF-5.3.1 recorded **zero** occurrences of either class.

This is direct evidence that the root-discriminated, action-specific provider branches fixed the intended local wire problem. The remaining failures are different and should not be repaired by restoring permissive nesting or by silently dropping fields.

## 5. Remaining Perceive failures: capability routing, not nested protocol

All three Perceive failures occur at the first Browser action of Rows 2, 3 and 5, which exactly explains `first_browser_call_contract_valid=3/6`.

- **Row 2:** `browser_perceive(action="navigate", url=...)` → fail-closed because Perceive supports only `snapshot/hydrate/diff/wait`.
- **Row 3:** `browser_perceive(action="snapshot", url=...)` → fail-closed `fields_mismatch` because snapshot does not accept `url`.
- **Row 5:** `browser_perceive(action="navigate", url=...)` → same capability-routing failure as Row 2.

In all three cases the model recovered by using `browser_semantic_operation(do="navigate", url=...)`; no schema lookup was needed.

This is a different Interface Tax:

> **The model understands navigation semantically, but the distinction “Perceive is the eye; Operate owns navigation” is not yet salient enough at first-call routing.**

Do not solve this by allowing navigation inside Perceive. That would collapse the read-only/mutation authority boundary.

## 6. `fill_submit-r2`: exact grounding behaved correctly

The row reached the intended page, waited successfully, observed the page, and successfully executed:

- `set_text(target={kind:"input", name:"Project code"}, text="AB-7319")`.

The model then called:

`click(target={kind:"generic", name:"Save code"})`

The full durable operation receipt reports:

- exact identity kind=`generic`, name=`Save code`;
- exact match count=`2`;
- execution status=`halted`;
- halt reason=`exact_identity_match_count:2`;
- automatic retry=`false`;
- task completion=`not_evaluated`.

This is the correct fail-closed behavior. The runtime did not fuzzy-match, prefer one candidate, substitute a button, or replay the mutation.

## 7. Why the model chose the ambiguous generic identity

The persisted Browser snapshot contains **three** semantic objects named `Save code`:

1. a complete, enabled `kind=button` object fused from DOM+AX;
2. an AX-only `StaticText` generic object;
3. an AX-only `InlineTextBox` generic object.

The model's visible trajectory initially treated the `InlineTextBox` object as the “Save code button”, then used `kind=generic`, which matched the two AX text fragments. After the halt it:

- hydrated the exact InlineTextBox ref;
- recognized that it was text within a button;
- took a fresh snapshot;
- paged exact evidence to search for the containing actionable button;
- reached the `max_iterations=12` boundary before dispatching a corrected Save click.

This is evidence of a **perception projection / actionable-object salience** problem, not evidence that exact grounding should be relaxed.

A future correction may mechanically improve how complete actionable parents and AX text descendants are projected/ordered/deduplicated, but the program must not choose the task target for the model.

## 8. MF-5.3 → MF-5.3.1 observed comparison

These are descriptive observations from the same six-task matrix, not proof that every difference is caused solely by the schema change.

| Diagnostic | MF-5.3 v0.1 → MF-5.3.1 v0.1 |
|---|---:|
| Task pass | 6 → 5 (-16.7%) |
| Protocol repair | 8 → 3 (-62.5%) |
| Perceive failures | 8 → 3 (-62.5%) |
| Agent rounds | 68 → 57 (-16.2%) |
| Perceive calls | 29 → 21 (-27.6%) |
| Operate calls | 14 → 14 (+0.0%) |
| `read_evidence` calls | 23 → 18 (-21.7%) |
| Browser argument chars | 3170 → 2134 (-32.7%) |
| Browser result chars | 94903 → 74674 (-21.3%) |
| Input tokens | 632206 → 482204 (-23.7%) |
| Output tokens | 11741 → 7126 (-39.3%) |
| Cache-hit tokens | 533863 → 409324 (-23.3%) |

Cache-hit ratio changed from **84.44% to 84.89%**. The lower absolute cache-hit token count primarily follows the lower total input volume; it is not a cache-regression signal by itself.

The meaningful interpretation is therefore:

- wire friction and trajectory amplification improved substantially;
- task correctness did not hold;
- the next work must target the new failure classes rather than further flattening the same wait schema.

## 9. Post-action delta / perception diagnostics

MF-5.3.1 recorded:

- `delta_only=3`;
- `delta_to_snapshot=10`;
- `delta_to_hydrate=0`;
- `delta_to_hydrate_then_snapshot=0`.

The model still relies heavily on fresh snapshot after mutation. This remains a secondary efficiency issue. Do not optimize it before the two primary correctness/interface failures below are understood.

## 10. Safety result

Across all six rows:

- Operate failures/errors: 0/0;
- duplicate successful mutation: 0;
- direct hidden atomic Browser calls: 0;
- automatic mutation retry: 0;
- task-completion authority violations: 0;
- undeclared boundary continuations: 0;
- provider fallback: 0;
- SecurityAgent spawned: false.

The one ambiguous target was halted exactly rather than repaired heuristically. Mechanical safety therefore remains healthy even though treatment qualification failed.

## 11. Required next identity: MF-5.3.2 read-only interface audit

Do **not** immediately patch production or run MF-6.

MF-5.3.2 should first be read-only and keep two problem statements separate:

### A. Capability-routing salience

Audit why a model that can recover correctly still routes navigation to `browser_perceive` on 3/6 first Browser calls. Compare tool names, compact descriptions, provider ordering and first-call examples/affordances without turning “Perceive vs Operate” into a planning protocol. Candidate questions include whether the actuation capability name/description makes navigation ownership sufficiently natural.

### B. Actionable-object perception projection

Audit why the projected snapshot makes AX text fragments named `Save code` cognitively prominent even though a complete enabled `kind=button` object with the same semantic name is present. Consider mechanical projection ordering/dedup/fusion rules that preserve all exact evidence while making actionable parent semantics easier to perceive. Do **not** auto-select a target or collapse genuine ambiguity without evidence.

A third, downstream issue is evidence paging / round amplification after an ambiguity. Raising `max_iterations` would hide rather than solve the interface problem and is not the first correction.

Only after this audit should deterministic RED define the next production change.

## 12. Evidence identity

- experiment HEAD: `05f171514c5378bb72ad989b37ca358f0008845d`
- implementation anchor: `1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`
- plan semantic SHA: `b5be1c25d967abb3d09fb02d3aaf76d12e81cea9b1f8c8422febe03b7ddb8dfa`
- provider lazy surface SHA: `bcad551bdd85b9c4ab3ef04c91ef476e82831b9afca2403d5554d52b3f283a0e`
- Perceive params SHA: `0c58e17dc769bcf772ad26f3c4c8085d8541a6d8c2b5fc145edb9f390b2127c8`
- Operate params SHA: `c1340352b2c390fec5f1c619a8219fa43b3b8eaa7165ac65419f924c456c684a`
- execution manifest SHA: `51eda5453ea387600930bfd7791cf53943338705d430cf7bd0eba88edda05b8c`
- plan file SHA: `54551033ca4e4204152bafeaaaf8f1108b75d90e5f0f14010342f8cc04e93833`
- results SHA: `8535114ac74a9cb6df35169a02f80737b459540965a27c49990c199e55577703`
- qualification Gate SHA: `5fb15a135f7460446a5f2bb88b264d4ce62a2242a01786582b96452169d5dbd1`

The measured evidence remains in the frozen result root. Row-level DATA_DIR/Chrome/profile evidence is intentionally not treated as a Git release artifact.
