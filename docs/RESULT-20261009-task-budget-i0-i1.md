# TaskBudget I0/I1 — offline contract and CAS root ledger (2026-10-09)

> Status: **offline implementation candidate**. This result only qualifies
> *storage invariants and static contracts*. It does **not** certify provider
> physical-attempt enforcement, tool sandboxing, GLM-5.3 precise tokens/cost,
> scheduler integration, actual cancellation, or method/experience efficacy.
>
> Parent: design/provider-tool-budget-20261009 @ b444d5bcd.
> Implementation: feat/task-budget-ledger-i1-20261009 (isolated worktree).
> Production: Web gen206 Shadow, Feishu/Learning gen204; **unchanged**.
> Knowledge Canary: **HOLD**.

## Delivered contract

- `src/llm_loop/resources/task_budget_contracts.py`: frozen
  `TaskBudgetLimits`, `TaskBudgetCapabilities`, `TaskBudgetGrant`,
  `TaskBudgetMember`, closed `BudgetDimension` and lifecycle enums.
- `src/llm_loop/resources/task_budget_store.py`: a disk-authoritative,
  one-snapshot-per-root `TaskBudgetStore`, with independently validated
  identity, workspace/session, origin run, human turn, child run,
  wake schedule reference, policy generation and reservation id.
- `tests/unit/test_task_budget_store.py`: provider-free fail-first tests
  of first creation, durable revision CAS, concurrency, lineage,
  policy restrictions, uncertain effects, and crash cut-points.
- `tests/guards/function_size_baseline.json :: durability_registry`:
  `task_budget_root_ledger` is registered as a T2 conform **file-level
  writer**. This classification does not grant a production admission role.

The modules are **not imported or instantiated** by Web, Feishu, Learning,
factory, LoopEngine, ProviderCallCoordinator, ResourceGovernor,
ToolRegistry, Scheduler, LLMClient or the RG-3D projection. There are no
configuration keys, provider calls, tool calls, background tasks or migration
of existing runtime data.

## Correctness and fault semantics

| Invariant | I1 contract | Evidence |
| --- | --- | --- |
| One root authority | `issue_root` is create-if-absent under per-root flock; duplicate exact issue returns the *existing* revision, differing issue is refused | offline duplicate/conflict cases |
| No reset after wake | Every child binding references an existing parent of the *same root*; separate Store instance reads the same reserved balance | wake-Run B / same root tests |
| CAS | Every semantic mutation checks an exact expected revision *under the file lock*; distinct writer/process races do not silently merge or overwrite | threads and spawned processes |
| Durable T2 | Root dir parent fsync, temporary O_EXCL + file fsync, atomic replace + directory fsync | injected torn temp, replace, parent and post-replace sync failures |
| Commit uncertainty | Before replace: `TaskBudgetPersistError(retry_safe=True)`; after replace: `TaskBudgetCommitUncertainError(retry_safe=False, visible_state)`; compare exact bytes, never replay the semantic mutation on an assumed failure | post-replace retry exhaustion and readback |
| No free unknown | `RESERVED`, `DISPATCHED`, `UNKNOWN` continue charging their allocated units; only a proven, still-`RESERVED` pre-dispatch abort refunds | status/abort and unknown-liability tests |
| One-way capabilities | Limits and explicit allowed tool set can only tighten; allow_wake/allow_subagents cannot turn false→true; generation increments | tightening/expansion-rejection cases |
| No stale policy dispatch | Reserved actions carry the policy generation at admission; tightening invalidates their *future physical dispatch* until a new authorized reservation | old-generation dispatch denial test |
| No fake closed state | Only `CLOSED_UNCERTAIN` is available; no I1 API can assert `CLOSED_VERIFIED` without external quiescence evidence | Run stop/settle/close tests |
| No bad-state reset | Missing/corrupt old file or unsupported schema is fatal; never treated as a new empty budget | malformed JSON/typed corruption/symlink tests |
| Scope isolation | Member workspace/session must match root; conflicting descendant lineage/generation refused; root ID/path cannot traverse directory | scope, identity and path cases |

**Exactness:** The store can enforce non-negative *declared allocations*
and atomic revision ceilings (one logical call, physical attempt, tool call,
round, optional input/output token or request byte count). I1 does **not**
verify that the caller's claims correspond to a real GLM wire or provider
usage. Limits set to `None` are **unqualified**, not unlimited; attempts
to reserve an unqualified dimension are blocked.

**Conservative accounting:** The `report()` projection is derived from
the persisted root, not a second mutable authority; it reports reserved/
known spend, over-limit dimensions and unknown/outstanding reservations,
with `physical_quiescence_verified=false` regardless of a clean ledger.

## Known gaps / stop conditions

1. **I2 not done:** no real network pre-dispatch gate, fallback/retry
   attempt accounting adapter, verified GLM tokenizer or actual request
   payload budget. Must remain HOLD.
2. **I3 not done:** no real `ToolRegistry.execute` deny, schema
   projection filter, MCP/Plugin/compound tool capability checks,
   or bound schedule issuance. The store's numeric admission alone
   is *not* a physical permission boundary.
3. **I4 not done:** no OS worker kill, provider cancel acknowledgement,
   process quiescence proof, exact transport usage reconciliation or
   `CLOSED_VERIFIED` transition. Unknown effects remain liabilities.
4. **Human authority not wired:** I1 accepts an explicitly constructed
   data object; it does not sign or verify an ingress token. It cannot
   be installed in production as a stand-alone authorization service.
5. **Resource/price identities unqualified:** current GLM product/account,
   exact model token semantics and billing are not proved. This phase
   does not implement cost admission or pricing by approximation.
6. **Not yet multi-root aggregated:** per-root CAS is isolated to a
   single task lineage, not cross-account quotas, fleet-wide or
   provider-global admission.
7. **Retained bounded history:** the pure snapshot bounds child member
   and reservation rows (128/1024); reaching capacity fails closed.
   GC/compaction requires independently designed, lossless authority
   preserving semantics before a normal production consumer can exist.

The hard rule is **fail closed at I1 store uncertainty, but do not attach
these unqualified hooks to a normal live run**. Normal production behavior
remains unchanged until the next explicitly authorized phase.

## Verification and next decision

Required evidence:

- Isolated branch parent, worktree clean, file scope and SHA;
- offline test suite for this module (including separate process CAS,
  parent directory sync and post-rename uncertainty);
- Ruff/Pyright zero new diagnostics and relevant adjacent tests;
- official R9 whole-repo CI, security scan, staged-candidate check and
  post-commit verification.

The first formal R9 attempt correctly rejected the unregistered new
`task_budget_store.py` writer in
`test_durability_write_candidates_registered` (309 passed / 1 failed).
It was repaired by registering the **actual** T2 authority surface, not by
raising ratchet thresholds, exempting the writer or skipping the guard.

This is the **I0/I1 stop line**, not I2/I3 deployment authority. The next
step must be a separate authorization for a pure provider physical-attempt
adapter designed around the actual GLM-5.3 wire and existing RG-3C attempt
identities; live smoke remains prohibited. Keep gen206 Web Shadow with
Canary HOLD.
