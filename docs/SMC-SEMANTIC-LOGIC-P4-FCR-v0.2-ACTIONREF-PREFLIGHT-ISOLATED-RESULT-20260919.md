# SMC Semantic Logic P4-FCR v0.2 — Source-Bound Preflight Result

> Date: 2026-09-19
> Status: **QUALIFIED_DETERMINISTIC_PREFLIGHT_ONLY / STOP BEFORE REAL MODEL**
> Exact qualification candidate: **a30e864a440cf5a89851fbde1fbccc458ea1a80c**
> ActionRef implementation candidate: **eae7638c83503472918927f93df49a26469200a8**
> Protocol commit: **d2945cfc5459cf69ae963b1b71a13976fdc6de75**

## 1. Why this preflight supersedes the previous one

The earlier preflight frozen at `33135a7d44f6fb8020813feda48de5802a9c1488`
was discovered, before any real v0.2 model row, to have a qualification isolation
defect. Its runner file came from the isolated candidate, but the shared editable
Python environment resolved `llm_loop` from the main worktree.

That mixed two code identities in one manifest: source hashes represented the
candidate while the provider-visible Browser surface was generated from the
main worktree. Reproducing the same shared interpreter reproduced the old
surface hashes exactly, proving the contamination rather than a model/runtime
change.

The old evidence remains immutable for audit history, but it is **superseded for
execution qualification**. No real row was produced from it.

## 2. Narrow isolation repair

Commit `a30e864a440cf5a89851fbde1fbccc458ea1a80c` changes only the v0.2
qualification runner and its focused tests. Production `src/` changes: **0**.

The runner now:

- puts the exact worktree `src/` ahead of editable/shared package roots;
- records actual imported module paths and SHA-256 values in the execution manifest;
- covers core prompt/run-context, LLM client/schema, ToolRegistry,
  browser_perceive, browser_wait, browser_semantic_execute, and method_card;
- fails closed if any tracked qualification import resolves outside the exact
  worktree source root.

A subprocess regression deliberately uses the shared project interpreter that
previously caused contamination. It now resolves all nine modules into the
current qualification worktree.

## 3. Deterministic qualification

Committed-state results on exact `a30e864a...`:

| Suite | Result |
|---|---:|
| P4-FCR v0.2 focused | **27/27 PASS** |
| v0.1 FCR preflight adjacency | **7/7 PASS** |
| P4-D typed compiler adjacency | **19/19 PASS** |
| **Combined** | **53/53 PASS** |

Additional gates:

- Ruff: PASS
- Ruff format: PASS
- Pyright: **0 errors / 0 warnings**
- git diff-check: PASS
- commit security scan: PASS
- production `src/` changes: **0**

## 4. Full repository CI

The fresh worktree initially lacked the gitignored restricted-EYE backend, the
same documented condition seen in the previous qualification. It was restored
from the tracked lock only via `npm ci --ignore-scripts`.

Verified qualification backend:

- eyereasoner **21.1.18**
- swipl-wasm **7.0.10**
- EYE **v11.24.5 (2026-08-23)**
- Node **v24.18.0**
- package-lock SHA-256 **83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be**

Full CI then passed directly:

- all-repo Ruff: PASS
- env-pin: **607 files / 0 undeclared**
- src Pyright: **0 / 0**
- tier0: PASS
- xdist full gate: **PASS directly**
- guard report: PASS

The CI wrapper's unrelated `git worktree list | head -1` fallback can exit 141
under `pipefail` when many worktrees exist. The run therefore supplied the
already-qualified shared Python path explicitly; the CI wrapper itself then
bound `PYTHONPATH` to this worktree's `src/`. No repository file was changed for
that operational workaround.

## 5. Fresh source-bound zero-model preflight

External workdir:

`/private/tmp/smc-p4-fcr-v02-actionref-preflight-isolated-a30e864a-20260919`

Results:

| Fact | Value |
|---|---:|
| experiment head | `a30e864a440cf5a89851fbde1fbccc458ea1a80c` |
| plan rows | **40** |
| model requests | **0** |
| tool execution total | **0** |
| Browser runtime | **false** |
| row directories | **0** |
| results.jsonl | absent |

Frozen semantic plan SHA-256 remains:

**62a4e18477d794140c46577efa32f33a4ef04da1659aa3a448499b5b74b54ad4**

Corrected provider-visible wire hashes, now generated from the exact candidate
source root:

- Arm A: **39f1c40e38dfb8187976ff633d952278eee54b67e2035716cc9c4fcd96266aec**
- Arm B: **4657bb82b26d3bfe6bf4ed2ce85d606123fc1b237ebe37c292d043fa3e421160**

External preflight artifact hashes:

| Artifact | SHA-256 |
|---|---|
| plan.json | `55133970a6e36c586b37de2c11641c3777b38d814990f0abbcec96633a4b37dc` |
| execution-manifest.json | `f6146cd79a4d59e4402316df3d2d632e9959b82ebaadc75f2e9c7f8d0995bb88` |
| preflight.json | `9ac8f60cc678e15877ba6af79edaa9768f407efc2a11729b9b9051b769c0901e` |

The manifest records all nine qualification imports as inside the exact
worktree source root. In particular, imported `browser_perceive.py` SHA-256 is
`d180b7880813b74b9a7c5fbda3e120576fa2657d53bd8fc4274d1cc08e4be072`,
identical to the candidate source hash; imported `method_card.py` likewise
matches its candidate source hash.

## 6. Evidence location and boundary

New superseding evidence:

`evals/smc_semantic_logic_p4_fcr_v02/results/PREFLIGHT-ISOLATED-v0.2-20260919/EVIDENCE.json`

This phase still proves **no model result**. It only restores trustworthy
qualification identity and preflight integrity.

No Browser call, deployment, restart, production ActionRef wiring, P4-LIVE run,
or second local model was used.

## 7. Next checkpoint

After this evidence is committed and ordinary-pushed to a new independent
review/evidence branch, the remote branch SHA and formal remote `main` must be
independently verified.

Only then may the frozen 40-row declaration-only FCR begin, strictly serially,
with no rerun, reorder, retry, normalization, Browser execution, or in-row
hydration. Qualification criteria remain unchanged: Arm B structural 20/20,
Arm B mechanical 20/20, targeted P4-X01/X02/X06/X07 total 0, and all
integrity/safety invariants green.
