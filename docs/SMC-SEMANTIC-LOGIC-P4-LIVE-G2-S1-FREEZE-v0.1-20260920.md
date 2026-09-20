# SMC P4-LIVE ActionRef — GREEN-2 Slice S1 Freeze v0.1

> Date: 2026-09-20
>
> Status: **G2-S1 QUALIFIED / STRICT BINDING + PREPARED BRIDGE ONLY / ZERO DISPATCH**
>
> Exact planning parent: `0d868fe074a8cad746fffbd7d771c24100eac74a`
>
> GREEN-1 parent of plan: `62529729c5888ae863a1fe1715e2590a9519d182`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. Slice boundary

This slice implements only the G2-S1 foundation frozen in
`GREEN2-PLAN.v0.1.json`:

1. a strict ActionRef-only ToolExecutionJournal binding authority;
2. an immutable durable ActionRef PREPARED execution bridge;
3. an explicit PREPARED/no-Browser-running recovery classification that is
   mechanically no-dispatch/no-replay.

This slice does **not** register or expose any ActionRef mutation tool and does not
call `BrowserActionAdapter.execute`, `CdpBrowserMutationActuator`, or any Browser
physical-dispatch path.

R10/R11/R15/R16 therefore remain RED at the frozen end-to-end matrix level: the
foundation now exists, but no typed ActionRef mutation path consumes it yet.  R12-R14
and R17-R19 are untouched.  The first dispatch-capable production boundary remains
G2-S4.

## 2. Strict ActionRef effect-binding authority

`src/llm_loop/core/tool_execution_journal.py` now exposes a dedicated
`current_action_ref_effect_binding_authority()` context manager and immutable
`ActionRefEffectBindingView`.

The new authority is intentionally stricter than the existing
`current_effect_mutation_authority()`:

- no current ToolExecutionJournal binding -> reject;
- revoked binding -> reject;
- current session differs from binding session -> reject;
- canonical current workspace differs from binding workspace -> reject;
- current run generation differs from binding origin generation -> reject;
- empty or no-longer-active origin run generation -> reject.

The exact binding and active-run guards are held across the caller's short
mechanical preparation window so timeout/revocation/run turnover cannot race the
durable PREPARED write.

The legacy authority contract is deliberately unchanged: existing direct/control-plane
callers with no ToolExecutionJournal binding still receive the historical permissive
behavior from `current_effect_mutation_authority()`.  The stricter rule applies only to
future ActionRef execution code.

## 3. Durable PREPARED execution bridge

`src/llm_loop/browser/action_ref_execution.py` adds a non-dispatching immutable store
with schema:

`smc.browser_action_ref_execution_binding.v0.1`

The bridge derives the complete outer identity exclusively from the current strict
ToolExecutionJournal binding.  Its `prepare_current()` API does not accept caller/model
copies of:

- session id;
- execution id;
- tool-call id;
- workspace root;
- origin run generation.

One PREPARED record joins:

- exact `execution_id` / `tool_call_id` / tool name / round;
- exact session/workspace/origin run generation;
- ActionRef;
- ActionRef binding id and binding digest;
- exact hidden GroundingRef;
- deterministic inner action id;
- expected version;
- ActionRef-observed Browser target id SHA-256.

The store is create-only and integrity protected.  The exact same execution/binding
facts are idempotent; the same `execution_id` cannot be rebound to another ActionRef,
GroundingRef, inner action id, version, or Browser target.

A PREPARED durability failure propagates fail-closed and no successful bridge object is
returned.

No verb-specific semantic payload or fill plaintext is duplicated into the bridge.

## 4. PREPARED/no-running recovery boundary

G2-S1 deliberately does not inspect Browser receipt storage; exact running/terminal
receipt correlation belongs to G2-S3.

The bridge only exposes the explicit mechanical classification:

`classify_prepared_without_browser_running(execution_id)`

for the already-proven crash cut "PREPARED exists, Browser running receipt does not".
The result fixes:

- `state = prepared_before_browser_running`;
- `executed = false`;
- `dispatch_attempted = false`;
- `auto_reexecuted = false`.

It does not search for a Browser receipt, does not infer a target, and cannot replay.
G2-S3 may consume this classification only after exact receipt absence is mechanically
proven.

## 5. Deterministic focused qualification

Focused suite:

`tests/unit/test_smc_p4_live_g2_s1.py`

The 11 deterministic cases cover:

- unbound ActionRef rejection while legacy direct authority remains allowed;
- exact bound execution identity exposure;
- timeout/cancel revocation rejection;
- session/workspace/run-context drift rejection;
- inactive origin run rejection;
- PREPARED outer identity sourced only from the current ToolExecutionJournal binding;
- exact PREPARED field round-trip;
- same-execution idempotence;
- same-execution rebind conflict;
- injected PREPARED write failure;
- PREPARED/no-running no-dispatch/no-replay;
- source-level absence of Browser adapter/actuator dispatch dependency.

Focused result: **11/11 PASS**.

## 6. Machine evidence

Evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S1-v0.1-20260920/EVIDENCE.json`

SHA-256:

`8b8e7605359824af9a84d97601f459dfd05e97162a994d19fa0693b07a131d95`

Machine qualification reports:

- `qualified_s1_stop = true`;
- focused S1 tests = **11/11 PASS**;
- GREEN-1 20-row matrix still passes;
- R01-R09/R20 remain GREEN;
- R10-R19 all remain RED end-to-end;
- R10-R19 frozen taxonomy remains intact;
- typed ActionRef mutation tools registered = **0**;
- Browser-dispatch dependency in the S1 bridge = **false**;
- first physical-dispatch boundary crossed = **false**;
- real Browser actions = **0**;
- model requests = **0**.

## 7. Existing contracts deliberately preserved

S1 does not change:

- GREEN-1 ActionRef issuer/resolver/perception annotation behavior;
- `browser_action_ref_enabled` default-OFF authority;
- existing Browser semantic compiler/action-id semantics;
- BrowserAction receipt/reservation behavior;
- CDP mutation actuator target binding;
- main LoopEngine provider/tool projection;
- `current_tool_discovery_scope` behavior;
- legacy Browser mutation tool registration;
- live provider/runtime configuration.

The frozen end-to-end RED taxonomy therefore remains the authority for R10-R19 until
the later slices actually connect the foundation to a typed ActionRef mutation path.

## 8. Stop boundary

This slice stops before G2-S2.

Not implemented or authorized here:

- exact ActionRef-observed Browser target precondition (S2);
- ActionRef -> hidden GroundingRef -> existing semantic compiler facade (S2);
- Browser running/terminal receipt ↔ outer WAL crash correlation (S3);
- any typed ActionRef mutation tool (S4);
- any provider/discovery/execution canary isolation change (S5);
- real Browser action;
- model request;
- deploy/restart/merge main;
- Web/Feishu/8901 changes;
- live provider/runtime config mutation.

The next production slice requires a separate human checkpoint and must start from this
committed S1 freeze; it must not silently continue into G2-S2.
