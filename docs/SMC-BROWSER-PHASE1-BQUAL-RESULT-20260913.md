# SMC Browser Phase 1 — B-QUAL Final Qualification Result

Date: 2026-09-13
Baseline: `2a44814bb3878817fbef2f25cf4741ec61e32588`
Implementation commit: `a1a659e375dc8436eb71c30cb182f9651693a8ae`
Status: **QUALIFIED**

## 1. Qualification judgement

Browser Phase 1 v0.1 is qualified for the frozen structural SMC surface after committed-state verification of B0–B14 and all 30 Phase 1 non-DEFERRED R3 scenarios.

This qualification means the runtime can mechanically observe Browser state, preserve exact identity and grounding, compare snapshots, evaluate typed predicates, expose version pressure, and perform the qualified semantic mutations with append-only receipts while preserving hard no-rebind/no-hidden-retry/no-task-judgement boundaries.

It does **not** mean Browser task success is decided by the runtime, nor does it promote Phase 2 vision-only actionability or Phase 3 native browser/OS UI.

## 2. B0–B14 matrix

| Gate | Result | Mechanical evidence |
|---|---|---|
| B0 surface isolation | PASS | `run_mode=ptc` experiment arm exposes `browser_perceive` + `browser_action` while legacy `playwright_exec/playwright_test` are absent. |
| B1 scope model | PASS | page/document/frame scope facts, generation transitions, explicit parentage. |
| B2 grounded snapshot | PASS | integrity-bound/session-fenced/retained GroundingRefs and explicit completeness. |
| B3 identity continuity | PASS | reorder continuity; replacement/duplicate ambiguity never silently rebinds. |
| B4 multi-sensor honesty | PASS | DOM/AX source-qualified conflict wire; unresolved canonical conflicts become null; ambiguous identity is not force-fused. |
| B5 diff semantics | PASS | `snapshot_pair_net`, scope/document/sensor-contract comparability, incomplete fields degrade honestly. |
| B6 semantic actions | PASS | click/fill/select/navigate/scroll accept semantic targets only; v0.1 scroll is `semantic_object` only. |
| B7 TOCTOU/version | PASS | fresh pre-dispatch observation + exact identity re-resolution + expected version guard; stale/ambiguous rejects. |
| B8 retry/atomicity | PASS | unknown-idempotency mutation is single-dispatch; real Chrome ack-loss after actual effect never replays; post-effect remains observable. |
| B9 append-only receipts | PASS | running/terminal revisions are immutable, per-action receipt sequence monotonic, before/after/dispatch grounding retained. |
| B10 predicate honesty | PASS | typed three-state predicate and read-only polling wait; timeout/observer error/coverage gaps remain factual. |
| B11 blind spots/boundaries | PASS | structural blind spots explicit; qualified Page events/new-page facts are mechanical and explicitly non-exhaustive. |
| B12 authority lint | PASS | model surface contains no task priority/best/recovery/completion policy and no selector/XPath/coordinate/CDP physical locator inputs. |
| B13 deterministic adversarial suite | PASS | exact 30/30 non-DEFERRED R3 scenarios map to concrete ground-truth pytest fixtures. |
| B14 repo qualification | PASS | committed live suite, expanded adjacency, security, Ruff, Pyright and full `ci_gate` all green. |

## 3. R3 deterministic implementation coverage

The machine-checked map in `tests/unit/test_smc_browser_phase1_qualification_v01.py` covers exactly:

`R3-01..R3-13, R3-15..R3-28, R3-30..R3-32`

That is **30/30 Phase 1 non-DEFERRED scenarios**. `R3-14` and `R3-29` are deliberately excluded:

- `R3-14`: vision-only semantic target actionability — Phase 2 DEFERRED.
- `R3-29`: native browser chrome / OS UI — Phase 3 DEFERRED.

The meta-test verifies every evidence node points to an existing pytest test function; live evidence supplements rather than replaces deterministic fixtures.

## 4. Three B-QUAL boundary decisions

### 4.1 Root-level scroll

The early Profile listed `page / document / frame / region` together with `semantic_object`, while `scroll.version_scopes` were only `object | snapshot`.

That was mechanically inconsistent: `object` versioning applies to SemanticObject, while strict snapshot versioning must reject a distinct fresh observation. B-QUAL therefore corrected the Phase 1 v0.1 contract to:

```text
scroll.target_kinds = [semantic_object]
scroll.version_scopes = [object, snapshot]
```

