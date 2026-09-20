# SMC P4-LIVE ActionRef — GREEN-2 Execution-Safety / Provider-Surface Plan v0.1

> Date: 2026-09-20
> Status: **PLAN/AUDIT ONLY — NO GREEN-2 PRODUCTION EDITS**
> Exact planning base: `62529729c5888ae863a1fe1715e2590a9519d182`
> RED freeze: `6730aae362a1f3c1a44088517e7da882820f368b`
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. Decision summary

GREEN-1 correctly stopped before physical Browser mutation.  GREEN-2 should not be
implemented as one large "wire ActionRef into Browser" change.  The exact baseline has
four strong reusable safety primitives already in production:

1. ToolExecutionJournal run/attempt effect ownership and timeout revocation;
2. BrowserAction deterministic `action_id` reservation + running/terminal receipt
   journal;
3. exact GroundingRef semantic compiler + fresh pre-dispatch version/stable-target guard;
4. outer WAL recovery that never auto-replays an incomplete tool execution.

The missing work is the **mechanical join between those primitives** plus a canary-only
provider/execution surface.  The safe implementation order is therefore:

1. **G2-S1 — strict effect binding + durable execution-join foundation**;
2. **G2-S2 — exact Browser-target precondition + hidden GroundingRef compiler bridge**;
3. **G2-S3 — Browser receipt ↔ outer WAL crash correlator**;
4. **G2-S4 — five typed ActionRef mutation facades, default OFF**;
5. **G2-S5 — main provider/discovery/execution canary-surface isolation**.

G2-S1 through G2-S3 must remain non-dispatching.  G2-S4 is the **first production-code
boundary capable of a physical dispatch when explicitly enabled**, but it must still be
default OFF and qualified only with deterministic fake actuators.  No real Browser
action is authorized until all R10-R19 are GREEN and a separate live-canary checkpoint
is approved.

Machine-readable plan:

`evals/smc_semantic_logic_p4_live/GREEN2-PLAN.v0.1.json`

SHA-256:

`a47dd615e7cba13ec329666734644b6039e6505e2718f0f138ab21cd35be8d34`

## 2. Current exact production facts

### 2.1 R10/R11: reuse ToolExecutionJournal ownership; do not tighten legacy globally

`src/llm_loop/core/tool_execution_journal.py` already binds runtime model tool calls to
an `_EffectBinding` containing:

- session id;
- execution id;
- round;
- tool-call id / tool name;
- canonical workspace root;
- origin run generation;
- one shared authority lock + revocation bit.

`ToolRegistry` copies that binding into the tool worker context.  On timeout it calls
`revoke_effect_binding_for_call()` **before TIMEOUT becomes visible**.  The same lock is
held by `effect_mutation_authority()` during the physical mutation window, so a worker
cannot enter a new commit after revocation and timeout return.

However `current_effect_mutation_authority()` intentionally yields `True` when no
ToolExecutionJournal binding exists.  That is a compatibility contract for existing
direct/control-plane callers and must not be changed globally.

**GREEN-2 ruling:** introduce a strict **ActionRef-only** binding requirement.  New
ActionRef tools reject if the exact current ToolExecutionJournal binding is absent,
revoked, lacks an active origin run generation, or disagrees with ActionRef
session/workspace/run ownership.  Existing legacy tools retain current behavior.

This directly addresses:

- R10 `actionref_effect_binding_requirement_absent`;
- R11 `actionref_revocation_wiring_absent`.

### 2.2 R12: current Browser capture and actuator still have independent first binding

`CdpReadOnlyBrowserHost` and `CdpBrowserMutationActuator` are independent objects.
`CdpBrowserMutationActuator._resolve_target()` still uses:

1. already-bound target if present;
2. configured target id if present;
3. otherwise the sole page currently visible at actuator first use.

Therefore the frozen race remains real:

1. perception observes A and ActionRef binds A;
2. A disappears;
3. B becomes the sole page;
4. an unbound actuator can choose B.

