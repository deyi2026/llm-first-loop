# Evidence Recoverability R10 — Physical Source Resolution Provider Holdout v1

Date: 2026-08-26
Status: PRE-REGISTERED BEFORE ANY R10 REAL PROVIDER REQUEST
Input: R3 currentness + R6 model contract + R9 EvidenceSourceResolver
Providers: MiniMax-M3, deepseek-v4-flash
A3: STOPPED
Production mode: unchanged/off

## Objective

Confirm on fresh unseen file bytes that provider-declared source fallbacks no longer imply redundant physical source acquisition. The model may still precommit a `read_file` fallback in a parallel tool batch; if verified-current Evidence already covers the request, R9 must satisfy that declaration as `evidence_reuse` without file I/O or a new EvidenceRecord.

## Fresh fixtures

- T1: no preacquire; buried `R10-ALPHA-TARGET: GARNET-324`.
- T2: no preacquire; buried `R10-BETA-TARGET: MOSS-781`.
- T3: full old Evidence, mutate `KHAKI-127 -> MAROON-968`, CURRENT task; exactly one post-change physical read is legitimate.
- T4: current precoverage `[0,68)`, target `TURQUOISE-654` hinted in `[112,172)`; one non-overlapping physical gap acquisition is legitimate.

24 runs = 2 providers × T1..T4 × 3 reps, fixed seed 20260826.

## Mechanical distinction

For every model-declared successful `read_file`:

- `source_execution_performed=true` -> physical acquisition; contributes to physical repeat/overlap accounting.
- `source_execution_performed=false` -> Evidence reuse; does not contribute to physical source execution/overlap.

Declared source call count is diagnostic. A provider is not penalized merely for precommitting a fallback that R9 truthfully resolves from current Evidence.

## Blocking gates

1. 24/24 COMPLETED; zero unresolved infra.
2. transport EvidenceRef as domain answer = 0.
3. T3 stale-as-current = 0.
4. physical exact same source+args repeat = 0.
5. physical redundant overlap = 0.
6. overall exact >=22/24; each provider >=10/12.
7. T1+T2 exact >=11/12; each provider >=5/6.
8. T3 exact >=5/6; each provider >=2/3.
9. T4 exact >=5/6; each provider >=2/3.
10. Every exact T1/T2 row has exactly one physical source acquisition and a recovery result containing target.
11. Every exact T3 row has exactly one post-change physical source acquisition and recovery containing current target.
12. Every exact T4 row has exactly one physical gap acquisition, zero physical overlap, and recovery containing target.
13. Every successful model-declared read_file is accounted as physical execution or Evidence reuse.

No gate requires provider tool-call declaration count to be one.
