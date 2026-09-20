# SMC P4-LIVE ActionRef — G2-S2 Pre-GREEN Freeze v0.1

> Date: 2026-09-20
>
> Status: **QUALIFIED PRE-GREEN / DETERMINISTIC RED + READ-ONLY RISK AUDIT**
>
> Exact base G2-S1: `06891fd144c635f0625644a0c2c2ea24ed009e52`
>
> Parent GREEN-2 plan: `0d868fe074a8cad746fffbd7d771c24100eac74a`
>
> GREEN-1: `62529729c5888ae863a1fe1715e2590a9519d182`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. Scope and stop boundary

This freeze is intentionally **before the first G2-S2 production GREEN**.

Only tests/eval/docs were added. No production `src/` file is modified in this stage.
No ActionRef mutation tool is registered or exposed; no real Browser action or model
request is issued; there is no deploy/restart/merge, Web/Feishu/8901 change, or live
provider/runtime configuration mutation.

G2-S2 is limited to the future prerequisites for parent rows R12, R14 and R19:

- exact Browser target precondition across perception → actuator;
- hidden ActionRefResolution → exact GroundingRef → existing compiler bridge;
- preservation of the existing stale/version/stable-target guard basis.

The first ActionRef production path that may physically dispatch remains **G2-S4**.

## 2. Read-only audit findings

### 2.1 R12 — target first-bind gap is real and narrowly located

`CdpReadOnlyBrowserHost` and `CdpBrowserMutationActuator` each own independent:

- `_configured_target_id`;
- `_bound_target_id`;
- sole-page fallback when no target id is configured.

The deterministic probe gives the perception host only `target-A` and the mutation
actuator only `target-B`. Both are initially unbound and each mechanically chooses its
own sole target. No dispatch is performed, yet the identity gap is observable:

- perception candidate = `target-A`;
- actuator candidate = `target-B`;
- `identity_gap_observed = true`.

GREEN-1/S1 already provide the missing fact needed to close this gap: every resolved
ActionRef carries `browser_target_id_sha256`, and the probe independently verifies that
the stored hash equals SHA-256 of the perception snapshot's exact `page_token`.

The remaining gap is therefore **not target discovery**. It is the absence of a
mechanical channel that consumes that already-frozen target hash before the actuator's
first bind.

### 2.2 Why the future precondition must sticky-bind, not merely check

A standalone `check_target(hash)` followed later by dispatch would leave a race between
the check and actuator first bind.

The narrow future contract is instead a **non-dispatching sticky bind**:

`bind_observed_target(expected_target_id_sha256: str) -> None`

For the CDP actuator it must run under the existing `_dispatch_lock` and:

1. resolve the current page target exactly once;
2. SHA-256 the exact target id;
3. reject a mismatch before mutating `_bound_target_id` and before opening a websocket;
4. on match, persist only the exact target id + websocket URL into the actuator's
   existing sticky bound fields;
5. create no CDP session and send no `Page.*`, `DOM.*`, or `Runtime.*` command.

Once sticky-bound, the existing `_resolve_target()`/`_ensure_session()` behavior already
fails closed if that exact target disappears or its websocket changes; it never silently
rebinds to a successor page. Thus the precondition remains valid across the later
version/stable-target guard and running-receipt work without holding a long lock across
those operations.

The future mismatch should surface a stable mechanical error code:

`browser_target_precondition_mismatch`

### 2.3 R14 — existing compiler is already the correct authority

`BrowserSemanticExecuteTool.compile_request()` already has the desired semantics:

- accepts an exact selected `target_ref`;
- calls exact `perception.hydrate(session_id, target_ref)`;
- performs no snapshot recapture, search, target selection, latest/successor lookup or
  rebind;
- derives scope/target/expected-version mechanically from that exact hydration;
- derives inner `action_id` deterministically from `verb + exact target_ref + args`.

The pre-GREEN probe resolves a real GREEN-1 ActionRef, feeds its hidden byte-identical
GroundingRef directly into current `compile_request()`, and verifies:

- ActionRef resolution GroundingRef == persisted model-visible GroundingRef;
- compiled expected version == ActionRef observed snapshot id;
- same exact GroundingRef + verb + args => same existing inner action id;
- current reservation store rejects duplicate reservation for that action id.

