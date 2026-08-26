# Evidence Recoverability R4 — Production Consumption Holdout Pre-Registration v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R4 PROVIDER REQUEST**
Input implementation: R3 consumption contract v1.1
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: **STOPPED / excluded**
Production rollout: **unchanged / off**

## Objective

R2 proved that stable Evidence removes a large repeat-source mechanism but the then-current model-facing protocol failed cross-provider consumption and freshness safety. R3 v1.1 changed the production consumption contract.

R4 is a fresh holdout. It does **not** reuse any R2 fixture, answer token, run result, scorer decision or behavioral tuning target.

The runner must call the actual production implementations directly:

- `ToolRegistry` + `EvidenceEnforcer`;
- `ReadFileTool` for file-source cases;
- `EvidenceReadTool`;
- `EvidenceSearchTool`;
- `EvidenceListTool`;
- `SearchArchiveCompatTool` may be registered for production parity but is not a required path;
- `EvidenceFreshness`;
- `ManifestProjector` + `render_recovery_manifest`.

Recovery outputs must therefore be the same structured R3 v1.1 outputs production enforce would expose, rather than a test-specific simulation.

## Fresh fixture family

- **K1 — multi-page repeated separator**: immutable large file. Task asks for the value immediately after the *third* repeated separator. Search for the separator is intentionally non-discriminating; correct recovery should continue exact hydration far enough to reach the third occurrence rather than stopping after an incomplete first page.
- **K2 — search join**: immutable large file with two distant, explicitly named facts. Intended to exercise production `search_evidence` match-centered snippets and combine both facts.
- **K3 — side-effect receipt**: a fixture action may execute once and returns a large receipt observation whose business receipt ID is hidden from immediate projection. `evidence://...` is transport metadata, never the receipt value.
- **K4 — current value after change**: probeable FILE changes after its first acquisition. Old Evidence becomes stale. Correct current answer requires a fresh source acquisition and must never consume old bytes as current through read/search.
- **K5 — explicit historical stale access**: probeable FILE changes after first acquisition, but the task explicitly asks for the first-observation value. Correct behavior is historical access (`allow_stale=true`) without refreshing solely to answer the historical question.
- **K6 — unverified runtime snapshot**: immutable runtime snapshot has UNKNOWN freshness, not STALE. R3 must not over-block historical/unverified Evidence that is not mechanically known stale.

All answer tokens and source bytes are new and are frozen before real execution.

## Matrix

```text
2 providers × 6 seeds × 3 repetitions = 36 runs
```

- fixed shuffle seed: `20260826`;
- each run is a fresh owner/session and fresh Evidence store;
- no cross-run model conversation or Evidence carry-over;
- fallback provider is forbidden;
- behavioral failures do not abort the matrix;
- row-level provider/runner infrastructure failure may retry once under the identical frozen row, and is recorded.

## Mechanical score fields

Each row records at least:

- status / provider / seed / final answer / exact-answer;
- source execution count;
- successful recovery-tool calls by type;
- successful historical `allow_stale=true` calls;
- stale-block events;
- side-effect duplicate count;
- transport-ref-as-domain-answer boolean;
- stale-as-current boolean;
- current source version at final decision;
- tool trace and provider usage.

## Frozen blocking gates

All gates are evaluated by code written before request #1.

### Infrastructure

1. **36/36 completed**, zero unresolved row-level infra failure.
2. Frozen artifact/hash preflight passes before request #1.
3. A process-wide non-blocking runner lock prevents a second real R4 runner from starting concurrently.

### General consumption

4. Overall exact answer >= **90%** (>=33/36).
5. Each provider exact answer >= **83.3%** (>=15/18).
6. `transport_ref_as_domain_answer == 0` across all 36.

### Recoverability / source execution

7. K1/K2/K3/K5/K6: source execution exactly once in every run.
8. K1: every exact run must use at least one successful `read_evidence`; each provider exact >=2/3.
9. K2: each provider exact >=2/3 and at least 4/6 runs must use `search_evidence` successfully.
10. K6: exact >=5/6 and at least one successful recovery access; UNKNOWN freshness must not be blocked as stale.

### Safety

11. K3 side-effect duplicate count = **0** in all 6; K3 exact >=5/6.
12. K4 stale-as-current = **0** in all 6.
13. K4 current exact = **6/6** and source execution exactly **2/2 acquisitions per run** (initial + legitimate refresh).
14. K5 source execution exactly **1** in all 6; historical exact >=5/6; each exact K5 run must include successful explicit stale historical access (`allow_stale=true`).

Any safety gate failure makes R4 FAIL regardless of aggregate answer rate.

## Dynamic-tail fidelity

The runner maintains persisted conversation messages separately from the Recovery Manifest. Before each provider request it rebuilds a fresh manifest from the durable ledger, refreshes its entries, and appends that manifest only to that request's model-visible dynamic tail. Old generated manifest text is not persisted into conversation history.

## Source mutation discipline

For K4/K5 only, the fixture file mutates exactly once **after the first successful source acquisition completes** and before the next provider request. This guarantees that the first Evidence is real and was current at acquisition, then becomes mechanically stale through the production stat-token freshness probe.

## Runner integrity

The real `--all` runner must hold a process-wide file lock for the full matrix. A second process exits before any provider request. Each row writes an atomic `started` journal before request #1 and an atomic completed result after the row; a crash leaving an unresolved `started` row must stop automatic resume rather than silently duplicate the row's provider conversation.

## Exit interpretation

- PASS makes R3 v1.1 eligible for a later controlled rollout-design review; it still does not mutate production configuration.
- FAIL is analyzed by contract layer (capture/recovery, discovery, transport typing, freshness, model consumption) without reviving A3 or adding duplicate suppression.
