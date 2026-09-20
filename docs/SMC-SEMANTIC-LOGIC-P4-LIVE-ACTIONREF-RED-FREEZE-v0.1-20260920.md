# SMC Semantic Logic P4-LIVE ActionRef — RED Freeze v0.1

> Date: 2026-09-20
>
> Status: **RED-ONLY QUALIFIED / NO PRODUCTION GREEN / NO LIVE EXECUTION**
>
> Exact protocol/design base: `e946eab26032aa4faa6698a3244ebd30c836cce1`
>
> Parent P4-FCR v0.2 QUALIFIED result: `66f8d6147a67c4b439ca930149359674e500ba68`

## 1. Scope

This freeze implements the twenty deterministic P4-LIVE ActionRef RED contracts
`P4L-R01` through `P4L-R20` defined by the frozen protocol.  The candidate contains
tests, qualification harness, expected-failure taxonomy, and evidence only.

No production `src/` file is modified.  No ActionRef GREEN implementation exists in
this phase.  No Browser action, model request, deploy, restart, merge, Web/Feishu/8901
change, or provider/runtime live-config mutation was performed.

The RED harness deliberately separates two checks:

1. a deterministic production probe must first match the frozen missing-capability
   taxonomy; a harness/import/setup/path failure is classified as `harness_error` and
   cannot qualify;
2. the actual pytest contract then remains RED because the matching production
   capability is absent.

The qualification runner returns success only when all twenty probes match their
expected taxonomy and pytest fails exactly `P4L-R01` through `P4L-R20` in order.

## 2. Frozen expected-failure taxonomy

| RED | expected production-missing code |
|---|---|
| P4L-R01 | `actionref_issuer_absent_after_persist` |
| P4L-R02 | `actionref_exact_resolver_absent` |
| P4L-R03 | `actionref_session_fence_absent` |
| P4L-R04 | `actionref_workspace_fence_absent` |
| P4L-R05 | `actionref_run_lifetime_fence_absent` |
| P4L-R06 | `actionref_expiry_fence_absent` |
| P4L-R07 | `actionref_browser_incarnation_fence_absent` |
| P4L-R08 | `actionref_kind_fence_absent` |
| P4L-R09 | `actionref_integrity_fence_absent` |
| P4L-R10 | `actionref_effect_binding_requirement_absent` |
| P4L-R11 | `actionref_revocation_wiring_absent` |
| P4L-R12 | `browser_target_independent_first_bind_gap` |
| P4L-R13 | `main_provider_legacy_browser_surface_gap` |
| P4L-R14 | `actionref_inner_action_id_bridge_absent` |
| P4L-R15 | `predispatch_execution_bridge_absent` |
| P4L-R16 | `prepare_without_running_recovery_contract_absent` |
| P4L-R17 | `running_unknown_browser_correlation_absent` |
| P4L-R18 | `terminal_browser_outer_wal_correlation_absent` |
| P4L-R19 | `actionref_version_guard_delegation_absent` |
| P4L-R20 | `actionref_disabled_compatibility_gate_absent` |

Machine taxonomy:
`evals/smc_semantic_logic_p4_live/EXPECTED-FAILURES.v0.1.json`

SHA-256:
`96a60885d7a8298082d457d7ba4119ca53a13427c17e8d95b53ff65c333cd4e9`

## 3. RED qualification result

Machine evidence:
`evals/smc_semantic_logic_p4_live/results/P4-LIVE-RED-v0.1-20260920/EVIDENCE.json`

SHA-256:
`cb8e7f7d8a2216e68c378680331bdc86249672d4c75f8d87708330fdaddac22a`

Frozen result:

- row count: **20**;
- expected RED rows: **P4L-R01 through P4L-R20 exactly**;
- all expected-failure taxonomies match: **true**;
- all rows remain RED: **true**;
- harness errors: **0**;
- pytest failure set/order exact: **true**;
- real Browser actions executed: **0**;
- model requests sent: **0**;
- production `src/` modified: **false**;
- RED freeze classifier: **QUALIFIED**.

