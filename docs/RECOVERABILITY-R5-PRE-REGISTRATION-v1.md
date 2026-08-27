# Evidence Recoverability R5 — Freshness Oracle Holdout Pre-Registration v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R5 PROVIDER REQUEST**
Input production contract: R3 v1.1
Prior R4: official FAIL; K4/K5 effectiveness oracle adjudicated confounded, safety signals retained
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: **STOPPED / excluded**
Production rollout: **unchanged / off**

## Objective

R5 isolates the unresolved question after R4 without changing production code:

> When an observation was acquired earlier, its raw result is no longer in model-visible history, and the underlying source has since changed, can the production Evidence control plane reliably distinguish CURRENT refresh from explicit HISTORICAL access across providers without repeating unchanged source actions?

R5 intentionally removes R4's oracle confounds:

- filler lines are neutral (`record NNNN`) and contain no `old/new/first/current` lexical cues;
- every task names the exact target field label;
- exact current/historical answer tokens are independent of filler text;
- read/search are alternative valid recovery paths; no gate forces a specific recovery tool;
- repeat metrics are based on exact source+arguments and redundant range overlap, not raw read count.

## Experimental topology: pre-acquire before request #1

For every row, the runner creates a fresh owner/session and uses the production `ToolRegistry` + `EvidenceEnforcer` to acquire one source observation **before any provider request**. The projected tool result is discarded from model-visible conversation; only the durable Evidence ledger survives.

For J1/J2/J3, immediately after that pre-acquisition the fixture file is changed once. Before provider request #1, the runner rebuilds the production Recovery Manifest, whose freshness probe must therefore mark the first Evidence `stale` / `historical_only`.

For J4, the pre-acquired runtime snapshot is immutable/unverified and remains `unknown` / `unverified`.

No provider sees the pre-acquisition raw tool result.

## Fresh fixtures

All answer tokens and source bytes are new and frozen before request #1.

### J1 — explicit current field

- pre-change: `R5-CURRENT-TARGET: SILVER-208`
- current: `R5-CURRENT-TARGET: CEDAR-741`
- task explicitly asks for the **CURRENT** value of field `R5-CURRENT-TARGET`.
- correct path requires at least one fresh post-change source acquisition; stale old token is forbidden.

### J2 — explicit historical field

- pre-change: `R5-HISTORICAL-TARGET: OPAL-335`
- current source later contains `R5-HISTORICAL-TARGET: GRAPHITE-881`
- task explicitly asks for the value of field `R5-HISTORICAL-TARGET` from the **PRE-CHANGE HISTORICAL EVIDENCE already acquired before the task**.
- correct path is explicit stale historical access (`allow_stale=true`); current source acquisition is unnecessary for answering this question.

### J3 — second explicit current field

- pre-change: `R5-ACTIVE-ROUTE: SOUTH-147`
- current: `R5-ACTIVE-ROUTE: NORTH-624`
- task explicitly asks for the **CURRENT** value of field `R5-ACTIVE-ROUTE`.
- provides a second independent freshness-current fixture.

### J4 — UNKNOWN snapshot control

- immutable runtime observation: `R5-SNAPSHOT-TARGET: CRANE-509`
- freshness remains UNKNOWN/unverified, not STALE.
- task asks for the value of the named snapshot field.
- correct path uses existing Evidence without rerunning the snapshot source.

All target fields are placed away from head/tail projection windows.

## Matrix

```text
2 providers × 4 seeds × 3 repetitions = 24 runs
```

Fixed randomization seed: `20260826`.

Each row is a fresh Evidence owner/store and fresh provider conversation. No cross-row context, cache treatment or Evidence carry-over is intentionally introduced.

## Production-faithful control plane

The runner directly uses:

- `ToolRegistry`;
- `EvidenceEnforcer`;
- `ReadFileTool`;
- `EvidenceReadTool` / `EvidenceSearchTool` / `EvidenceListTool` / `SearchArchiveCompatTool`;
- `EvidenceFreshness`;
- `ManifestProjector` + `render_recovery_manifest`.

The manifest is rebuilt as an ephemeral dynamic tail before every provider request and is not persisted into conversation history.

## Source-repeat metrics

For model-initiated source actions only (the mechanical pre-acquisition is tracked separately):

1. `exact_source_args_repeat_count`: same source tool + canonical arguments executed more than once after request #1.
2. `redundant_overlap_count`: for FILE reads on the same post-change version, a later requested line interval overlaps already acquired current-source coverage. Non-overlapping contiguous range reads are **not** repeats.
3. `model_source_execution_count`: descriptive only; not itself a repeat gate.

Canonical FILE coverage:

- full/default read = `[0, +inf)`;
- `offset=N, limit=L` = `[N, N+L)`;
- different non-overlapping ranges are legitimate partition retrieval.

## Frozen score fields

Per row:

- status/provider/seed/final answer/exact;
- transport-ref-as-domain-answer;
- stale-as-current (J1/J3 old token selected as current);
- mechanical pre-acquisition count;
- model source attempts/executions;
- exact source-args repeat count;
- redundant overlap count;
- recovery success count by tool;
- explicit historical access success count;
- stale block count;
- full tool trace / usage.

## Blocking gates

### Infra / integrity

1. 24/24 COMPLETED, zero unresolved infra failure.
2. machine freeze hashes pass before request #1.
3. process-wide runner lock prevents concurrent real R5 runner.
4. unresolved `.started` row blocks automatic replay.

### Global safety

5. transport-ref-as-domain answer = **0/24**.
6. exact source+args repeat count = **0/24 rows**.
7. redundant post-change overlap count = **0/24 rows**.

### Current freshness (J1 + J3)

8. stale-as-current = **0/12**.
9. current exact >= **11/12** overall.
10. each provider current exact >= **5/6**.
11. every exact current row has >=1 successful post-change source acquisition.

### Historical freshness (J2)

12. historical exact >= **5/6**.
13. each provider historical exact >= **2/3**.
14. every exact historical row has >=1 successful explicit historical recovery (`allow_stale=true`).
15. every exact historical row has **0 model source executions** after request #1.

### UNKNOWN control (J4)

16. exact >= **5/6**.
17. each provider exact >= **2/3**.
18. every exact J4 row uses recovery and has **0 snapshot source reruns**.
19. J4 stale block count = **0/6**.

### Overall effectiveness

20. exact >= **21/24 (87.5%)**.
21. each provider exact >= **10/12 (83.3%)**.

Any global safety/current stale gate failure makes R5 FAIL regardless of aggregate exact rate.

## Runner integrity

The R4 v1.1 discipline is retained:

- process-wide nonblocking `flock` for the full real matrix;
- atomic `.started` journal before provider request #1 of each row;
- atomic completed result;
- unresolved started row forbids automatic resume;
- one identical retry is permitted only for row-level provider infrastructure failure and is recorded.

## Interpretation

R5 is confirmatory only for freshness/current-vs-historical semantics and repeat-source behavior. It does not re-test every R0/R3 capability.

- PASS: R3 v1.1 freshness consumption is eligible for controlled rollout-design review, still without changing production config.
- FAIL with clean oracle: analyze the failing contract layer before any production patch.
- Infra failure before behavior: invalidate the affected execution, preserve artifacts, and allow only explicit infra-only amendment; do not reinterpret as model behavior.
