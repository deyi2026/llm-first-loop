# SMC Browser MF-5.3.1 Deterministic Implementation Result — 2026-09-16

Status: **DETERMINISTICALLY QUALIFIED / LIVE MEASURED QUALIFICATION PENDING / MF-6 DEFERRED**

RED anchor: `54bf0c2684d05166c93819e9aacba4daa40c62f6`

Implementation anchor: `1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`

Measured predecessor: `MF-5.3 v0.1` at result commit `419433455182b75d12076e8ed52e8b381e65f57b`

## 1. Result

MF-5.3.1 closes the deterministic correction identified by the MF-5.3 v0.1 measured run.

The provider-facing `browser_perceive` contract is now **root-direct and action-specific**:

- `snapshot`: `action + projection_limit?`;
- `hydrate`: `action + grounding_ref`;
- `diff`: `action + from_version + to_version`;
- `wait/page_ready`: `action + kind + state + within_ms?`;
- `wait/page_url`: `action + kind + match + url + within_ms?`;
- `wait/object_state`: `action + kind + object_ref + state + value + within_ms?`;
- `wait/object_text`: `action + kind + object_ref + field + match + text + within_ms?`.

Every branch is closed with `additionalProperties=false`.

The provider surface no longer exposes nested `condition`, and it still does not expose runtime-owned `interval_ms`.

The execution layer mechanically converts flat wait fields into the already-existing typed-wait request path. No new interpretation authority was added.

## 2. Why this correction exists

MF-5.3 v0.1 achieved external task correctness **6/6**, but failed its cognition-preserving hard Gate because `browser_perceive` produced eight observable protocol repairs:

- 6/8: semantically correct wait conditions were serialized by the model as a JSON string inside nested `condition`;
- 2/8: `hydrate` carried the snapshot-only `projection_limit` field from the broad shared parameter bag.

The correction therefore removes unnecessary protocol structure instead of teaching the model to remember it or making the runtime permissively guess intent.

The runtime still rejects malformed or unsupported requests fail-closed.

## 3. RED evidence

Commit `54bf0c26` froze eight MF-5.3.1 focused tests before production modification.

Initial committed-state result:

- **6 RED**:
  1. provider schema had no root-direct closed `oneOf`;
  2. wait fields remained nested under `condition`;
  3. action-specific branches were not independently closed;
  4. lazy provider surface retained nested condition shape;
  5. flat `page_url` wait did not execute;
  6. flat exact-object state wait did not execute;
- **2 PASS**:
  - runtime poll interval remained hidden;
  - fuzzy/best-match/auto-target/auto-retry/rebind/latest/task-completion authority remained absent.

After `1cb9ad2b`, the same focused suite is **8/8 PASS**.

## 4. Implementation boundary

Production change is limited to:

`src/llm_loop/tools/builtin/browser_perceive.py`

The implementation does four things only:

1. replaces the nested condition provider schema with seven root-discriminated closed branches;
2. uses the same root-direct schema for lazy provider delivery, preserving first-call self-sufficiency;
3. validates flat wait fields by exact `kind`-specific field sets;
4. mechanically constructs the existing internal condition object before invoking existing typed waits.

It does **not** modify:

- `browser_semantic_operation`;
- Browser Action or Semantic Execute;
- typed wait implementations or polling semantics;
- exact grounding/version/scope mechanics;
- mutation single-dispatch;
- evidence durability;
- task-completion authority.

For frozen historical evidence/tests, the execution function still accepts the old nested `condition` shape as an **internal compatibility path**. That shape is no longer model-facing.

## 5. Authority boundaries preserved

MF-5.3.1 does not add any of the following:

- JSON-string-to-object coercion;
- fuzzy or best-match target selection;
- automatic target choice;
- latest/rebind fallback;
- mutation retry/replay;
- runtime semantic relevance judgment;
- runtime task-success/completion judgment.

The program continues to own only mechanical translation, validation, polling cadence, exact grounding, version checks and evidence mechanics.

## 6. Provider-visible surface identity

The authoritative probe was executed with the semantic worktree explicitly first on `PYTHONPATH` and printed:

`<semantic-worktree>/src/llm_loop/__init__.py`

