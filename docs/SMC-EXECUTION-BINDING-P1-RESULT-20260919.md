# SMC Execution Binding P1 — Synthetic Desktop/Mobile Qualification Result

> Date: 2026-09-19
> Status: **QUALIFIED_DETERMINISTIC / SYNTHETIC / NON-PRODUCTION**
> Exact candidate commit: **11559ea640e4bdb19e39331975d824d7a0aacc58**
> Reviewed P1 spec commit: **22692bd6cc4d61aa045f6ae99d529076ac2db349**
> Frozen Execution Binding contract commit: **3b7163a11dca88e7a4e2bd6c6b7146e5925adc31**

---

## 1. Verdict

Execution Binding P1 satisfies **P1-G1 through P1-G12** for the synthetic Desktop/Mobile read-only reference phase.

This result qualifies only the deterministic reference mechanics:

- revision-bound capability discovery;
- ActionRef issuance/admission/invalidation;
- equivalent-only deterministic binding selection;
- binding-specific InteractionContext rejection;
- monotonic permission/confirmation composition;
- revalidation after explicit user-confirmed parameter edits;
- human preemption and honest post-dispatch settling;
- no-queue effect reservation;
- issuer-backed portable identity boundary;
- frozen-schema structural validation;
- deterministic evidence reproduction;
- zero real OS dispatch.

It does **not** qualify any real operating-system adapter or live mutation path.

---

## 2. RED → GREEN evidence

P1 was implemented test-first.

### RED

The P1 unit test was created before the P1 reference implementation.

The first run failed at collection because the evaluation package did not exist:

~~~text
ModuleNotFoundError: No module named 'evals.smc_execution_binding_p1'
~~~

### First GREEN attempt

After adding the eval-only implementation, the suite exposed two real defects:

1. capability sorting incorrectly assumed provider_id was carried by each capability item, while the frozen schema makes provider identity page-level;
2. the test-only schema validator returned immediately after anyOf / oneOf, thereby skipping sibling required / properties constraints and falsely accepting unrelated envelope shapes.

The tests were not weakened.

The implementation was corrected so that:

- capability order uses the page-level provider plus the frozen item order dimensions;
- JSON Schema combinators are evaluated together with sibling constraints;
- unsupported schema keywords fail closed.

The focused P1 suite then reached GREEN.

---

## 3. Frozen implementation artifacts

The P1 implementation candidate is exact commit:

~~~text
11559ea640e4bdb19e39331975d824d7a0aacc58
~~~

It adds only eval/test files. No src/ production file changed.

| Artifact | SHA-256 |
|---|---|
| docs/SMC-EXECUTION-BINDING-P1-SPEC-20260919.md | b53e247cd1444480e1aa7284e282b69ae3f05966df6f260d174a3847585ee82f |
| evals/smc_execution_binding_p1/P1-FIXTURES.v0.1.json | 6297c1c395667f140012d6b078c6860151deeffc5b559e778fe848028066bbb9 |
| evals/smc_execution_binding_p1/reference.py | 9aeda3eb4165518bfd6d930931a9addf245a347a3d4a8abd22e1878159bbdaf9 |
| evals/smc_execution_binding_p1/schema_validator.py | f1b0881b623708bc7c867f991bb6b5bdeb74a97e43ffd6bb24bde4cf7abe34a9 |
| tests/unit/test_smc_execution_binding_p1.py | d5d2f05500803c6915e48e33c68f42ac5e7d9074cd5732722ef000619183fc2f |
| evals/smc_execution_binding_p1/results/P1-v0.1-20260919/EVIDENCE.json | 6e2a3a98317bececa4d687e37a2e8c1d42f4ee9d6eee74895aa7b04169119855 |

The repository environment does not contain the external jsonschema package. P1 therefore did **not** add a production dependency. Its schema validator is eval-only, implements the exact keyword subset used by the frozen schema, and rejects unsupported keywords.

---

## 4. Desktop and Mobile synthetic coverage

### Desktop

The synthetic Desktop profile exercises:

- manifest revision 7;
- direct native semantic/API bindings;
- keyboard shortcut binding;
- document save/export/share;
- HUMAN_REQUIRED protected unlock;
- active app/window/focus/keyboard-layout context;
- equivalent native-save and shortcut-save bindings.

### Mobile

The synthetic Mobile profile exercises the same SMC contract rather than a separate mobile protocol:

- manifest revision 3;
- App Intent-style semantic binding;
- system-command binding;
- HUMAN_REQUIRED protected unlock;
- orientation=portrait;
- virtual_keyboard=visible;
- foreground-scene and orientation preconditions.

This proves only cross-profile contract coherence, not real Android/iOS support.