The existing version guard protects page/document observation lineage, but it does not
mechanically carry the ActionRef-observed CDP target identity into actuator first bind.

**GREEN-2 ruling:** ActionRef mutation carries the GREEN-1
`browser_target_id_sha256` into the Browser mutation boundary.  Before first bind or
physical commit, the actuator must hash the candidate page id and compare it to the
expected value.  A mismatch/disappearance/websocket identity change rejects with zero
dispatch.  The legacy GroundingRef path keeps its current behavior.  A later live
P4-LIVE canary additionally requires an explicit non-empty configured target id.

This closes R12 without introducing target search or semantic rebinding.

### 2.3 R14/R19: compiler, duplicate guard, and stale guard already exist

`BrowserSemanticExecuteTool.compile_request()` already accepts an exact GroundingRef,
hydrates that exact ref, derives verb-specific mechanical action fields, and computes:

`action_id = sha256({verb, exact target_ref, normalized args})`

`BrowserActionReceiptStore.reserve()` is create-only for that `action_id`; an identical
request cannot physically dispatch twice.

`BrowserActionAdapter.execute()` already performs this pre-dispatch sequence:

1. reserve `action_id`;
2. fresh Browser capture;
3. `assess_version_precondition()` against the compiled expected version;
4. exact stable physical-identity lookup;
5. persist dispatch grounding;
6. append running receipt;
7. enter effect mutation authority;
8. one actuator dispatch attempt;
9. append terminal receipt.

**GREEN-2 ruling:** do not create a second compiler or stale-target algorithm.  Typed
ActionRef tools resolve the opaque ActionRef to the hidden byte-identical GroundingRef
and delegate that GroundingRef + model-selected verb + model-owned args to the existing
compiler/adapter.  The only additional precondition is the exact ActionRef-observed
Browser-target identity from §2.2.

This is the required bridge for:

- R14 deterministic inner action id + at-most-once dispatch;
- R19 existing stale/version/unstable-target guards.

### 2.4 R15-R18: outer WAL and Browser receipts are safe separately but not correlated

The outer ToolExecutionJournal persists:

`declared -> started -> finished -> receipt_committed`

and knows `execution_id`, `tool_call_id`, session, workspace, run generation and tool
name.  BrowserActionReceiptStore knows `action_id`, dispatch grounding, before/after
versions, running receipt and terminal receipt.

There is currently no durable record joining those identities before Browser dispatch.
On restart, `ToolExecutionJournal.recover()` safely behaves as follows:

- declared/no started -> executed=false;
- started/no finished -> `started_outcome_unknown`;
- all recovery receipts carry `auto_reexecuted=false`.

That is safe against replay, but it cannot distinguish:

- ActionRef execution prepared but Browser never reached running receipt;
- Browser running receipt exists but terminal outcome is unknown;
- Browser terminal receipt exists but outer WAL did not reach `finished`.

**GREEN-2 ruling:** add one immutable Browser execution-binding record **before the
existing Browser running/dispatch window**.  It is not a second run authority: its
outer identifiers must come exclusively from the current ToolExecutionJournal binding.
The record must link at least:

- execution id;
- tool-call id;
- ActionRef;
- ActionRef binding digest;
- exact hidden GroundingRef;
- deterministic inner action id;
- expected version;
- ActionRef-observed Browser target identity hash;
- owner session/workspace/run generation.

Do not persist fill plaintext or other unnecessary semantic payload.  The inner
`action_id` already commits to normalized args.

Recovery starts from the **outer execution id**, loads exactly that immutable bridge,
then loads only the Browser receipt history for its exact bound `action_id`:

| Durable state | Required recovery | Replay |
|---|---|---|
| PREPARED, no Browser running receipt | report not dispatched / prepared-before-running | never |
| Browser running, no terminal receipt | outcome unknown | never |
| Browser terminal receipt, outer finished absent | reconstruct exact receipt/result provenance and settle outer WAL | never |

No semantic lookup, target matching, "latest" receipt selection, or new Browser call is
allowed during recovery.