No B-STALE semantics were weakened. Root-level scroll requires a future separately frozen scope/resource version contract and is not part of Phase 1 v0.1.

### 4.2 Transport ambiguity / partial side effect

A qualification-only actuator wrapper performs the **real Chrome dispatch once** and then deterministically drops the acknowledgement by raising a timeout. The DOM effect is real before the injected transport ambiguity.

Observed result:

- physical effect happened exactly once;
- receipt terminates `failed` with `dispatch_outcome_ambiguous`;
- `automatic_retry_performed=false`;
- post-action snapshot/diff still records the observed side effect;
- no replay occurs.

This closes the Phase 1 R3-19/R3-20 obligation without introducing retry policy.

### 4.3 Boundary events

The narrow actuator now enables Page events and mechanically recognizes the following reliable Phase 1 facts when observed:

- `new_window` from `Page.windowOpen`;
- `download_started` from `Page.downloadWillBegin`;
- `dialog_opened` from `Page.javascriptDialogOpening`;
- `new_page` from target-list new page IDs;
- existing `navigation_started` acknowledgement for explicit navigate.

Every event remains `complete=false`, and ActionReceipt retains `boundary_detector_non_exhaustive`. Missing events are therefore never interpreted as proof that no boundary event occurred.

Native permission UI is not promoted into Phase 1; `permission_prompt` remains schema vocabulary for a future qualified detector, while R3-29 stays DEFERRED.

## 5. Committed live qualification

All runs were executed from implementation commit `a1a659e375dc8436eb71c30cb182f9651693a8ae`.

| Suite | Result | Result SHA256 |
|---|---|---|
| navigation | PASS | `81168752968887f26dbb741033bf97d6fcbea25730a79d3d8da4e09f9edf0c80` |
| SemanticDiff | PASS | `b0af595c5c392de494b243127f9ca60ae57624fd9f19a2dd04370680dd475915` |
| Predicate / Wait | PASS | `41b7ca20d9bbc938b4c0254660fddc16a15c78aac56da1f7eff90bae01732828` |
| VersionPressure | PASS | `51268ff3b5b9e31a92a167425a18746e01310749fa4b3b0f3c19dd2613d2d2ae` |
| Mutation / ActionReceipt | 18/18 behavior + 8/8 safety | `4946123962727323fb1c04ee537f390d179eb26e874a7f463e95adfd0c321808` |

Implementation evidence hashes:

- `src/llm_loop/browser/cdp_action_host.py`: `229e83caac450fb7285a6d75fc5d4a0dbc23fd5e5201bfb92b600a4ad34c778d`
- `scripts/qualification/smc_browser_live_action_receipt.py`: `c6cc3beafe0b475520c18dab57dacbddefc84243d35ee2decf0379e7757c5bd9`
- `tests/unit/test_smc_browser_phase1_qualification_v01.py`: `a881e40aed0679747d4b05af2e8a52c504bf5aa76502f55ed736b4f6676b0340`
- `docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json`: `965968f28b71eae4244476fc74ea6faff1d3bffd0799d3e5e5f1c1a7c72a6000`

## 6. Repository gates

Committed implementation verification:

- expanded Browser/SMC adjacency: **186 PASS**;
- whole-tree security: **1668 tracked files PASS**;
- Ruff: **PASS**;
- env-pin: **545 test files / 0 undeclared**;
- Pyright: **0 errors / 0 warnings / 0 informations**;
- tier0: **PASS**;
- full xdist pytest: **PASS**;
- architecture guard report: **PASS**;
- full `scripts/ci_gate.sh`: **exit 0**.

## 7. Explicit non-claims

Phase 1 qualification does not claim:

- root-level page/document/frame/region scroll;
- event-driven wait semantics;
- wait cancellation surface;
- exhaustive popup/download/dialog/permission detection;
- native permission-prompt manipulation or browser chrome control;
- vision-only target actionability;
- automatic recovery, retry, locator fallback, or target substitution;
- runtime judgement of task value, semantic success, or task completion;
- Browser model A/B quality. No model was invoked during B-QUAL.

## 8. Final Phase 1 statement

> **Browser Phase 1 v0.1 is QUALIFIED for the structural SMC surface: the runtime can see mechanically, preserve and compare grounded state, wait on typed facts, reject stale writes, dispatch the qualified semantic actions exactly once, and retain honest append-only evidence without taking semantic strategy away from the model.**

A real model A/B experiment may be opened as a separate next phase. It must use the isolated SMC Browser surface and must not reinterpret this qualification as model-quality evidence.
