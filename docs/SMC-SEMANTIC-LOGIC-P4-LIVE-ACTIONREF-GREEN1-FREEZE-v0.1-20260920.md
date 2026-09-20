# SMC Semantic Logic P4-LIVE ActionRef — GREEN Phase 1 Freeze v0.1

> Date: 2026-09-20
>
> Status: **GREEN-1 QUALIFIED / NON-DISPATCHING CORE ONLY**
>
> Exact RED parent: `6730aae362a1f3c1a44088517e7da882820f368b`
>
> Frozen protocol/design parent of RED: `e946eab26032aa4faa6698a3244ebd30c836cce1`
>
> P4-FCR v0.2 QUALIFIED anchor: `66f8d6147a67c4b439ca930149359674e500ba68`

## 1. Phase boundary

GREEN Phase 1 implements only the mechanical, non-dispatching ActionRef core required
to turn the following frozen RED contracts GREEN:

- `P4L-R01` through `P4L-R09`;
- `P4L-R20`.

The following contracts deliberately remain RED with the same failure taxonomy frozen
in the RED phase:

- `P4L-R10` through `P4L-R19`.

This phase does **not** implement or expose an ActionRef Browser mutation path.  It does
not add the five typed mutation tools, does not bridge ToolExecutionJournal to Browser
ActionReceipt, does not fix Browser perception/actuator target first-binding, and does
not change main LoopEngine provider projection/discovery filtering.

No real Browser action or model request was executed during qualification.

## 2. Production capability added

### 2.1 Durable opaque binding authority

`src/llm_loop/browser/action_ref.py` adds an immutable production binding store using
the frozen `smc.browser_action_ref_binding.v0.1` record contract.

Bindings are indexed by a canonical mechanical binding fingerprint and contain only
the hidden authority facts required by the protocol, including:

- hashed owner session;
- hashed canonical workspace identity, with an explicit unbound-workspace sentinel;
- hashed origin run generation;
- Browser runtime generation and hashed runtime nonce;
- hashed observed Browser page/target token;
- exact observed snapshot id and scope;
- exact hidden GroundingRef;
- object/resource identity and target kind;
- source snapshot expiry and ActionRef expiry;
- SHA-256 integrity over the complete unsigned record.

ActionRef handles contain 128 bits of cryptographic randomness and are collision
checked.  The binding index makes repeated issuance of the same exact binding
idempotent within the frozen mechanical identity basis.

### 2.2 Persist-before-issue perception annotation

The existing `BrowserPerceptionAdapter.snapshot()` still constructs and persists its
canonical Browser snapshot first.  Only after `BrowserPerceptionStore.persist()` and
session-state persistence complete may an optional ActionRef issuer load the exact
persisted snapshot and annotate the model-visible projection.

The issuer produces:

- one resource/page ActionRef;
- object ActionRefs only when the persisted grounding identity basis is mechanically
  stable (`dom_physical_identity` or `ax_backend_physical_identity`).

Canonical GroundingRefs remain untouched in the persisted perception bundle and model
read/hydrate path.

### 2.3 Exact-only resolver

The resolver accepts only the exact ActionRef string and loads the one immutable record
derived from that handle.  It performs no capture, search, matching, ranking,
normalization, retry, latest lookup, successor substitution, or target rebinding.

Before returning the byte-identical stored GroundingRef it mechanically verifies:

- record integrity;
- session ownership;
- canonical workspace ownership;
- active/current run generation;
- ActionRef/source snapshot expiry;
- exact source snapshot availability;
- Browser runtime generation and nonce;
- requested object/resource kind.

The resolver is **not** wired to a mutation tool in this phase.

### 2.4 Default-OFF runtime authority

The existing Settings/configuration authority gains:

`browser_action_ref_enabled: bool = False`

with existing environment/config resolution for:

`LFL_BROWSER_ACTION_REF_ENABLED`

The default-off path constructs the same Browser perception adapter without an
ActionRef issuer, preserving the existing GroundingRef production projection.  The
flag does not imply or enable `browser_action_enabled`.

## 3. Frozen matrix result