### 2.5 R13: main provider projection is the remaining canary bypass

`get_tool_schema` already filters both list and exact lookup by
`current_tool_discovery_scope`.  Subagent provider projection also honors an inherited
scope.  The main LoopEngine does not: `_project_request_tools()` starts from
`registry.schemas(...)` and projects the full registered set.

With Browser mutation enabled, factory still registers the existing legacy tools:

- `browser_action`;
- `browser_semantic_execute`;
- `browser_semantic_operation`.

The last one can itself recapture and exact-unique-match semantic fields, so merely
adding five ActionRef tools would not constitute an ActionRef-only treatment.

**GREEN-2 ruling:** an explicit canary execution-domain scope must be enforced at three
mechanical surfaces:

1. main LoopEngine provider schemas;
2. `get_tool_schema` discovery (already present);
3. actual ToolRegistry execution, so a hallucinated/unadvertised out-of-scope legacy
   tool cannot execute.

`scope=None` preserves the existing full-registry behavior.  The canary scope removes
only the three legacy Browser mutation tools and admits exactly the five typed ActionRef
Browser mutation tools; unrelated non-Browser capabilities are not globally removed.

The scope must come from explicit runtime/canary authority, never from user text or a
model semantic classification.

## 3. Dependency-ordered production slices

### G2-S1 — strict execution binding + durable execution-join foundation

**Risk:** low-to-medium.  **Physical dispatch capability added:** none.

This is the recommended first implementation slice.

Planned responsibility:

- expose a strict read-only ActionRef binding view/accessor from the existing current
  ToolExecutionJournal binding;
- reject missing/revoked/owner-inconsistent ActionRef attempts without changing legacy
  `current_effect_mutation_authority()` semantics;
- add the immutable execution-join record/store and exact lookup by outer execution id;
- allow deterministic creation of PREPARED bridge facts only;
- add recovery classification for PREPARED/no-running as a no-dispatch fact, but do not
  create or register any ActionRef mutation tool.

Required write order:

1. assistant tool declaration durable;
2. outer `tool.execution.declared` durable;
3. outer `tool.execution.started` durable;
4. exact worker effect binding active;
5. ActionRef exact resolve + existing compiler (test/harness caller only in this slice);
6. execution bridge PREPARED durable;
7. **STOP — no BrowserActionAdapter.execute / no actuator call.**

Deterministic tests:

- strict accessor rejects unbound callers while legacy authority remains unchanged;
- strict accessor rejects revoked binding;
- bridge facts use execution/tool-call/session/workspace/run identity from the binding,
  not caller-supplied duplicates;
- bridge write failure prevents any continuation;
- same execution id cannot be rebound to another ActionRef/action id;
- restart with PREPARED/no running receipt never dispatches and reports
  `auto_reexecuted=false`.

Do **not** prematurely relabel end-to-end R10/R15 GREEN merely because the primitives
exist.  Those rows become GREEN only when the real typed ActionRef path consumes them.

### G2-S2 — exact target precondition + compiler bridge

**Risk:** medium.  **Live/provider exposure:** none.

Planned responsibility:

- add an ActionRef-only exact Browser target precondition into the adapter/actuator
  boundary;
- verify target identity before actuator first bind and physical commit;
- add a non-exposed typed compiler helper that performs:
  `ActionRef -> exact GroundingRef -> existing BrowserSemanticExecuteTool.compile_request`;
- carry the existing deterministic inner action id forward unchanged;
- reuse the existing version/stable-physical-identity guard.

Legacy Browser paths must continue to work without the new ActionRef target
precondition unless explicitly routed through the ActionRef wrapper.

Deterministic tests use fake CDP/capture/actuator only:

- observed target A, actuator first sees B -> reject, dispatch count 0;
- exact A -> target precondition passes;
- same exact ActionRef+verb+args -> same inner action id;
- duplicate exact request -> physical dispatch counter at most 1 in fake harness;
- stale document/page or unstable physical identity -> existing rejection, no
  re-observation/search/rebind.

