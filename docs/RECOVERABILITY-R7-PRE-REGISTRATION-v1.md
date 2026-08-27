# Evidence Recoverability R7 — Covered-Recovery Efficiency Holdout Pre-Registration v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R7 PROVIDER REQUEST**
Input production contract: R3 freshness/currentness + R6 shared source-vs-recovery tool contract
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: **STOPPED / excluded**
Production rollout: **unchanged / off**

## Objective

R7 tests the sole residual isolated by R5: after a source observation is already durably represented by Evidence, does the model recover covered bytes/results instead of reacquiring overlapping source ranges, while still acquiring a genuinely uncovered range when coverage is insufficient?

This is a behavioral efficiency holdout, not a duplicate-call blocker test. Source acquisition remains legitimate for freshness and coverage gaps.

## Fresh unseen fixtures

All R7 bytes/tokens are new.

- **Q1 covered full / field A**: no pre-acquire. The model must acquire the current file once; target `R7-PRIMARY-TARGET: AMBER-612` is buried outside projection head/tail. After that full acquisition, all file bytes are already covered by Evidence.
- **Q2 covered full / field B**: independent no-preacquire file with buried `R7-SECONDARY-TARGET: IVORY-374`; same covered-recovery question on different content/position.
- **Q3 stale then current refresh**: full old Evidence is mechanically pre-acquired, then source mutates from `MINT-105` to current `PLUM-842` before provider request #1. One post-change source acquisition is legitimate; after that, further overlapping reads are redundant. Stale-as-current is forbidden.
- **Q4 real coverage gap**: current file Evidence for lines `[0,60)` is mechanically pre-acquired and remains current. Target `R7-GAP-TARGET: ONYX-913` is in the hinted source line window `[100,160)`. A non-overlapping source range acquisition covering the target is legitimate; reacquiring already-covered `[0,60)` bytes is redundant.

Filler is neutral and carries no target-like lexical values.

## Matrix

`2 providers × 4 seeds × 3 reps = 24 runs`, fixed random seed `20260826`.
Each row uses a fresh owner/store/conversation. No cross-row Evidence is shared.

## Production-faithful path

The runner uses production `ToolRegistry`, `ReadFileTool`, `EvidenceEnforcer`, `EvidenceReadTool`, `EvidenceSearchTool`, `EvidenceListTool`, `SearchArchiveCompatTool`, `EvidenceFreshness`, `ManifestProjector`, and `render_recovery_manifest`. Therefore the provider sees the actual R6 `read_file` description, not a holdout-specific paraphrase.

## Efficiency metrics

For model-initiated `read_file` calls:

1. `exact_source_args_repeat_count`: repeated canonical `(path, offset, limit)` after request #1.
2. `redundant_overlap_count`: a successful current-version file interval overlaps current-version coverage already acquired for the row.
   - Q1/Q2 begin with no coverage; first model read is legitimate.
   - Q3 pre-acquired coverage is stale after mutation and is not seeded as current coverage; first post-change model read is legitimate.
   - Q4 pre-acquired `[0,60)` is current and is seeded into coverage accounting; later overlap with it is redundant.
3. Non-overlapping uncovered intervals are legitimate even when multiple source calls are needed.

Raw source-call count alone is descriptive, not a global failure criterion.

## Blocking gates

### Integrity / safety

1. 24/24 `COMPLETED`, no unresolved infra failure.
2. frozen artifact hashes pass before request #1.
3. single real runner lock and `.started` crash journal discipline.
4. transport EvidenceRef used as domain answer = 0/24.
5. exact source+args repeat rows = 0/24.
6. redundant overlap rows = 0/24.
7. Q3 stale-as-current = 0/6.

### Correctness

8. overall exact >= 22/24.
9. each provider exact >= 10/12.
10. Q1+Q2 covered fixtures exact >= 11/12; each provider >= 5/6.
11. Q3 exact >= 5/6; each provider >= 2/3.
12. Q4 exact >= 5/6; each provider >= 2/3.

### Contract-path gates

13. Every exact Q1/Q2 row has exactly one successful model source acquisition and at least one recovery result containing the target answer.
14. Every exact Q3 row has exactly one successful post-change model source acquisition, at least one stale block, and later recovery containing the current answer.
15. Every exact Q4 row has at least one successful model source acquisition, zero redundant overlap, and a recovery result containing the target answer.

No gate requires a specific recovery tool (`search_evidence` and `read_evidence` are both valid).

## Interpretation

PASS means the R6 source-vs-recovery contract is eligible to remain as the model-facing efficiency contract for rollout design review. FAIL is analyzed at the failing semantic layer; no post-hoc prompt or scorer modification is allowed.
