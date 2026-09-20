# SMC Semantic Logic P4-LIVE ActionRef Protocol v0.2

> Date: 2026-09-20
> Base result: `faffd569d6d5a99c6bde9fdf68348c56aef92df3`
> Production GREEN: `f1efef6b57ef90562410a93cd310bae98e33a983`
> Status: **FROZEN PRE-LIVE REQUALIFICATION PROTOCOL / ZERO LIVE AUTHORIZATION**

## 1. Purpose

P4-LIVE v0.2 is a new qualification run after the R12 Browser-target identity production fix. It does not rewrite the v0.1 protocol semantics and it does not reinterpret or retry the frozen v0.1 L02 failure. The prior negative qualification at `9a11fe4c43cc...` remains immutable evidence.

The v0.2 purpose is narrower: re-run the same 20-row LIVE semantics from a new qualification namespace after proving that the production target-identity precondition now uses one canonical raw CDP target identity on both ActionRef issuance and actuator verification.

## 2. Unchanged authority model

The v0.1 LLM-First split remains unchanged. The model chooses the observed ActionRef, typed verb and semantic argument values. Program code owns only mechanical identity, integrity, session/workspace/run authority, lifetime, exact hydration, version/scope/physical-identity preconditions, execution binding, single-dispatch fences and durable recovery without replay.

Program code still may not search, rank, guess, normalize semantic targets, select a successor, silently rebind, replay an unknown outcome, or judge semantic task completion.

## 3. R12 canonical target identity

Perception keeps its private page-generation token `target:<raw_cdp_target_id>` unchanged. At the ActionRef issuance boundary only, the qualified R12 fix mechanically extracts the exact raw CDP target id. Both the ActionRef binding and `CdpBrowserMutationActuator` verify `sha256(raw_cdp_target_id)`.

This is representation alignment, not semantic normalization. Empty or malformed prefixed identities reject. Target disappearance, replacement, websocket change, stale document/scope/version, wrong kind, expired or revoked bindings and all existing lifetime fences remain fail-closed.

## 4. Provider and discovery surface

The v0.2 canary uses the same exact 12-tool scope as v0.1: read-only perception, five typed waits, `get_tool_schema`, and the five typed ActionRef mutation tools. `browser_action`, `browser_semantic_execute`, and `browser_semantic_operation` must be absent from provider projection and discovery and must be mechanically non-executable inside the canary scope.

The Browser target id is explicit and non-empty. Sole-page implicit target selection is not qualified for mutation.

## 5. New qualification namespace

Qualification id: `smc-p4-live-v0.2-20260920`.

Future LIVE result root: `evals/smc_semantic_logic_p4_live/results/P4-LIVE-v0.2-QUALIFICATION-20260920/`.

The v0.1 result root is read-only and must not be overwritten. Row ids are versioned as `V02-L01` through `V02-L20` while preserving the exact v0.1 row semantics and order.

## 6. Frozen row order

Success: V02-L01 navigate, V02-L02 click, V02-L03 fill, V02-L04 select, V02-L05 scroll.

Zero-dispatch rejection: V02-L06 cross-session, V02-L07 cross-workspace, V02-L08 prior run, V02-L09 expired, V02-L10 runtime restart, V02-L11 wrong kind, V02-L12 integrity corruption, V02-L13 stale document, V02-L14 target replacement, V02-L15 missing/revoked effect binding, V02-L16 duplicate exact declaration at-most-once.

Crash/ambiguity: V02-L17 execution prepared before Browser running receipt, V02-L18 running-receipt ambiguity, V02-L19 terminal Browser receipt with missing outer finish, V02-L20 transport ambiguity after possible effect.

Rows are serial. There is no automatic retry, substitution or reordering. A valid first row failure is frozen and stops the run for adjudication.

## 7. PRE-LIVE gate

Before any v0.2 model request, mechanically prove all of the following with zero model requests and zero Browser mutation dispatches:

- exact base lineage from `faffd569d6d5...`;
- old v0.1 negative artifacts remain byte-identical;
- R12 qualified production source hashes remain exact;
- one physical Ornith server on 8901 with prompt/decode concurrency 1 and no established competing client;
- explicit raw Browser target id;
- Browser action / ActionRef / ActionRef mutation feature flags enabled only in the qualification process environment;
- exact 12-tool scoped provider surface;
- legacy Browser mutation tools unavailable through scoped schemas, `get_tool_schema`, and direct registry execution;
- real raw-target identity can bind mechanically without opening the mutation websocket or dispatching;
- the 20-row manifest is complete, ordered, unique and versioned under the v0.2 namespace.

## 8. Authorization boundary

This protocol freeze authorizes **zero** real model requests and **zero** Browser mutations. It does not authorize deployment, restart, PR/merge, or main modification.

After the zero-action preflight and its evidence are frozen remotely, stop at a human checkpoint **before the V02-L01 model request**.
