# SMC P4-LIVE v0.2 PRE-LIVE Qualification Result

> Date: 2026-09-20
> Base production-fix result: `faffd569d6d5a99c6bde9fdf68348c56aef92df3`
> Frozen v0.1 NOT_QUALIFIED result: `9a11fe4c43cc83f53bf2baf62d0782c91e1d4242`
> Protocol commit: `267ad5778be2af324e38ba8422a5d1a29bbe053d`
> Result: **QUALIFIED V0.2 PRE-LIVE STOP**

## 1. What is qualified

P4-LIVE v0.2 now has a frozen requalification protocol, exact execution manifest, independent result namespace, deterministic PRE-LIVE tests, and a zero-action runtime preflight. This result authorizes **no model request and no Browser mutation**. It stops before `V02-L01` makes its first Ornith request.

The v0.1 negative qualification remains immutable. Its L02 failure is neither retried nor reclassified; v0.2 is a new qualification run.

## 2. Protocol continuity

The v0.1 20-row semantics, serial row order, no-retry/no-substitution rule, LLM-First authority split, exact 12-tool canary surface, and legacy Browser-mutation exclusions remain unchanged. Row ids are versioned `V02-L01` through `V02-L20`, and future LIVE results must be written only under the new v0.2 namespace.

The only new production fact is the independently qualified R12 target-identity fix: perception keeps its private `target:<raw CDP target id>` page token, while ActionRef issuance and the actuator both bind the exact raw CDP target identity digest. No target search, guessing, successor substitution, silent rebind, or semantic normalization was added.

## 3. Zero-action preflight

Committed protocol preflight passed with:

- exact base lineage from `faffd569...`;
- frozen v0.1 LIVE/adjudication hashes unchanged;
- exact R12 production source hashes;
- one Ornith server on 8901, prompt/decode concurrency 1, no established competing client;
- explicit non-empty Browser target id;
- three Browser/ActionRef feature flags enabled only in the qualification process environment;
- exact 12-tool provider/schema/catalog scope;
- all three legacy mutation tools blocked through scoped visibility, `get_tool_schema`, and direct registry execution;
- exact raw-target mapping and zero-dispatch target bind;
- mutation websocket opens = 0;
- model requests = 0;
- Browser mutations = 0;
- 20 manifest rows complete, unique, serial, and v0.2 namespaced.

## 4. Deterministic and static gates

Current S1-S5 descendant / Browser / ActionRef / recovery selection plus v0.2 protocol tests: **177/177 PASS**. Ruff passed. Pyright reports **0 errors / 0 warnings**. Diff-check and git security scan passed. This PRE-LIVE branch introduces **zero production `src/` delta** relative to the frozen R12 result.

The repository-wide CI remains red on the inherited frozen stack. The v0.2 candidate has the same **72** failures as the frozen R12 base, with candidate-only = 0, base-only = 0, and identical failure-set SHA-256 `67cb4e57...`. This is recorded as **baseline-equivalent red / no new failures**, not as a full-CI GREEN claim.

## 5. Historical S5 scope gate

Replaying the old S5 qualifier still shows R01-R20 all GREEN, inherited behavior GREEN, and exact 12-tool canary scope GREEN. Its aggregate `qualified_s5_pre_live_stop` is now false only because that historical qualifier hard-codes the pre-R12 three-file production scope. The separately qualified R12 successor legitimately added `action_ref.py`, `cdp_action_host.py`, and `target_identity.py`. Therefore the old exact-src-scope predicate is superseded for v0.2; its semantic/deterministic GREEN evidence remains inherited.

## 6. Mandatory stop

No new LIVE model request, Browser mutation, deploy, restart, PR/merge, or main modification has occurred. The next action requires a new explicit human authorization to cross the boundary before the first `V02-L01` model request.
