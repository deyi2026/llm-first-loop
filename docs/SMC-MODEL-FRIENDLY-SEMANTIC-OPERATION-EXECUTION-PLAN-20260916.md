# SMC Model-Friendly Semantic Operation — Execution Plan — 2026-09-16

Status: **MF-5 v0.1 COMPLETE / NOT QUALIFIED / COGNITION-PRESERVING CORRECTION ADOPTED / MF-6 DEFERRED**

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
| 5.2 | Cognition-preserving actuation qualification | design + qualification | normal reasoning -> natural semantic call; protocol-repair taxonomy + fresh hard Gate | model still reasons about tool grammar |
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
