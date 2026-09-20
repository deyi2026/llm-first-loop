# SMC P4-LIVE ActionRef — G2-S4 GREEN Freeze v0.1

> Date: 2026-09-20
>
> Status: **QUALIFIED S4 / DEFAULT-OFF / FAKE-ONLY / STOP BEFORE S5 PROVIDER-SURFACE ISOLATION**
>
> Exact parent G2-S3: `b0b3e1da438e2e3c248390f4cbe7c666a23e10cd`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. What S4 adds

S4 is the first production slice that can compose the already-qualified ActionRef safety
primitives into a Browser mutation path, but the capability remains separately gated and
default OFF.

Production source delta is exactly three files:

1. `src/llm_loop/config.py`
   - adds independent `browser_action_ref_mutation_enabled: bool = False`;
   - loads only from `LFL_BROWSER_ACTION_REF_MUTATION_ENABLED`;
   - does not overload GREEN-1 ActionRef projection or legacy Browser mutation enablement.
2. `src/llm_loop/tools/builtin/browser_action_ref_mutation.py`
   - adds one shared mechanical `ActionRefMutationKernel`;
   - adds five closed-schema typed facades:
     - `browser_semantic_click(action_ref)`;
     - `browser_semantic_fill(action_ref,text,mode)`;
     - `browser_semantic_select(action_ref,value)`;
     - `browser_semantic_scroll(action_ref,delta_pages)`;
     - `browser_semantic_navigate(action_ref,url)`.
3. `src/llm_loop/factory.py`
   - constructs/registers the five typed tools only inside existing Browser mutation opt-in,
     with an existing ActionRef binding store and the separate S4 mutation flag enabled;
   - leaves the three legacy Browser mutation tools unchanged for S5 to isolate by scope.

No S5 provider/discovery/execution scope isolation is implemented in this slice.

## 2. Frozen execution order

For every typed call the shared kernel performs only this authority order:

1. require a live, non-revoked `ToolExecutionJournal` ActionRef effect binding;
2. exact ActionRef resolution with binding-owned session/workspace/run generation and the
   existing Browser runtime/TTL/integrity/kind authority;
3. delegate the hidden byte-identical GroundingRef to the qualified S2 compiler bridge;
4. persist the S1 immutable PREPARED execution bridge;
5. arm the S3 exact Browser-receipt cursor before Browser entry;
6. sticky-bind the exact ActionRef-observed Browser target hash;
7. call the existing `BrowserActionAdapter.execute()` unchanged.

The existing BrowserActionAdapter therefore remains canonical for fresh version/stable
identity checks, dispatch grounding, durable running receipt, effect-mutation authority,
one physical dispatch attempt, and terminal receipt.

There is no name/selector/similarity/latest/successor search, automatic re-observation,
retry, or target rebind in the S4 module.

## 3. Default-OFF / exposure boundary

S4 deliberately separates three authorities:

- Browser perception / ActionRef annotation;
- legacy Browser mutation capability;
- new ActionRef mutation composition.

`browser_action_ref_mutation_enabled` defaults to false. Merely landing S4 therefore does
not expose the five typed tools in ordinary runtime configuration. S5 remains responsible
for making an explicit `current_tool_discovery_scope` an actual main provider/discovery/
execution boundary and hiding the three legacy Browser mutation tools inside the P4-LIVE
canary domain.

## 4. Deterministic fake-only qualification

Focused S4 qualification currently collects and passes **22/22** tests. It proves:

- all three S4 structural contracts are present;
- the mutation flag is distinct and default OFF, and explicit config parsing works;
- exactly five closed ActionRef-only typed schemas exist;
- direct/unbound calls are zero-dispatch;
- already-revoked calls are zero-dispatch;
- revocation after PREPARED but before physical authority remains zero-dispatch;
- a valid bound click persists PREPARED + receipt cursor, sticky-binds the exact target,
  produces running + terminal receipts, and performs exactly one fake dispatch;