Therefore S2 must **not rewrite, extract, fork or replace the compiler**.

The only future missing seam is a hidden, non-provider adapter:

`ActionRefSemanticCompileBridge.compile_resolved(...)`

It accepts an already-resolved `ActionRefResolution` and delegates exactly once to the
existing compiler with:

`target_ref = resolution.grounding_ref`.

It must not accept a raw locator, URL, selector, target id, search query, or alternate
GroundingRef from the model/caller.

### 2.4 R19 — existing guard machinery is already fail-closed

The qualification independently proves the current guard prerequisites:

- document/page version drift => `stale`;
- automatic refresh = false;
- silent rebind = false;
- the manually ActionRef-resolved + existing-compiler-produced SemanticAction is rejected
  by current `BrowserActionAdapter` against a stale capture before fake actuator dispatch;
- stable physical target resolves from the persisted private snapshot identity;
- changing that identity to unstable makes `_physical_target()` fail closed.

So S2 must not introduce a second version/stability policy. The hidden compiled result
only needs to preserve the exact values needed by the existing guard:

- current compiler-produced `semantic_action`;
- exact hidden `grounding_ref`;
- exact `observed_snapshot_id`;
- exact `browser_target_id_sha256`.

End-to-end parent R19 intentionally remains RED until a later typed ActionRef path
actually composes these primitives.

## 3. Frozen future S2 production candidate

The narrowest future GREEN is exactly three production files.

### 3.1 `src/llm_loop/browser/action.py`

Future change only:

- extend `BrowserMutationActuator` with
  `bind_observed_target(expected_target_id_sha256: str) -> None`;
- add the same mechanical forwarding method to `BrowserActionAdapter`;
- do **not** change the closed SemanticAction schema;
- do **not** change `BrowserActionAdapter.execute()` reservation, fresh observation,
  version/stable-target guard, running receipt, effect-authority, or single-dispatch
  semantics.

### 3.2 `src/llm_loop/browser/cdp_action_host.py`

Future change only:

- add stable `BrowserTargetPreconditionError`/
  `browser_target_precondition_mismatch`;
- implement sticky `bind_observed_target()` under the existing `_dispatch_lock`;
- mismatch: reject before websocket/session/CDP and leave `_bound_target_id` empty;
- match: set only exact target id + websocket URL; zero CDP commands;
- later dispatch retains existing no-silent-rebind behavior.

### 3.3 `src/llm_loop/tools/builtin/browser_action_ref_kernel.py`

New future hidden/non-registered module only:

- immutable `CompiledActionRefMutation` result;
- hidden `ActionRefSemanticCompileBridge`;
- constructor receives existing `BrowserSemanticExecuteTool` compiler authority;
- `compile_resolved(session_id, resolution, verb, args)` calls
  `compile_request()` exactly once with `resolution.grounding_ref`;
- verify compiled expected version == `resolution.observed_snapshot_id`;
- preserve existing compiler action id byte-for-byte;
- carry `resolution.browser_target_id_sha256` unchanged;
- no `BrowserActionAdapter`, `execute_request`, actuator or `dispatch` dependency;
- no `Tool` name/schema and no factory registration.

## 4. Explicit production non-edits for future S2 GREEN

The following are frozen as non-edits for S2:

- `src/llm_loop/browser/action_ref.py` — existing resolver stays sole ActionRef authority;
- `src/llm_loop/browser/action_ref_execution.py` — S1 PREPARED bridge remains unchanged;
- `src/llm_loop/browser/perception.py` — existing observation/version authority unchanged;
- `src/llm_loop/tools/builtin/browser_semantic_execute.py` — compiler unchanged;
- `src/llm_loop/factory.py` — no registration/exposure;
- `src/llm_loop/tools/registry.py` — no provider/discovery change;
- `src/llm_loop/core/loop/engine.py` — no main-loop surface change.

If future GREEN requires changing one of these files, that is a scope break and requires
a new architecture checkpoint rather than silently expanding S2.

## 5. Frozen future composition order

S2 itself will still not create a model-callable mutation path. The later S4 composition
must use these authorities in this order:

