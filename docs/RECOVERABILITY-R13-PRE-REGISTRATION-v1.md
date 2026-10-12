# Evidence Recoverability R13 — Fresh Paired Long-Session / Compression / Cache Stress v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R13 PROVIDER REQUEST**
Model: `deepseek/deepseek-v4-flash`
Conditions: isolated `off` vs isolated `enforce` on the same R12-integrated production tree
A3: STOPPED
Production `.env` / `data/providers.json`: unchanged

## Purpose

R13 is the clean paired replacement for invalidated R11 v1. It tests whether R3/R6/R9/R12 improve long tool-session correctness and physical source reuse under forced compression while preserving stable tools/model/budget and acceptable provider-cache behavior.

R11 v1 B0 is historical evidence only and is not paired causally with R13 because R12 production integration changed after that baseline.

## Isolation and stress

Each condition uses a fresh Web subprocess, dedicated DATA_DIR/LFL_DATA_DIR, and a copied provider registry. The only stress change is DeepSeek `history_budget_chars=50,000`. Global `.env` remains `HISTORY_MAX_CHARS=1,000,000`; global provider registry is untouched.

Each mode gets an unscored warmup before a fixed 12-turn measured session. Ten entirely new R13 source files/tokens are shared byte-for-byte across the two modes.

## Analyzer corrections frozen before request #1

R11 v1 exposed two analyzer mistakes which are corrected in R13 before any new request:

1. non-success tool results (e.g. recovery MISS/business failure) are diagnostic `tool_non_success_count`, not protocol failures. The blocking execution gate is now `run.end.reason == completed` for all measured turns plus successful HTTP completion.
2. `cache.window.boundary_msg_index` backward motion is retained as diagnostic only. It reflects provider cache coverage/window movement and is not itself proof of prompt structural mutation.

Structural blocking signals remain stable tools_count/model/budget, compression storm/streak, persistent cache-hit cliff, correctness and physical source reacquisition.

## Per-mode blocking gates

1. 12/12 turns complete; >=11/12 contain every mechanically expected code; final turn contains all ten.
2. one model only: DeepSeek flash.
3. tools_count has one value across measured requests.
4. request budget has one value = 50,000.
5. unresolved run errors = 0.
6. max consecutive request intervals with compression <5.
7. max compression events between adjacent request.meta <=3.
8. no run of 3 consecutive cache.window hit_ratio <0.50 after request 2.
9. median cache.window hit_ratio after request 2 >=0.70.

## Paired blocking gates

10. enforce physical repeated-source-path count <= off.
11. enforce total physical read count <= off + 10 distinct introduced sources.
12. enforce context.compressed count <= off.
13. enforce max compression streak <= off +1.
14. enforce post-warmup median cache hit ratio not worse than off by >0.10 absolute.
15. enforce prefix-cliff count <= off.

Evidence reuse and recovery declarations are diagnostic. Provider-declared fallback calls are not failures if R9 resolves them without physical source I/O.
