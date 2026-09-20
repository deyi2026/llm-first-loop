# SMC P4-LIVE ActionRef — G2-S5 GREEN Freeze v0.1

> Date: 2026-09-20
>
> Status: **QUALIFIED S5 / R01-R20 DETERMINISTIC GREEN / STOP BEFORE LIVE CANARY**
>
> Exact parent G2-S4: `44b38540691f7cddc1d34cf709dc92bb8e6b0e66`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. Objective closed

G2-S5 closes the sole remaining deterministic P4-LIVE gap, R13:

`main_provider_legacy_browser_surface_gap`

The fix makes one existing request-local authority, `current_tool_discovery_scope`, a
consistent mechanical boundary across all three model-facing/callable channels:

1. main LoopEngine provider schema projection;
2. `get_tool_schema` catalog/exact discovery;
3. actual `ToolRegistry.execute()` dispatch.

`scope=None` remains the exact legacy full-registry behavior.

## 2. Exact P4-LIVE canary surface

The canary scope is not inferred from task text and not guessed from current registry
contents. It is frozen from two already-qualified sources:

- the P4 shared Browser read-only surface: perception + five typed waits +
  `get_tool_schema`;
- the five G2-S4 typed ActionRef mutation facades.

Exact scope: **12 tools**.

```text
browser_perceive
browser_wait_scope_url
browser_wait_scope_ready
browser_wait_scope_count
browser_wait_object_state
browser_wait_object_text
get_tool_schema
browser_semantic_click
browser_semantic_fill
browser_semantic_select
browser_semantic_scroll
browser_semantic_navigate
```

The three legacy Browser mutation surfaces are mechanically excluded:

```text
browser_action
browser_semantic_execute
browser_semantic_operation
```

Production authority is in:

`src/llm_loop/tools/p4_live_scope.py`

`P4_LIVE_CANARY_TOOL_SCOPE` is immutable. `p4_live_canary_tool_scope()` activates it only
for the current context and restores the prior scope on exit. Merely landing S5 does not
activate the canary.

## 3. Single mechanical scope authority

### 3.1 ToolRegistry

`ToolRegistry` now owns the common scope primitives:

- `current_scope_allows(name)`;
- `names_for_current_scope()`;
- `schemas_for_current_scope(lazy=False)`.

These read only `current_tool_discovery_scope`. No user text, model output, semantic
classification, provider identity, or Browser state participates in membership.

### 3.2 Provider projection

`LoopEngine._project_request_tools()` now starts from:

`registry.schemas_for_current_scope(...)`

instead of the full registry. Therefore a tool outside an explicit scope is never placed
in the provider tools array, even if it remains registered for compatibility elsewhere.

### 3.3 Discovery

`GetToolSchemaTool` already had correct explicit-scope behavior before S5. S5 preserves
that behavior but removes the duplicated membership logic: catalog listing now uses
`names_for_current_scope()` and exact lookup uses `current_scope_allows()`.

### 3.4 Execution

`ToolRegistry.execute()` now checks `current_scope_allows(call.name)` immediately after
validating `tool_call_id` and **before** tool lookup, health checks, argument processing,
safety/pipeline hooks, or tool execution.

An out-of-scope registered tool therefore returns a factual failure receipt and its
business `execute()` method is never called. Provider/schema hiding cannot be bypassed by
a hallucinated/stale direct tool declaration.

## 4. Legacy behavior

With `current_tool_discovery_scope=None`:

- `names_for_current_scope()` equals the full registry names;
- `schemas_for_current_scope()` equals the full registry schemas;
- `get_tool_schema` lists/reads all registered tools as before;
- direct `ToolRegistry.execute()` remains callable according to the historical registry,
  health, safety and tool-specific authorities.

S5 therefore changes only explicit scoped execution domains.

## 5. Context isolation

The scope remains a `ContextVar`, not shared mutable registry state. Deterministic tests
prove:

- nested P4-LIVE activation restores an outer explicit scope;
- an isolated context scoped to `{a}` cannot execute `b`;
- the surrounding context remains `None`/full registry;
- scope activation in one context does not mutate registry membership or another context.

This preserves existing subagent inheritance semantics while closing the main-loop bypass.

## 6. Pre-GREEN evidence

Before production edits, the S5 channel matrix was:

| Channel | State | Code |
|---|---|---|
| Main provider projection | RED | `main_provider_scope_bypass` |
| `get_tool_schema` discovery | GREEN prerequisite | `discovery_scope_already_enforced` |
| Direct ToolRegistry execution | RED | `registry_execution_scope_bypass` |
| Exact P4-LIVE scope authority | RED | `p4_live_canary_scope_authority_absent` |