1. enter S1 strict ActionRef ToolExecutionJournal binding authority;
2. resolve ActionRef exactly once using binding-owned session/workspace/run generation;
3. hidden S2 compiler bridge passes only the resolved exact GroundingRef + verb +
   model-owned args into existing `compile_request()`;
4. persist the existing S1 PREPARED execution bridge;
5. sticky-bind/verify the ActionRef-observed Browser target hash;
6. call current `BrowserActionAdapter.execute()` with the unchanged compiled
   SemanticAction;
7. existing fresh version/stable-physical-target guard remains authoritative;
8. only after those guards may existing running-receipt/effect-authority/single-dispatch
   machinery proceed.

No semantic search/rebind/refresh is inserted anywhere in this order.

## 6. Deterministic RED taxonomy

The S2 pre-GREEN matrix is intentionally three expected RED rows:

| S2 row | Parent | Expected failure code |
|---|---|---|
| `G2S2-R12-TARGET-PRECONDITION` | P4L-R12 | `actionref_browser_target_precondition_absent` |
| `G2S2-R14-HIDDEN-COMPILER-BRIDGE` | P4L-R14 | `actionref_hidden_groundingref_compiler_bridge_absent` |
| `G2S2-R19-GUARD-BASIS` | P4L-R19 | `actionref_guard_basis_bridge_absent` |

The probe wrapper converts every unexpected exception to `harness_error`. A harness
error is forbidden from qualifying as RED.

During qualification this caught a real test-environment problem: a direct runner using
the shared editable venv initially imported `llm_loop` from another checkout and reported
the production ActionRef core missing. The S2 harness now prepends its exact worktree
`src/` before any `llm_loop` import and machine evidence records the actual imported
critical module paths and SHA-256 values. This follows the already-frozen P4-FCR
isolation rule rather than treating path contamination as product evidence.

## 7. Machine plan/evidence

Machine plan:

`evals/smc_semantic_logic_p4_live/GREEN2-S2-PREGREEN-PLAN.v0.1.json`

SHA-256:

`b1e36e828c20330fbe1663b1ce1d3a05f5b59e518e19129bcab96da869bbea2f`

Expected-failure taxonomy:

`evals/smc_semantic_logic_p4_live/GREEN2-S2-EXPECTED-FAILURES.v0.1.json`

SHA-256:

`61f51c4aa1d4e512d4670b00aaaa9071925740cf1a048baebf14c808323db2cd`

Qualification evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S2-PREGREEN-v0.1-20260920/EVIDENCE.json`

SHA-256:

`0d905b8ecdcd5dbb26658abbbdf226498b133182cda41dc9e21add41bddbe377`

At this freeze the machine runner reports:

- `qualified_s2_pregreen_stop = true`;
- all three S2 rows exact expected RED;
- S2 focused pytest PASS;
- all critical `llm_loop` imports under this exact worktree `src/`;
- G2-S1 qualification still GREEN;
- GREEN-1 20-row matrix still qualified;
- parent R12/R14/R19 frozen RED taxonomy unchanged;
- all R10-R19 remain RED end-to-end;
- future machine plan validates;
- production `src/` diff/untracked count from exact S1 base = 0;
- real Browser actions = 0;
- model requests = 0;
- S2 production GREEN started = false.

## 8. Future GREEN acceptance gates

Before leaving S2 in a future implementation Goal, deterministic fake-only tests must
prove at minimum:

1. observed A hash + actuator sole B => precondition mismatch before websocket, with no
   bind or CDP command;
2. observed A hash + actuator A => sticky bind A with zero websocket/CDP during bind;
3. after sticky bind A, replacing target list with B => later fake dispatch rejects, no
   silent rebind;
4. legacy path that never invokes sticky bind behaves exactly as before;
5. hidden compiler bridge invokes existing compiler exactly once using only
   `resolution.grounding_ref`;
6. existing action id and expected version are preserved exactly;
7. target hash is carried unchanged;
8. hidden bridge has zero dispatch/provider-registration dependency;
9. stale/version/unstable-target current guards remain fail-closed and zero fake
   dispatch;
10. duplicate existing inner action id reservation remains at-most-once.

After those gates, S2 must stop again before G2-S3. Real Browser authorization remains a
later phase.
