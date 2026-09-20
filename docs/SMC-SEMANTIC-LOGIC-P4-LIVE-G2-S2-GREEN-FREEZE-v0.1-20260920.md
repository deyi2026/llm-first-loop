# SMC P4-LIVE ActionRef — G2-S2 GREEN Freeze v0.1

> Date: 2026-09-20
>
> Status: **G2-S2 QUALIFIED / FAKE-ONLY / NON-PROVIDER / NON-DISPATCHING S2 PRIMITIVES**
>
> Exact S2 pre-GREEN parent: `8c000d74015af858d960d051ecb2619cf62ec8b9`
>
> G2-S1 anchor: `06891fd144c635f0625644a0c2c2ea24ed009e52`
>
> Frozen protocol/design: `e946eab26032aa4faa6698a3244ebd30c836cce1`

## 1. Scope

G2-S2 implements only the three-file production candidate frozen before GREEN:

- `src/llm_loop/browser/action.py`;
- `src/llm_loop/browser/cdp_action_host.py`;
- new hidden `src/llm_loop/tools/builtin/browser_action_ref_kernel.py`.

No other production source is changed by S2. In particular, S2 does not edit the
ActionRef resolver, S1 PREPARED bridge, perception authority, existing semantic compiler,
factory, registry, or LoopEngine provider projection.

This slice adds no model-callable ActionRef mutation tool, no provider/discovery surface,
and no new physical Browser-dispatch path. The first ActionRef physical-dispatch boundary
remains G2-S4.

## 2. R12 primitive — exact observed Browser target sticky precondition

`BrowserMutationActuator` and `BrowserActionAdapter` now expose the mechanical method:

`bind_observed_target(expected_target_id_sha256: str) -> None`

The adapter only forwards this call to its actuator; `BrowserActionAdapter.execute()` is
unchanged from the exact pre-GREEN parent.

`CdpBrowserMutationActuator.bind_observed_target()` runs under the actuator's existing
`_dispatch_lock`. It:

1. resolves the current page target exactly once using the existing target rules;
2. requires a valid SHA-256 expected target identity;
3. SHA-256 hashes the exact current CDP target id;
4. rejects a mismatch with stable code `browser_target_precondition_mismatch` before
   mutating bound state, opening a websocket, creating a CDP session, or sending a CDP
   command;
5. on match, sticky-binds only the exact target id and validated websocket URL;
6. performs zero websocket/CDP calls during the bind.

After sticky bind, existing `_resolve_target()` remains authoritative. If the bound page
A disappears and page B becomes the only page, later dispatch fails with the existing
"bound Browser target disappeared; no silent rebind" contract rather than adopting B.

Legacy callers that never invoke `bind_observed_target()` retain the old configured-target
or sole-page first-bind behavior; deterministic regression proves the legacy click path is
unchanged.

## 3. R14 primitive — hidden exact GroundingRef compiler bridge

New hidden module:

`src/llm_loop/tools/builtin/browser_action_ref_kernel.py`

contains:

- immutable `CompiledActionRefMutation`;
- hidden `ActionRefSemanticCompileBridge`;
- stable mechanical compile-basis errors.

The bridge accepts an **already-resolved** `ActionRefResolution`. It does not resolve an
ActionRef itself and has no search, recapture, selector, URL matching, latest/successor
lookup, or target-selection authority.

`compile_resolved()` calls the existing semantic compiler exactly once with:

- `target_ref = resolution.grounding_ref`;
- the model-selected verb;
- a copied model-owned args object.

It preserves the compiler-produced SemanticAction byte-for-field, including the existing
inner `action_id`, and mechanically requires:

- compiled `expected_version == resolution.observed_snapshot_id`;
- a non-empty existing compiler `action_id`;
- the exact `resolution.browser_target_id_sha256` to be carried unchanged.

The hidden module has no `BrowserActionAdapter`, execution, actuator, or dispatch
dependency and is not imported/registered by factory or registry.

## 4. R19 primitive — existing stale/version/stable-target authority remains unchanged

S2 deliberately does not create another stale-target policy.

The existing `BrowserSemanticExecuteTool.compile_request()` remains unchanged and still
hydrates the exact supplied GroundingRef. `BrowserActionAdapter.execute()` remains
source-identical to the exact pre-GREEN parent and still owns:

- fresh pre-dispatch observation;
- page/document version precondition;
- stable physical target resolution;
- fail-closed stale/changed/unstable rejection;
- existing reservation/running-receipt/effect-authority/single-dispatch mechanics.