This avoids accidentally measuring the common repository's installed package.

### Lazy Browser two-capability surface

- names: `browser_perceive`, `browser_semantic_operation`;
- serialized chars: **6,734**;
- SHA256: `77f50738b6b8a02392ea7bdf79f70daddb052217f0009d7fb26c09984267cf46`.

`browser_perceive` parameters:

- chars: **3,041**;
- SHA256: `0c58e17dc769bcf772ad26f3c4c8085d8541a6d8c2b5fc145edb9f390b2127c8`;
- root branches: exactly 7;
- nested `condition`: absent;
- `interval_ms`: absent.

`browser_semantic_operation` parameters:

- SHA256: `c1340352b2c390fec5f1c619a8219fa43b3b8eaa7165ac65419f924c456c684a`;
- `steps`: absent.

The Operate parameter identity is unchanged by MF-5.3.1.

### Full Browser two-capability surface

- serialized chars: **6,967**;
- SHA256: `dfdaaf4f25fd802f8132b935691cb835eb93e6e3b5b3ca32a0d3253cad27a9ab`;
- Perceive parameter SHA is the same as lazy;
- the same seven root-direct branches are present.

### Important interpretation

The root-direct schema is not smaller in raw bytes than every earlier projection because action-specific closed `oneOf` branches repeat field constraints. That is acceptable.

The optimization target is **lower cognitive protocol tax**, not minimum serialized bytes. MF-5.3 measured evidence showed that the nested condition shape caused real repair behavior even though it could be represented compactly.

Schema byte cost remains a diagnostic and may be optimized later without reintroducing ambiguous/shared parameter structure.

## 7. Deterministic qualification

Exact implementation commit:

`1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`

Committed-state verification:

- MF-5.3.1 + MF-5.3 + frozen MF-5.3 protocol focused tests: **30/30 PASS**;
- all Browser unit tests: **316/316 PASS**;
- Factory tests: **24/24 PASS**;
- Ruff: PASS;
- targeted Pyright: **0 errors / 0 warnings**;
- staged security scan: PASS;
- `git diff --check`: PASS;
- tracked worktree after commit: clean;
- full `pytest tests -q -m 'not real_llm'`: **exit 0, 100%, 0 FAILED / 0 ERROR**, about 230.6s.

No live model was invoked by this qualification.

## 8. Historical-contract migrations

Five existing tests contained assertions that the provider-visible Perceive contract must expose nested `condition` or the old broad field set.

Those assertions were updated to the new provider contract. Historical nested-condition **runtime execution tests remain green**, proving the compatibility path was not removed merely to make the new surface pass.

No test was weakened around mutation authority, target grounding, polling ownership, exact refs, or safety boundaries.

## 9. Source identity

Committed SHA256:

- `src/llm_loop/tools/builtin/browser_perceive.py`:
  `23256d719a94f813d11b34a800f9e2f968dab0b6ec434ca5809d1f14e331d9ff`
- `tests/unit/test_browser_cognition_preserving_perceive_mf5_3_1.py`:
  `ef4e8cc3ce66fec0e00c72b650bee09817e9832c18f6a096c8213f4d5c6e18b0`

RED → implementation production/test migration diff:

- 6 files;
- 198 insertions;
- 199 deletions.

## 10. Qualification ruling

MF-5.3.1 is **deterministically qualified** for a fresh measured qualification identity.

It is **not yet live-qualified**.

The correct next sequence is:

1. freeze a new MF-5.3.1 measured protocol/manifest identity;
2. retain the same frozen task prompts/fixture and hard correctness/safety Gate unless a protocol-versioned reason requires an explicit change;
3. add explicit surface assertions for root-direct Perceive and absence of nested `condition`;
4. run `model_requests=0` zero-model preflight;
5. stop at a human checkpoint before the first Ornith measured row;
6. if authorized, run the fresh treatment matrix without replaying failures.

The principal measured question is now narrow:

> Does root-direct Perceive drive `browser_perceive` contract repair from 8 toward 0 while preserving the already-demonstrated 6/6 task correctness and all safety boundaries?

MF-6 remains deferred until a treatment hard-passes its frozen live Gate.