- duplicate exact request physically dispatches at most once;
- observed target A / actuator target B rejects before physical dispatch;
- stale observation/version rejects through the existing guard;
- kind/session/workspace/run/runtime/TTL/integrity ActionRef failures are zero-dispatch;
- all five typed facades reach only the deterministic fake actuator when properly bound;
- source order is PREPARED -> receipt cursor -> sticky target bind -> BrowserActionAdapter;
- crash immediately after PREPARED recovers as no-dispatch/no-replay;
- crash after durable running receipt recovers as outcome-unknown/no-replay;
- exact terminal Browser receipt with missing outer finished fact settles the outer WAL
  without a second physical dispatch.

No real Browser action or model request was made.

## 5. S4 deterministic 20-row matrix

The S4 machine qualifier overlays the new typed-path evidence onto the frozen P4-LIVE
contracts without rewriting historical RED artifacts.

At the S4 stop boundary:

- **R01-R12: GREEN**;
- **R13: RED / intentionally deferred to G2-S5** with frozen code
  `main_provider_legacy_browser_surface_gap`;
- **R14-R20: GREEN**.

The S4-specific GREEN evidence for the newly composed execution rows is mechanically tied
to named focused tests:

- R10 — strict ToolExecutionJournal binding / unbound zero-dispatch;
- R11 — post-PREPARED revocation zero-dispatch;
- R12 — perception-target / actuator-target mismatch zero-dispatch;
- R14 — deterministic duplicate exact request at-most-once;
- R15 — PREPARED bridge + cursor before existing Browser entry;
- R16 — PREPARED crash cut no-dispatch/no-replay;
- R17 — running/no-terminal crash cut unknown/no-replay;
- R18 — exact terminal receipt outer-WAL settlement/no replay;
- R19 — stale/version/target guard zero-dispatch.

R01-R09/R20 remain supported by the existing GREEN-1 contracts. The frozen parent matrix
is retained as historical evidence; it is not mutated to pretend that earlier phases knew
about the S4 typed path.

## 6. Regression interpretation

Broad Browser/ActionRef/S1/S2/S3/WAL/run-generation/P4-FCR qualification passes after
excluding exactly three historical phase assertions whose sole purpose was to prove that
production wiring did **not yet exist**:

- S2: hidden bridge not referenced from factory;
- P4-FCR preflight: no typed production Browser mutation wiring;
- P4-FCR v0.2: no typed production Browser mutation wiring.

Those assertions are intentionally superseded by S4 and were not edited to rewrite
history. All adjacent behavioral/safety tests in those suites remain GREEN. Independent
factory/config/capability/subagent tests are also GREEN.

Full tracked-tree security scan: **2077 files PASS**.

Ruff: PASS. Pyright: 0 errors / 0 warnings. `git diff --check`: PASS.

## 7. Machine evidence

Machine runner:

`evals/smc_semantic_logic_p4_live/run_green2_s4_qualification.py`

Evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S4-v0.1-20260920/EVIDENCE.json`

Evidence SHA-256:

`f0737cfaa8e8068d4a839d7cbad8f17f77bb50fd4230310866b81dedf5a0db1c`

S4 pre-GREEN structural expected-failure taxonomy:

`evals/smc_semantic_logic_p4_live/GREEN2-S4-EXPECTED-FAILURES.v0.1.json`

SHA-256:

`57c89032d37bd9fca58f2039ef0940f23ee8f16dd42f6ce8a9d229650e7bbb41`

The machine evidence currently reports:

- `qualified_s4_stop = true`;
- focused 22/22 PASS;
- S4 matrix qualified except intentionally deferred R13;
- frozen parent R13 exact RED preserved;
- inherited S1/S2/S3 behavioral subset PASS;
- exact production source scope = three S4 files;
- exact worktree imports = true;
- default exposure OFF;
- S5 scope logic not added to the mutation module;
- real Browser actions = 0;
- model requests = 0;
- live config mutations = 0;
- deployment actions = 0.

## 8. Stop boundary

S4 stops before G2-S5.

Not performed here:

- main provider projection filtering;
- `get_tool_schema` / actual execution scope enforcement changes;
- P4-LIVE canary provider visibility;
- real Browser action;
- model request;
- deploy/restart;
- merge main;
- Web/Feishu/8901 change;
- live provider/runtime config mutation.

G2-S5 must begin from the exact committed S4 freeze and close only R13 before any live
P4-LIVE canary authorization.