This means the **RED phase** is qualified.  It does not mean P4-LIVE production is
qualified or implemented.

## 4. Three P0 gaps independently reproduced

### P0-A — independent Browser target first-bind gap

The deterministic probe instantiates the existing read-only perception host and mutation
actuator with independent fake CDP target lists and no configured target id.  The
perception side resolves `target-A`; the still-unbound actuator independently resolves
`target-B`.  No physical dispatch occurs.

This reproduces the audit finding that observation target identity is not mechanically
carried into the actuator's first binding.

Mapped RED: **P4L-R12**.

### P0-B — no ToolExecutionJournal ↔ Browser ActionReceipt pre-dispatch bridge

Production inspection confirms:

- ToolExecutionJournal owns outer `execution_id`, `tool_call_id`, run ownership and
  generic effect authority;
- BrowserActionReceiptStore / BrowserActionAdapter own Browser `action_id`, dispatch
  grounding, running receipt and terminal receipt;
- the two systems do not durably join
  `execution_id/tool_call_id ↔ ActionRef ↔ GroundingRef ↔ action_id` before physical
  Browser dispatch.

Mapped RED: **P4L-R15**, with recovery consequences locked by **R16-R18**.

### P0-C — main provider projection does not honor discovery scope

The main `LoopEngine._project_request_tools()` starts from the complete registry and does
not read `current_tool_discovery_scope`.  `get_tool_schema` does honor that scope, while
the existing factory registers the three legacy Browser mutation tools when Browser
mutation is enabled:

- `browser_action`;
- `browser_semantic_execute`;
- `browser_semantic_operation`.

Therefore discovery scope alone cannot isolate the P4-LIVE canary provider surface.

Mapped RED: **P4L-R13**.

## 5. Existing production primitives preserved as prerequisites

The RED probes also establish that existing production safety primitives remain present
and should be reused rather than reimplemented:

- exact GroundingRef hydration round-trips the exact ref and is session fenced;
- existing Browser semantic compiler derives deterministic inner `action_id` from the
  exact GroundingRef + verb + semantic args;
- Browser receipt reservation rejects duplicate `action_id` before a second physical
  dispatch;
- ToolExecutionJournal has generic run ownership / timeout-cancel revocation and
  `started_outcome_unknown` recovery with `auto_reexecuted=false`;
- Browser version assessment rejects changed document generation as `stale`, with
  `automatic_refresh_performed=false` and `silent_rebind_performed=false`.

The RED state is precisely the missing ActionRef ownership / causality / target-binding
adapter around those existing primitives.

## 6. Adjacent GREEN verification

The exact-baseline candidate ran the broad adjacent unit suites covering:

- Browser perception, exact recovery, timeout observation and version pressure;
- Browser semantic execute / args normalization / semantic diff;
- Browser action / CDP mutation host;
- Browser Phase-1 profile/spec/qualification;
- Browser typed waits and predicate waits;
- run-generation ownership / ToolExecutionJournal behavior;
- capability discovery-scope behavior;
- P4-FCR preflight and P4-FCR v0.2 protocol tests.

The aggregate adjacent run completed **GREEN (exit 0)**.  The repository side-effect
auditor emitted its existing non-blocking warnings about test fixture provider URLs; no
new blocking finding was introduced.

Static candidate checks also pass:

- Ruff: PASS;
- Pyright: **0 errors / 0 warnings**;
- taxonomy/evidence JSON parse: PASS;
- `git diff --check`: PASS.

## 7. Freeze boundary

This phase stops before the first production GREEN.

Not authorized or performed here:

- adding a production ActionRef store/issuer/resolver;
- adding the five production ActionRef mutation tools;
- changing Browser target binding;
- adding the ToolExecutionJournal ↔ Browser receipt bridge;
- changing main provider projection;
- running a P4-LIVE Browser mutation;
- deployment, restart or main merge.

The next phase requires a separate human decision and should start from this RED freeze,
not by redesigning against a newer main.