Machine evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-GREEN1-v0.1-20260920/EVIDENCE.json`

SHA-256:

`7accf5cb3282412af2b1b03efa2f7732f93fb8f8bf371cc963df70a3f72d63ae`

Original RED expected-failure taxonomy remains:

`evals/smc_semantic_logic_p4_live/EXPECTED-FAILURES.v0.1.json`

SHA-256:

`96a60885d7a8298082d457d7ba4119ca53a13427c17e8d95b53ff65c333cd4e9`

Qualified matrix facts:

- row count: **20**;
- R01-R09/R20 GREEN: **true**;
- R10-R19 remain RED: **true**;
- remaining RED taxonomy preserved: **true**;
- harness errors: **0**;
- staged matrix pytest: **20/20 PASS**;
- real Browser actions: **0**;
- model requests: **0**.

## 4. R01-R09/R20 mechanical outcome

| ID | GREEN-1 outcome |
|---|---|
| R01 | exact persisted snapshot is the issuance barrier; projection receives stable 128-bit opaque ActionRefs; repeated exact binding issuance is idempotent |
| R02 | exact ActionRef returns the byte-identical hidden GroundingRef |
| R03 | cross-session resolution rejects with `action_ref_session_mismatch` |
| R04 | cross-workspace resolution rejects with `action_ref_workspace_mismatch` |
| R05 | wrong run generation and inactive/terminated run context reject with `action_ref_run_generation_mismatch` |
| R06 | ActionRef/source expiry rejects with `action_ref_expired`; ActionRef expiry is bounded by source snapshot expiry |
| R07 | changed Browser runtime generation/nonce rejects with `action_ref_browser_runtime_mismatch` |
| R08 | object/resource kind mismatch rejects with `action_ref_kind_mismatch` |
| R09 | binding-record tamper rejects with `action_ref_integrity_error` |
| R20 | ActionRef feature default OFF leaves existing GroundingRef projection unchanged |

## 5. R10-R19 intentionally still RED

The exact RED taxonomy remains the boundary for the next separately authorized phase:

- R10 `actionref_effect_binding_requirement_absent`;
- R11 `actionref_revocation_wiring_absent`;
- R12 `browser_target_independent_first_bind_gap`;
- R13 `main_provider_legacy_browser_surface_gap`;
- R14 `actionref_inner_action_id_bridge_absent`;
- R15 `predispatch_execution_bridge_absent`;
- R16 `prepare_without_running_recovery_contract_absent`;
- R17 `running_unknown_browser_correlation_absent`;
- R18 `terminal_browser_outer_wal_correlation_absent`;
- R19 `actionref_version_guard_delegation_absent`.

Adding the ActionRef alias core itself is not allowed to make these rows GREEN.  The
qualification probes therefore require actual mutation-tool/execution/provider wiring,
not merely the presence of ActionRef source code.

The three previously frozen P0s remain present by design at this stop boundary:

1. Browser perception host / mutation actuator independent first-bind target identity
   gap — R12 still RED;
2. ToolExecutionJournal ↔ Browser ActionReceipt durable pre-dispatch execution bridge
   absent — R15 still RED, with R16-R18 recovery consequences;
3. main LoopEngine provider projection does not isolate legacy Browser mutation surface
   merely via `current_tool_discovery_scope` — R13 still RED.

## 6. Qualification / regression status

The Phase-1 candidate has passed:

- staged P4-LIVE 20-row matrix: PASS;
- GREEN-1 machine classifier: QUALIFIED;
- Ruff: PASS;
- Pyright: **0 errors / 0 warnings**;
- `git diff --check`: PASS;
- broad Browser/GroundingRef/WAL/P4-FCR adjacent suites: GREEN;
- broader config/factory/default-off Browser perception regressions: GREEN.

The side-effect audit continues to print the repository's existing non-blocking fixture
URL warnings; no new blocking finding was introduced.

## 7. Explicit non-claims / stop boundary

This freeze does **not** claim that P4-LIVE is ready to mutate a Browser.

Not implemented or authorized here:

- `browser_semantic_click(action_ref)`;
- `browser_semantic_fill(action_ref, ...)`;
- `browser_semantic_select(action_ref, ...)`;
- `browser_semantic_scroll(action_ref, ...)`;
- `browser_semantic_navigate(action_ref, ...)`;
- ActionRef ↔ ToolExecutionJournal effect binding;
- exact observed-target actuator binding;
- durable pre-dispatch execution binding;
- Browser receipt ↔ outer WAL crash correlation;
- provider/discovery canary isolation;
- any physical Browser dispatch;
- live Browser canary, deploy, restart, or main merge.

The next phase must be separately authorized and must start from this committed GREEN-1
freeze rather than from a newer main or an expanded design.