### G2-S3 — exact crash correlator

**Risk:** medium-high.  **Physical dispatch capability added:** none; recovery only.

Planned responsibility:

- add a narrow recovery-correlator interface to ToolExecutionJournal rather than
  teaching generic WAL recovery semantic Browser search;
- Browser correlator loads the exact execution bridge by execution id and exact receipt
  history by bound action id;
- support the three frozen crash cuts from R16-R18;
- every recovery path remains `auto_reexecuted=false`.

Fault-injection tests must cut execution exactly:

1. after PREPARED fsync, before Browser running receipt;
2. after running receipt fsync, before terminal receipt;
3. after terminal Browser receipt fsync, before outer `finished`.

The recovery call itself must prove Browser dispatch count stays unchanged.

Main LoopEngine can receive the correlator through explicit mechanical construction.
Initial P4-LIVE canary should not expose ActionRef mutation to subagents until the same
correlation contract is wired to the subagent ToolExecutionJournal path or separately
qualified there.

### G2-S4 — five typed ActionRef mutation tools, default OFF

**Risk:** high.  **First physical-dispatch-capable production slice.**

Only after S1-S3 qualification should production add:

- `browser_semantic_click(action_ref)`;
- `browser_semantic_fill(action_ref, text, mode)`;
- `browser_semantic_select(action_ref, value)`;
- `browser_semantic_scroll(action_ref, delta_pages)`;
- `browser_semantic_navigate(action_ref, url)`.

The model owns ActionRef choice, verb/tool choice and semantic arg values.  The program
only checks the frozen mechanical contract.

Per-call order is mandatory:

1. require live non-revoked ToolExecutionJournal binding;
2. resolve exact ActionRef against that binding's session/workspace/run;
3. delegate hidden exact GroundingRef + verb + args to existing compiler;
4. persist exact execution bridge PREPARED;
5. verify exact ActionRef-observed Browser target;
6. reuse existing fresh version / stable identity guard;
7. persist Browser dispatch grounding and running receipt;
8. enter existing effect-mutation authority critical section;
9. one physical actuator attempt;
10. persist terminal Browser receipt;
11. return exact receipt for normal outer WAL finish/receipt commit.

Introduce a **separate default-OFF mutation exposure gate**.  Do not overload the
GREEN-1 perception-annotation flag and do not change legacy `browser_action_enabled`
compatibility.

Before any live Browser authorization, deterministic tests must turn
R10/R11/R12/R14-R19 GREEN with fake actuators and crash injection.

### G2-S5 — canary provider/discovery/execution scope

**Risk:** medium-high because it changes the main model-visible capability plane.

Planned responsibility:

- main `_project_request_tools()` filters by an explicit
  `current_tool_discovery_scope` before provider projection;
- `get_tool_schema` keeps the same scope behavior;
- ToolRegistry call execution rejects a name outside an explicit scope before
  `tool.execute`;
- `scope=None` preserves full legacy behavior;
- P4-LIVE canary scope hides all three legacy Browser mutation tools and exposes the
  five ActionRef mutation tools as the only Browser mutation surface;
- canary preflight requires an explicit non-empty configured Browser target id.

R13 becomes GREEN only after provider projection, discovery, and execution callability
all agree on the same exact scope.

## 4. Row-to-slice qualification map

| Row | Primary slice | Required evidence |
|---|---|---|
| R10 | S1 + S4 | direct/unbound typed ActionRef call rejected, dispatch 0; bound call uses exact ToolExecutionJournal identity |
| R11 | S1 + S4 | timeout/cancel revokes binding before return; released late worker cannot enter dispatch window |
| R12 | S2 + S4 | observation A / actuator B first-bind race rejects, dispatch 0 |
| R13 | S5 | provider schemas + get_tool_schema + actual execution all hide/reject three legacy Browser mutation tools in canary scope |
| R14 | S2 + S4 | exact ActionRef resolves same GroundingRef; existing compiler yields same action id; reserve prevents second dispatch |
| R15 | S1 + S4 | immutable execution bridge durable before Browser running/dispatch window |
| R16 | S1 + S3 | PREPARED/no running -> no-dispatch recovery |
| R17 | S3 | running/no terminal -> unknown, no replay |
| R18 | S3 | terminal/no outer finished -> exact correlate/recover, no replay |
| R19 | S2 + S4 | existing version/stable-target guard rejects stale/changed/unstable state; no search/rebind |