The qualification proves a SemanticAction compiled from an exact ActionRef-hidden
GroundingRef is rejected by the current stale-version guard before fake actuator dispatch,
and an unstable physical target remains unresolved/fail-closed. There is no automatic
refresh or silent rebind.

## 5. Source-stability proof

The S2 machine qualifier extracts production methods from both exact parent
`8c000d740...` and the candidate and compares their source text. The following methods are
byte-identical at the method-source level:

- `BrowserActionAdapter.execute`;
- `BrowserActionAdapter._validate`;
- `CdpBrowserMutationActuator._resolve_target`;
- `CdpBrowserMutationActuator._ensure_session`;
- `CdpBrowserMutationActuator.dispatch`.

Therefore S2 adds a separate sticky precondition seam without rewriting the existing
execution path.

## 6. TDD result

Before production edits, the GREEN test suite failed specifically because:

- `BrowserTargetPreconditionError` / sticky bind API were absent;
- hidden ActionRef compiler bridge was absent;
- the three S2 probes still returned their frozen pre-GREEN absence codes.

After the exact three-file production implementation, focused S2 GREEN is **9/9 PASS**.
It covers:

- R12/R14/R19 S2 contract probes all `contract_present`;
- target A hash versus current B rejects before bind/websocket;
- exact A match sticky-binds with zero websocket/CDP;
- bound A never silently rebinds to successor B;
- legacy no-precondition actuator path remains operational;
- hidden bridge delegates exact GroundingRef exactly once;
- existing action id and expected version are preserved;
- observed target hash is carried unchanged;
- hidden bridge remains non-dispatching and unregistered.

One historical pre-GREEN eval helper used an invalid loopback websocket URL without a
port. GREEN execution reached that previously-unused match branch and exposed the harness
bug. The eval fixture alone was corrected from `ws://127.0.0.1/...` to
`ws://127.0.0.1:9222/...`; this is not a production behavior change.

## 7. Parent-contract preservation

G2-S2 primitives do **not** make the end-to-end P4-LIVE mutation rows GREEN by their mere
existence.

Committed/current machine qualification requires and currently proves:

- GREEN-1 remains qualified;
- G2-S1 remains qualified;
- R01-R09/R20 remain GREEN;
- all end-to-end R10-R19 remain RED;
- parent R12 remains `browser_target_independent_first_bind_gap`;
- parent R14 remains `actionref_inner_action_id_bridge_absent`;
- parent R19 remains `actionref_version_guard_delegation_absent`.

Those parent rows require later typed ActionRef composition; S2 intentionally creates no
such model-callable path.

## 8. Machine evidence

Machine qualification:

`evals/smc_semantic_logic_p4_live/run_green2_s2_qualification.py`

Evidence:

`evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S2-v0.1-20260920/EVIDENCE.json`

Evidence SHA-256:

`b34c9b5a973536e72cdb1accb36b04c43ba79710753d03412504c9c7115e6e18`

Frozen pre-GREEN plan SHA-256 remains:

`b1e36e828c20330fbe1663b1ce1d3a05f5b59e518e19129bcab96da869bbea2f`

Frozen pre-GREEN expected-failure taxonomy SHA-256 remains:

`61f51c4aa1d4e512d4670b00aaaa9071925740cf1a048baebf14c808323db2cd`

The S2 qualifier currently reports:

- `qualified_s2_stop = true`;
- three S2 subcontracts GREEN;
- focused S2 = 9/9 PASS;
- exact three production source paths and no others;
- critical imports from this exact worktree;
- unchanged existing execution methods = true;
- hidden kernel dispatch dependencies = none;
- factory registration = false;
- registry registration = false;
- real Browser actions = 0;
- model requests = 0;
- first physical-dispatch boundary crossed = false.

## 9. Stop boundary

G2-S2 stops before G2-S3.

Not implemented or authorized in this slice:

- Browser running/terminal receipt ↔ outer WAL crash correlator (G2-S3);
- typed ActionRef mutation facades (G2-S4);
- ActionRef physical Browser dispatch (G2-S4+);
- provider/discovery/execution canary isolation (G2-S5);
- real Browser action or model request;
- deploy/restart/merge main;
- Web/Feishu/8901 changes;
- live provider/runtime configuration changes.

The next phase must begin from the exact committed S2 freeze and requires a new human
checkpoint before G2-S3.
