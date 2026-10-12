# SMC Browser MF-5.3.2 Post-Qualification Deterministic Corrections Result

Date: 2026-09-16
Audit baseline: `e05b92e624445102eb88e3e426e351bdd6075519`
Qualified implementation/test HEAD: `0e4eb293a10b2987a6d32d1e10c7630755be0034`
Status: **DETERMINISTICALLY QUALIFIED — LIVE MEASURED TREATMENT NOT STARTED**

## 1. Scope

This result closes the two deterministic corrections authorized after the MF-5.3.2 post-qualification read-only audit:

1. **B1 — direct DOM text preservation** for post-mutation evidence legibility;
2. **A' — Browser URL-role disambiguation** for Perceive-vs-Operate provider affordance.

The work intentionally did not run a new model treatment and did not change model budgets, tool ordering, target grounding authority, retry semantics, or task-completion authority.

## 2. Exact causal commit chain

| Stage | Commit | Purpose |
|---|---|---|
| B1 RED | `ba2307bc0416ed79f49a6df851b9bcdaddb4e4ee` | Freeze direct DOM text / stable-parent diff contract |
| B1 implementation | `058a5ae5e86316b4173800a79322b165561dacde` | Preserve direct `#text` on exact DOM parent |
| A' RED | `f310407d4c189a5f5be3c9c3e83446e5bc8c6981` | Freeze observed-URL vs destination-URL provider roles |
| A' implementation | `e4ee53520e8649a5360657501e1d5b98947bfcab` | Expose `expected_url` only on Perceive provider surface |
| Adjacent contract alignment | `0e4eb293a10b2987a6d32d1e10c7630755be0034` | Align three current provider-surface tests; no production change |

The A' and B1 production changes remain separately attributable.

---

# Part I — B1 direct DOM text preservation

## 3. RED evidence

The B1 RED was written before production implementation and initially produced **3 expected failures / 1 existing boundary pass**:

- RED: direct DOM `#text` child content must appear on its exact parent as existing `attributes.text`;
- RED: nested descendant text must stay on its direct parent and must not be hoisted to an ancestor;
- RED: a text change on the same stable parent must appear through the existing semantic diff as `attributes.text`;
- existing green boundary: script text must not become model-visible DOM text.

The RED was independently committed at `ba2307bc`.

## 4. Production implementation

B1 changes only `src/llm_loop/browser/perception.py`.

The DOMSnapshot capture path now:

1. mechanically enumerates `#text` nodes;
2. uses DOMSnapshot `parentIndex` as the only parent binding;
3. preserves non-empty direct text-node values in original DOM order;
4. uses that text only when the parent element itself has no non-empty node-value text;
5. writes into the already-existing closed-schema field `attributes.text`;
6. excludes `script`, `style`, `noscript`, and `template` parents.

It does **not**:

- merge or delete AX fragments;
- add AX lineage;
- use task prompt, target name, actionability, relevance, or completion semantics;
- change model target selection;
- change grounding/version checks;
- change mutation dispatch or retry;
- increase Evidence budget.

B1 implementation commit: `058a5ae5`.

## 5. B1 qualification result

The original B1 RED suite is now green. Adjacent Browser perception, semantic diff, live-perception, MF-5.3.2 projection, and capability-identity tests also pass.

The important semantic consequence is mechanical: when the same stable DOM parent changes direct text from `Not submitted` to `Submitted`, the existing semantic diff can report `attributes.text` on that stable object. No task-success inference is added.

---

# Part II — A' URL-role disambiguation

## 6. RED evidence

A' freezes one provider-surface distinction:

- Browser Operate owns navigation destination:
  `do=navigate + url=<destination>`;
- Browser Perceive `page_url` wait observes an expected page state:
  `action=wait + kind=page_url + expected_url=<observed target>`.

The A' RED initially produced **5 expected failures**, all tied to the old Perceive provider role or execution of the new field. At the same time, two boundaries already stayed green:

- Operate retained `do=navigate + url`;
- legacy/internal direct Perceive callers using old flat `url` remained mechanically executable.

The RED was independently committed at `f310407d`.

## 7. Production implementation

A' changes only `src/llm_loop/tools/builtin/browser_perceive.py`.

Provider-visible Perceive full/lazy schemas now use `expected_url` for the `page_url` branch and expose **no property key named `url`**.