## 5. Adjacent regression gates per slice

Every implementation slice must keep these existing suites GREEN:

- `tests/unit/test_tool_execution_effects.py`;
- `tests/unit/test_tool_execution_restart.py`;
- `tests/unit/test_run_generation_ownership.py`;
- `tests/unit/test_smc_browser_action_v01.py`;
- `tests/unit/test_smc_browser_cdp_action_host_v01.py`;
- `tests/unit/test_smc_browser_semantic_execute_v01.py`;
- `tests/unit/test_smc_browser_perception_v01.py`;
- `tests/unit/test_capability_wiring.py`;
- relevant `tests/unit/test_subagent*.py` whenever scope or ToolExecutionJournal
  construction changes;
- P4-FCR and GREEN-1 P4-LIVE matrix tests.

Additionally, each slice requires:

- deterministic RED->GREEN tests for only its authorized row/sub-contracts;
- explicit physical-dispatch counters in fake actuators;
- no network Browser fixture for S1-S3;
- Ruff / Pyright / diff-check / security scan;
- committed-state qualification before advancing.

## 6. Rollback / feature boundaries

- GREEN-1 ActionRef issuance/resolution remains independently default OFF through
  `browser_action_ref_enabled`.
- GREEN-2 mutation exposure gets a **separate default-OFF authority**.
- Legacy GroundingRef Browser tools remain registered/usable outside an explicit P4-LIVE
  canary scope for rollback and compatibility.
- `current_effect_mutation_authority()` legacy-unbound behavior is not globally
  tightened.
- `current_tool_discovery_scope=None` remains the legacy full registry.
- Persisted ActionRef/execution/receipt evidence is inert when mutation exposure is OFF.
- No slice requires an 8901 restart merely to disable ActionRef Browser wiring.

## 7. Risks that must not be hidden by implementation convenience

1. **Cross-layer coupling:** outer WAL must not learn semantic Browser search.  Recovery
   correlation is exact execution-id -> binding -> action-id only.
2. **Crash window ordering:** a "prepared" fact written after running receipt is too
   late and fails R15/R16.
3. **Target hash is not optional on ActionRef path:** allowing actuator sole-page
   fallback reopens R12.
4. **Direct-call compatibility cannot be reused for ActionRef tools:** unbound legacy
   authority is intentionally permissive and must be rejected by the new typed path.
5. **Provider hiding alone is not sufficient:** actual call execution must respect an
   explicit scope or a hallucinated hidden legacy tool remains a bypass.
6. **Do not expose ActionRef mutation to subagents accidentally:** either wire the same
   recovery bridge there or keep the typed tools outside their explicit scope during the
   initial canary qualification.
7. **Do not persist sensitive semantic args:** especially fill text.  The bridge needs
   identity/provenance, not plaintext payload duplication.

## 8. Recommended next implementation

Start a fresh Goal/worktree from the exact GREEN-1 freeze (or from this docs-only plan
commit once independently frozen) and implement **G2-S1 only**.

Success for that next slice is deliberately narrow:

- strict ActionRef-only ToolExecutionJournal binding requirement exists;
- immutable execution bridge PREPARED record is durable and owner-consistent;
- PREPARED/no-running recovery is mechanically no-dispatch/no-replay;
- legacy tools remain unchanged;
- no ActionRef mutation tool is registered;
- no BrowserActionAdapter/actuator dispatch is reachable through new code;
- R10/R15 should not be declared end-to-end GREEN until later slices actually consume
  the foundation.

Stop again before G2-S2.
