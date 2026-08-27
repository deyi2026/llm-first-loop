# Evidence Recoverability R8 — Clean Covered-Recovery Efficiency Holdout Pre-Registration v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R8 PROVIDER REQUEST**
Input: R3 currentness safety + R6 shared source-vs-recovery contract
R7 v1: invalidated after first row due oracle requiring unnecessary stale hydration
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: STOPPED
Production rollout: unchanged/off

## Objective

Confirm with fresh unseen source bytes that covered Evidence is recovered rather than reacquired with overlapping `read_file` ranges, while a real coverage gap remains eligible for non-overlapping source acquisition.

## Fresh fixtures

- P1: no preacquire, buried `R8-ALPHA-TARGET: CORAL-286`.
- P2: no preacquire, independently buried `R8-BETA-TARGET: SLATE-731`.
- P3: full old Evidence preacquired, then file changes `LIME-214 -> AZURE-683`; task asks CURRENT.
- P4: current Evidence only for `[0,64)`; target `R8-GAP-TARGET: BRONZE-957` is in hinted `[104,164)` range. A non-overlapping later source acquisition is correct.

No provider has seen these R8 bytes/tokens before request #1.

## Matrix

24 runs = 2 providers × P1..P4 × 3 reps, fixed shuffle seed 20260826, fresh owner/store/conversation per row.

## Metrics

- exact source+canonical-args repeat count;
- redundant overlap against already-current acquired coverage;
- model source executions (descriptive/path gate);
- recovery result containing target answer;
- transport-ref-as-domain answer;
- P3 stale-as-current.

P4 current precoverage `[0,64)` is seeded into overlap accounting. P3 old full coverage is stale after mutation and is not seeded as current coverage.

## Blocking gates

1. 24/24 COMPLETED, zero unresolved infra.
2. frozen hashes pass before request #1; single runner lock + `.started` journal discipline.
3. transport-ref-as-domain=0.
4. exact source+args repeat count=0.
5. redundant overlap count=0.
6. P3 stale-as-current=0.
7. overall exact >=22/24; each provider >=10/12.
8. P1+P2 exact >=11/12; each provider >=5/6.
9. P3 exact >=5/6; each provider >=2/3.
10. P4 exact >=5/6; each provider >=2/3.
11. every exact P1/P2 row: exactly one successful model source acquisition and recovery contains target answer.
12. every exact P3 row: exactly one successful post-change model source acquisition and recovery contains current target answer. **A stale hydration attempt/block is optional diagnostic behavior, not a gate**, because the Manifest already exposes stale/historical_only before the request.
13. every exact P4 row: >=1 successful model source acquisition, zero redundant overlap, recovery contains target answer.

No gate bans repeated calls categorically; freshness and uncovered ranges remain legitimate acquisition reasons.
