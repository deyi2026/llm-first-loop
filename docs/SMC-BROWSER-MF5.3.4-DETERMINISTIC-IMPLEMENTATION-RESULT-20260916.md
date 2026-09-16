# SMC Browser MF-5.3.4 GroundingRef Deterministic Implementation Result

Date: 2026-09-16
Measured-result baseline: `be99d0673517e44f1f0a6c4870523433f7ebcb3f`
RED: `395f759065222c7dbdfae2225239f20640192038`
Qualified implementation/test HEAD before this docs closure: `4376ca4bfc48169f19b5cc75f4bd4d3ad7b79abb`
Status: **DETERMINISTICALLY QUALIFIED — LIVE MEASURED TREATMENT NOT STARTED**

## 1. Scope

MF-5.3.4 closes the single remaining provider-contract ambiguity observed in the frozen MF-5.3.3 six-row treatment:

- the snapshot exposes a canonical full `grounding_ref` next to the semantic object's opaque `id`;
- provider-visible object waits previously named their exact-ref argument `object_ref`;
- MF-5.3.3 Row 5 supplied the bare semantic `el_...` id to that field, which the runtime correctly rejected as `invalid_ref` before the model recovered with a full GroundingRef.

This correction changes only the model-visible object-wait argument role. It does **not** weaken exact-reference validation and does not add fuzzy matching, latest/rebind, automatic retry, task-success inference, or semantic target selection.

## 2. Exact commit chain

| Stage | Commit | Purpose |
|---|---|---|
| MF533 formal measured freeze | `be99d067` | Freeze 6/6 task PASS and the single Row5 `object_ref` repair with artifact hashes |
| MF534 RED | `395f7590` | Freeze model-visible `grounding_ref`, hidden `object_ref` compatibility, and bare-id fail-closed behavior |
| Production implementation | `fd61cf76` | Expose `grounding_ref` on object waits and mechanically translate it to existing internal exact-wait machinery |
| Current-contract alignment | `4976868b` | Align two cognition-preserving provider-surface unit contracts; no production change |
| Remaining surface alignment | `4376ca4b` | Remove stale root `object_ref` expectations from three current Browser surface tests; no production change |

The production correction is independently attributable to `fd61cf76`.

## 3. RED evidence

The independently committed RED at `395f7590` initially produced exactly **4 RED / 2 PASS**.

Expected RED:

1. provider `object_state` branch must expose and require `grounding_ref`;
2. provider `object_text` branch must expose and require `grounding_ref`;
3. lazy provider surface must expose the same contract;
4. a model-visible full GroundingRef must execute the existing exact object wait successfully.

Existing green safety/compatibility boundaries:

1. historical/internal `object_ref=<full grounding://...>` remains mechanically executable;
2. historical/internal `object_ref=<bare el_...>` remains fail-closed with `object_ref_unavailable:invalid_ref`.

After `fd61cf76`, the same RED suite is **6/6 PASS**.

## 4. Production implementation

Only `src/llm_loop/tools/builtin/browser_perceive.py` changes in the production commit.

Provider-visible full/lazy Perceive now uses:

- `object_state`: `action, kind, grounding_ref, state, value, within_ms`;
- `object_text`: `action, kind, grounding_ref, field, match, text, within_ms`.

The shallow provider root no longer exposes `object_ref`.

Execution remains narrow:

1. model-visible `grounding_ref` is mechanically passed to the already-existing typed object-wait layer as its internal `object_ref` request field;
2. historical flat `object_ref` callers are normalized to `grounding_ref` before provider-field validation;
3. historical nested `condition.object_ref` callers are normalized the same way;
4. the existing exact hydration/session fence remains authoritative;
5. a bare semantic id is still rejected by the existing GroundingRef validator.

No typed-wait core, GroundingRef resolver, Browser Operate logic, Factory registration, registry ordering, Evidence budget, iteration limit, retry policy, or task-completion authority changes.

## 5. Frozen provider surface at qualified HEAD

Worktree source provenance was explicitly bound to this semantic worktree:

`.../.worktrees/smc-model-friendly-v01-20260916/src/llm_loop/__init__.py`