Hidden execution compatibility remains intentionally narrow:

- legacy flat `page_url + url` is mechanically normalized to `expected_url`;
- historical nested `condition.url` is mechanically normalized to `condition.expected_url`;
- neither compatibility form is provider-visible.

Operate is untouched and continues to expose navigation destination `url`.

Factory and registry are untouched. Provider tool ordering is therefore unchanged and remains an independent future variable rather than being mixed into A'.

A' implementation commit: `e4ee5352`.

## 8. Frozen provider-role facts at qualified HEAD

For the current two Browser provider capabilities only:

- names: `browser_perceive`, `browser_operate`;
- combined lazy two-capability JSON chars: **6,704**;
- combined lazy two-capability SHA256:
  `831bd8aca15e0d5fdd4dc0d3eb64b43894f02a31e615fa85bd4d5814a6df999b`;
- Perceive parameters SHA256:
  `bad333c3f5aaf8cde6e4ca9be26ac13d0ae962a927f931a56469e671bce15435`;
- Operate parameters SHA256 remains:
  `c1340352b2c390fec5f1c619a8219fa43b3b8eaa7165ac65419f924c456c684a`.

Mechanical property-key check:

- Perceive: literal `url` property-key count = **0**; `expected_url` count = **2**;
- Operate: literal `url` property-key count = **2**; `expected_url` count = **0**.

This is a provider affordance correction only. It does not prove a live routing improvement until a new measured identity is run.

---

# Part III — committed-state qualification

## 9. Focused and adjacent Gates

After each implementation, focused RED and adjacent Browser tests were rerun from committed state.

For A', the focused set covering URL-role, MF-5.3.1 Perceive, semantic operation, MF-5.3.2 capability identity, B1, and Factory passed from committed state.

The broad Browser+Factory Gate initially caught exactly three stale current-contract assertions that still expected Perceive root property `url`. No production behavior failed. Those current tests were aligned to `expected_url` in independent test-only commit `0e4eb293`, while historical execution compatibility and Operate destination-URL tests were left unchanged.

The same Browser+Factory Gate then completed **100% / exit 0**.

## 10. Full repository qualification

At exact committed HEAD `0e4eb293a10b2987a6d32d1e10c7630755be0034`:

- `pytest tests -q -m 'not real_llm'`: **100% / exit 0 / no FAILED / no ERROR**;
- full Ruff `src tests`: **PASS**;
- full project Pyright: **0 errors / 0 warnings / 0 informations**;
- full tracked-tree security scan: **PASS, 2,013 files**;
- aggregate `git diff --check e05b92e6..0e4eb293`: **PASS**;
- tracked worktree: **clean**.

`src/llm_loop/factory.py` and `src/llm_loop/tools/registry.py` have zero diff from the read-only audit baseline, mechanically proving A' did not change provider registration/order policy.

## 11. Runtime / execution boundary

No fresh measured model request was made during this correction phase.

No MF5 measured runner/worker was active at final qualification. The only local model process observed was the already-existing single Ornith server on 8901 with prompt/decode concurrency 1/1. It was not restarted or duplicated by this work.

No push, PR, merge, deployment, service restart, or MF-6 work occurred.

---

# 12. Deterministic ruling

**B1 + A' are deterministically qualified.**

B1 closes a mechanically reproduced evidence-representation gap without adding task semantics. A' removes a mechanically observed provider argument-role collision without adding a model routing protocol.

What is **not** yet established:

- that A' improves first-call routing under Ornith;
- that B1 materially reduces post-success evidence amplification or avoids the old fill timeout in live treatment;
- that tool ordering needs any change;
- that AX lineage/fusion is needed after B1.

Those are live or later-phase questions and must not be inferred from deterministic qualification alone.

## 13. Next phase boundary

The next admissible experimental step is a **fresh measured protocol identity** derived from this exact qualified implementation state, with zero-model preflight before any model request.

A future measured treatment should preserve comparability with the prior six-row task/fixture/oracle matrix while changing only the newly qualified B1 + A' interface corrections unless a separately reviewed protocol change is explicitly justified.

Do not reuse or append to MF532 measured identities. Do not silently run a model row from this deterministic closure.

A human checkpoint is required before freezing/starting the next measured identity.