---

## 5. Focused and adjacency qualification

Exact committed-state qualification:

| Suite | Tests | Result |
|---|---:|---|
| test_smc_execution_binding_p1.py | 19 | PASS |
| test_smc_execution_binding_contract_v01.py | 13 | PASS |
| test_smc_contract_v01_conformance.py | 15 | PASS |
| test_smc_semantic_logic_p4d.py | 19 | PASS |
| **Total** | **66** | **66/66 PASS** |

Additional committed-state checks:

- Ruff: PASS;
- Ruff format: PASS;
- Pyright on the P1 eval/test surface: **0 errors / 0 warnings**;
- P1 fixture JSON parse: PASS;
- git diff --check: PASS;
- commit security scan: PASS;
- forbidden real-OS/network/input import scan: zero matches;
- tracked src/ changes: zero.

---

## 6. P1-G12 deterministic evidence

Two independent executions of run_case_matrix on the exact candidate commit produced identical canonical output.

~~~text
run_sha256:
4e8dbc64781ce2327dedf43249cb8aebc5c849a85aef2bfea5a8cb343dbaba6a

canonical_evidence_sha256:
62a8bea3be27a2e354d04fa1cdd57e62117bce5398120f56eb126572dadfcb47
~~~

Observed effect boundary:

| Fact | Value |
|---|---:|
| real OS dispatch | 0 |
| synthetic dispatch | 1 |
| queued effects | 0 |

The synthetic dispatch is an in-memory version/effect transition used to test after_version, observed_effects and receipt settling. It is not a real OS action.

---

## 7. P1-G10 full repository gate

Full repository CI was run from the exact candidate commit:

~~~text
PY=<repo-root>/.venv/bin/python bash scripts/ci_gate.sh
~~~

Final exit status: **0**

Observed results:

- all-repo Ruff: PASS;
- env-pin declaration gate: **628 test files scanned / 0 undeclared**;
- src Pyright: **0 errors / 0 warnings**;
- tier0 pytest preflight: PASS;
- xdist full repository gate: PASS;
- final ci_gate summary: PASS.

The run emitted the repository's existing 44 non-blocking audit_test_side_effects warnings. They were not P1 failures.

The full test run also generated a pytest restart-preflight log under scripts/data/audit. Readback showed it pointed to a pytest temporary directory with outcome=aborted. Only that verified test residue was removed after CI; no source or user artifact was deleted.

---

## 8. Gate summary

| Gate | Result | Evidence |
|---|---|---|
| P1-G1 Manifest consistency | PASS | revision-bound paging, deterministic ordering, consumer order rejection |
| P1-G2 ActionRef exactness | PASS | six single-fault rejects, TTL != freshness, no silent refresh |
| P1-G3 Semantic equivalence | PASS | equivalent-only selection, deterministic tie-break, cross-class reject |
| P1-G4 Authority monotonicity | PASS | provider descriptive only, runtime/platform constraints preserved, effective action revalidated |
| P1-G5 Context safety | PASS | context-sensitive race reject, context-free direct binding decoupled |
| P1-G6 Human preemption | PASS | pending action rejects, dispatched action settles, no replay |
| P1-G7 Receipt honesty | PASS | requested/effective delta only through explicit user edit; synthetic effects retained |
| P1-G8 Cross-device identity | PASS | issuer-backed link only; similarity does not create identity |
| P1-G9 Contract/schema/fixture consistency | PASS | closed frozen schema, six positive envelopes, structural negatives, no new revision |
| P1-G10 Full repository regression | PASS | full ci_gate exit 0 |
| P1-G11 Zero real side effect | PASS | no real OS dispatch/import path; synthetic mutation only |
| P1-G12 Evidence determinism | PASS | two identical independent canonical runs/hashes |

---

## 9. Important non-claims

P1 does **not** prove:

- macOS AX integration works;
- Windows UIA integration works;
- Linux AT-SPI integration works;
- Android AccessibilityService integration works;
- iOS App Intent integration works;
- real user/AI co-control is safe;
- the model is First-Call-Ready on this surface;
- P4-FCR v0.2 is qualified;
- P4-LIVE is qualified;
- any production tool/provider surface has changed.

No deployment, service restart or model request occurred in P1.

---

## 10. Phase boundary

P1 is complete as a **synthetic deterministic reference qualification**.

The result grants only the right to propose the next independent phase.

It does not automatically authorize real platform observation or mutation.

The next architecture choice should therefore be made explicitly between:

1. a real-platform **read-only observation** phase, with a fresh platform-specific protocol and no mutation; or
2. returning to the independent P4-FCR ActionRef v0.2 causal chain.