Two Browser capabilities remain exactly:

- `browser_perceive`
- `browser_operate`

Combined lazy two-capability surface:

- JSON chars: **6,671**
- SHA256: `15c5066c15abe3998ba65facbbc3fd3d450bd5e8e05185e9395e02d768615d81`

Perceive parameters:

- JSON chars: **3,035**
- SHA256: `f0ddd98681823f16be3fd99b91dec98d44122018748c660d709849459464a297`
- full/lazy byte-equivalent under canonical JSON
- root `object_ref`: **absent**
- object-state/object-text branches: `grounding_ref` present and required

Operate parameters remain unchanged:

- JSON chars: **3,095**
- SHA256: `c1340352b2c390fec5f1c619a8219fa43b3b8eaa7165ac65419f924c456c684a`

Production source SHA256:

`32103c6c6e529a11a58d7c7ee04b25acdad0bfd8936f53af782e61e08dcdb403`

MF534 RED test SHA256:

`0aebf38cf93dcd45e6ab132f6f6ad3b0d71faceae52b0e8afbdbc5cd206738d1`

## 6. Current-contract migrations

The production correction intentionally invalidated five current unit-test expectations that still encoded the prior provider surface.

They were corrected in test-only commits after production was already frozen:

- `4976868b`: cognition-preserving Perceive / semantic-operation contract assertions;
- `4376ca4b`: three root provider-property lists.

No MF-5.3.2 or MF-5.3.3 frozen harness/protocol file was modified. A direct diff from `fc01ddc1` to the qualified HEAD over the entire MF533 harness and protocol test set is empty.

The first full non-real repository run therefore failed exactly three stale surface-list assertions and no production behavior test. After the test-only alignment in `4376ca4b`, the full non-real Gate was rerun from committed state and passed.

## 7. Deterministic qualification

### Focused

MF534 RED plus A', B1, MF5.3.1 Perceive, and MF5.3 semantic-operation focused coverage: **100% / exit 0** after current-contract alignment.

### Browser + Factory

Broad Browser coverage includes both `test_browser*.py` and `test_smc_browser*.py`, plus `test_factory.py`:

- files collected: **37**
- tests collected: **399**
- run: **100% / exit 0**

### Full repository non-real Gate

`pytest tests -q -m 'not real_llm'`:

- selected collection: **6,037 tests across 596 files**;
- final committed-state run: **100% / exit 0**;
- **0 FAILED / 0 ERROR**.

### Static / security

At qualified HEAD `4376ca4b`:

- Ruff `src tests`: **PASS**;
- Pyright full project: **0 errors / 0 warnings / 0 informations**;
- aggregate `git diff --check`: **PASS**;
- tracked-tree security scan: **PASS — 2,024 files**;
- tracked worktree: **clean**.

## 8. Runtime / experimental boundary

No Ornith measured row was executed in MF-5.3.4 deterministic qualification.

No MF53 runner/worker was present at final verification. The already-existing single Ornith server on 8901 remained the only local model server observed and was not restarted or duplicated by this phase.

No push, PR, merge, deployment, Web restart, Feishu restart, 8901 restart, or MF-6 work occurred.

## 9. Deterministic ruling

**MF-5.3.4 GroundingRef unification is deterministically qualified.**

The model-visible naming now matches the exact reference actually emitted by Browser perception, while historical internal compatibility and fail-closed exact hydration remain intact.

What deterministic qualification does **not** establish is whether a live Ornith treatment will reduce MF-5.3.3's remaining Row5 protocol repair to zero. That requires a fresh measured identity.

## 10. Next phase boundary

The next admissible step is a **fresh MF-5.3.4 measured protocol/manifest identity** derived from this qualified state while preserving the original six-row prompts, fixture, external oracles, hard Gate, model/runtime parameters, and no-row-replay discipline.

Before any live row:

1. freeze the fresh protocol/manifest;
2. run deterministic protocol checks;
3. run zero-model preflight;
4. prove exact source/provider/runtime identity and `model_requests=0`;
5. stop at a human checkpoint before Row 1.

Do not append to or rewrite the frozen MF533 measured identity.