Pre-GREEN production `src/` diff from exact S4 was zero.

Frozen taxonomy SHA-256:

`3c871676078ecf5ae26db3357b8d8146837cbf828589f52bfff0bd949ddfc594`

Pre-GREEN evidence SHA-256:

`44bf5464913e130bd8ec95217357a232e194a4036768d7ffcfa31363bc05e84e`

## 7. GREEN qualification

Focused S5 suite: **7/7 PASS**.

It proves:

- all four S5 structural/behavioral channels are qualified;
- exact 12-tool canary scope matches frozen evidence;
- all three legacy Browser mutation tools are excluded;
- main provider projection is exactly the registered intersection of the 12-tool scope;
- discovery catalog and exact lookup cannot surface legacy Browser mutations;
- direct registry execution cannot bypass the scope;
- scope=None preserves full discovery/schema/execution behavior;
- nested/context-isolated scope state restores correctly.

Broader qualification also passes:

- ToolRegistry core behavior;
- lazy schema behavior;
- registry pipeline;
- execute-many + pairing;
- engine reentrancy;
- capability wiring;
- subagent scope inheritance;
- tool eligibility;
- S1/S2/S3/S4 P4-LIVE behavior;
- Browser action/CDP/semantic/perception;
- ToolExecutionJournal effects/restart/run generation;
- factory/config.

The known historical S2 assertion whose sole purpose was to prove that the hidden bridge
was not yet referenced from factory remains excluded because S4 intentionally superseded
that historical condition; the historical test itself is not rewritten.

Ruff: PASS. Pyright: **0 errors / 0 warnings**. `git diff --check`: PASS.

Full tracked-tree security: **2084 files PASS**.

## 8. Final P4-LIVE deterministic matrix

S5 does not rewrite frozen S1-S4 evidence. The final machine qualifier verifies the exact
S4 evidence hash, inherits its already-qualified rows, and overlays only S5's R13 scope
proof.

Final pre-live deterministic state:

- **R01-R20: GREEN**.

R13 is GREEN because the same explicit scope now controls provider projection, schema
discovery and actual registry execution, with an exact frozen canary scope that excludes
all three legacy Browser mutation surfaces.

## 9. Machine evidence

S5 machine runner:

`evals/smc_semantic_logic_p4_live/run_green2_s5_qualification.py`

S5 evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S5-v0.1-20260920/EVIDENCE.json`

SHA-256:

`ce8d720a5ee361f88ea0d0089d2a1a378b1df4f7a094c82e7d0d2a597459291e`

The evidence requires:

- focused 7/7 PASS;
- exact S4 evidence hash `f0737cfaa8e8068d4a839d7cbad8f17f77bb50fd4230310866b81dedf5a0db1c`;
- final R01-R20 all GREEN;
- exact three-file production scope;
- exact-worktree module imports;
- provider/discovery/execution source-order checks;
- exact 12-tool scope and legacy-mutation exclusion;
- inherited behavior PASS;
- valid pre-live canary preflight;
- Browser actions = 0;
- model requests = 0;
- live config mutations = 0;
- deployment actions = 0.

## 10. Live-canary preflight freeze

Machine preflight:

`evals/smc_semantic_logic_p4_live/P4-LIVE-CANARY-PREFLIGHT.v0.1.json`

SHA-256:

`b1e3dd2d34313571023bb1042535d0bf186062191b6272b70fc0797fe32e3b0e`

Before any live canary, all of the following must be independently verified at the live
runtime boundary:

- explicit loopback Browser CDP URL;
- **explicit non-empty exact Browser target id** — initial canary must not rely on sole-page
  implicit first bind;
- Browser mutation enabled;
- ActionRef issuance enabled;
- S4 ActionRef mutation composition enabled;
- exact P4-LIVE 12-tool context explicitly active;
- legacy Browser mutation tools absent from provider/discovery;
- direct execution of those legacy mutation names denied in the scoped context.

This preflight file authorizes **zero** model requests and **zero** real Browser actions.
It is evidence, not activation.

## 11. Stop boundary

G2-S5 stops before the first live P4-LIVE canary.

Not performed in S5:

- model request;
- real Browser mutation;
- live config change;
- service restart/deploy;
- Web/Feishu/8901 change;
- merge to main.

The deterministic GREEN-2 implementation plan is now complete. A live canary is a new,
high-impact phase and requires an explicit human checkpoint using the exact committed and
remote-frozen S5 SHA.
