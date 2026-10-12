# MF-5 Model-Friendly Semantic Operation — Paired A/B Qualification v0.1

Status: **FROZEN BEFORE MODEL EXECUTION**

## Question
Holding the current Browser backend at the same Git SHA, does the model-friendly surface reduce model interaction amplification without reducing correctness or weakening authority/safety boundaries?

## Arms
- **A legacy-interface control:** same current backend, but `browser_semantic_operation` exposes the frozen legacy `clauses` provider schema and returns the legacy full aggregate receipt.
- **B model-friendly treatment:** same backend, current `steps` schema + compact receipt + exact hydration refs.

Only the model-facing interface differs. Both arms inherit the same exact grounding, version guard, typed Predicate, single-dispatch, MF-4 boundary halt, actuator and fixture mechanics.

## Matrix and order
Six task slots, each paired A/B once. Pair order alternates A-first/B-first to reduce warm-order bias. Runs remain strictly serial against the single pre-existing Ornith server on 8901. Every row gets a fresh LFL session, DATA_DIR and Chrome profile.

Tasks are byte-identical to FC2-B: click_commit, fill_submit, delayed_wait, each repeated twice. max rounds=12; no selective replay.

## Frozen model surface
Exactly: `browser_semantic_operation`, `get_tool_schema`, `read_evidence`. No atomic Browser tools are model-visible.

## SRTA denominator
Preregistered from the fixture/task, not model trajectories:
- click_commit = 2 semantic decision points (navigate; choose/click Commit choice)
- fill_submit = 3 (navigate; set Project code; choose/click Save code)
- delayed_wait = 3 (navigate; declare wait condition; choose/click Finalize)
Internal captures, exact grounding, version checks and wait samples are not semantic decision points.

## Hard gate
Both arms independently require 6/6 external task oracle, no INFRA/TIMEOUT/INVALID, zero operation FAILURE/ERROR, zero automatic retry, zero task-completion violation, zero direct atomic Browser calls. These gates are not traded for efficiency.

## Efficiency gate
All are preregistered and conjunctive:
1. B `(get_tool_schema + read_evidence)` total < A;
2. B `(operation arg chars + model-visible operation result chars)` total < A;
3. B total model rounds <= A.

Tokens/cache/SRTA are reported diagnostics; SRTA is computed from the frozen denominator above. A single stochastic token metric cannot override the hard gate.

## Evidence discipline
No row replay, gate weakening or in-place repair after measured execution starts. Any interface/code change requires a new protocol identity and fresh full matrix. MF-5 PASS is local model-behavior qualification only, not deployment/stability; MF-6 independent repeat remains required.
