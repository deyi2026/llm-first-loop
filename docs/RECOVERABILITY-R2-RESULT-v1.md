# Evidence Recoverability R2 — Fresh Provider Confirmation Result v1

Date: 2026-08-26
Frozen contract: `docs/RECOVERABILITY-R2-FROZEN-v1.md`
Providers: MiniMax `MiniMax-M3` + DeepSeek `deepseek-v4-flash`
Overall frozen-score status: **FAIL**
Production activation: **NOT ELIGIBLE**
A3: **STOPPED / not part of R2**

## Executive result

R2 separates the upstream recoverability fix from the remaining model-consumption problem.

The Evidence layer **did solve the original source re-execution mechanism** for reusable evidence:

- E1 reusable source-once: **30/30 (100%)**;
- E1 reusable source re-execution: **0/30 (0%)**;
- B0 reusable source re-execution: **18/30 (60%)**;
- paired B0-E1 re-execution-rate delta: **+0.60**, conservative Wilson interval **[0.3097, 0.7541]**;
- successful reusable answers that used Evidence hydration: **17/17 (100%)**;
- side-effect duplicate executions inside scored runs: **0**.

However, provider effectiveness and freshness safety did **not** satisfy the frozen gates:

- reusable exact answer: **17/30 (56.7%)**, required >=90%;
- MiniMax reusable exact: **5/15 (33.3%)**, required >=80%;
- DeepSeek reusable exact: **12/15 (80.0%)**, exactly at provider floor but overall gate still fails;
- F6 legitimate freshness refresh: **2/6 (33.3%)**;
- MiniMax F6 refresh: **0/3**;
- DeepSeek F6 refresh: **2/3**;
- stale-as-current: **4** (required 0).

Therefore the correct conclusion is not “Evidence failed”. The stronger conclusion is:

> Stable EvidenceRef + exact hydration removes a major program-induced repeat-source mechanism, but the current model-facing recovery protocol does not yet make evidence completeness, transport metadata, and freshness/currentness semantics reliable enough across providers.

## Frozen scorer result

Machine report: `data/audit/evidence_r2/score_real_v1.json`

Frozen gates:

| Gate | Result |
|---|---|
| infra complete | PASS — 72 rows, 0 row-level infra failures |
| zero side-effect duplicate + zero stale-as-current | **FAIL** — duplicate 0, stale 4 |
| reusable exact overall >=90% | **FAIL** — 17/30 |
| reusable exact each provider >=80% | **FAIL** — MiniMax 5/15; DeepSeek 12/15 |
| source-once overall >=90% | PASS — 30/30 |
| source-once each provider >=80% | PASS — both 15/15 |
| hydration among successful reusable >=80% | PASS — 17/17 |
| F6 legitimate refresh each provider >=80% | **FAIL** — MiniMax 0/3; DeepSeek 2/3 |
| E1 re-execution lower than B0 | PASS — 0% vs 60% |

## Failure mechanism audit

### 1. Pagination completeness is not a mechanical contract

Representative MiniMax run `R2-037` (F1/E1):

1. source executed once and produced a stable EvidenceRef;
2. model called `read_evidence(start=0, limit=4000)` once;
3. the answer marker was beyond that first page;
4. despite continuation being available, the model stopped and answered generic filler.

The current interface exposes bounded bytes and a continuation cursor, but “this page is not the complete observation” remains a model interpretation problem rather than a machine-enforced semantic state.

### 2. EvidenceRef transport identity can be confused with domain identity

Representative DeepSeek run `R2-026` (F4/E1):

1. side-effect action executed exactly once;
2. result was captured under `evidence://v1/...`;
3. model hydrated only the first page, before the receipt marker;
4. final answer was the **EvidenceRef itself** rather than the receipt ID.

The transport handle is currently highly salient in the recovery frame while its role as non-domain metadata is only conventional text. F4 exposed a real namespace/typing ambiguity.

### 3. Recoverable does not mean current

Four uncontaminated F6/E1 runs used stale v1 evidence as current truth:

- `R2-024` MiniMax
- `R2-028` DeepSeek
- `R2-035` MiniMax
- `R2-044` MiniMax

`R2-024` is the clearest example: the recovery frame marked the old observation stale; MiniMax hydrated all four pages of that old Evidence and returned `OLD-103` without performing the required fresh source read.

By contrast, successful `R2-052` DeepSeek first inspected old Evidence, then re-read the changed source, obtained a new v2 EvidenceRef, hydrated v2, and returned `NEW-947`.

This proves freshness/currentness requires its own machine-level contract. Exact old bytes are useful historical evidence, but exactness alone must never imply current authority.

## Execution-integrity deviation

A crash-safe resume process ended after 58 persisted rows. During recovery, a second resume process appeared before the later process was detected, creating a short dual-runner overlap. The later-started process was terminated immediately.

Because R2 clients run with `guard_enabled=False`, `guarded_requests.jsonl` does not provide request-level IDs for this experiment. Therefore the exact count of duplicate provider requests during the overlap cannot be mechanically proven to be zero.

The conservatively affected window is **R2-059..R2-064**. This is recorded as an execution-integrity deviation and is not silently ignored.

### Sensitivity analysis

Deleting the entire R2-059..064 window still independently produces a decisive FAIL:

- unaffected reusable exact: **15/27 (55.6%)**;
- unaffected MiniMax reusable exact: **3/12 (25.0%)**;
- unaffected MiniMax F6 legitimate refresh: **0/3**;
- unaffected stale-as-current: **4**;
- all four stale failures occurred before the overlap window.

Therefore the exact 72-run point estimates should carry the execution-integrity caveat, but **the preregistered PASS/FAIL decision is robust to removing every possibly affected row**. No post-hoc rerun is used to rescue the result.

## Post-run integrity

- R2 unit tests: **7/7 PASS**;
- all Evidence tests: **99/99 PASS**;
- targeted Ruff: **PASS**;
- targeted Pyright: **0 errors / 0 warnings**;
- frozen `spec.md` SHA-256 unchanged: `97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771`;
- frozen `design.md` SHA-256 unchanged: `95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b`;
- frozen scorer SHA-256 unchanged: `3c00a0b13d252c2bcf9e5c0e53991555b485d19a920521f6a51da2b4af88ac82`;
- amended machine freeze SHA-256 unchanged: `538be9ac5db8aca0cd66739be10675bd0e6242603605ecc66c3fba40d4f9a6df`;
- no R2 change to core prompt, stopped A3 test, or frozen ev_recov spec/design.

## Architecture decision

R0 and R1 remain valid: the system can durably preserve and recover observations that old program paths lost after projection/compression. R2 adds a new boundary:

```text
recoverability continuity       PASS
source re-execution reduction   PASS
cross-provider evidence use     FAIL
freshness/currentness safety    FAIL
```

Production `EVIDENCE_MODE=enforce` remains **not eligible**.

The next fix must not be an anti-repeat prompt or Action Guard. It must strengthen the Evidence consumption contract itself:

1. separate transport metadata from hydrated domain content with a structured envelope;
2. make pagination completeness/continuation explicit machine state, not a prose hint;
3. make stale probeable Evidence historical-only by default, with an explicit safe path to refresh current source state;
4. keep exact stale hydration available for historical/audit tasks without allowing stale bytes to masquerade as current truth;
5. validate the revised contract with a new fresh fixture family rather than reusing R2 outcomes as confirmatory data.
