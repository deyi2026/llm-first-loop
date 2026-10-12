# Evidence Recoverability R10 — Frozen Physical Source Resolution Holdout v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST R10 REAL PROVIDER REQUEST**
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: STOPPED
Production Evidence activation: unchanged/off

R10 is the fresh provider confirmation of R9 Evidence-aware source resolution. The provider may declare redundant `read_file` fallbacks; correctness is judged by physical source execution, not declaration count.

Frozen matrix: 24 rows = 2 providers × T1..T4 × 3 reps, seed 20260826.

Blocking semantics are exactly the pre-registration/scorer:
- zero physical same-args repeat;
- zero physical redundant overlap;
- one legitimate physical read per exact row for covered/current/gap scenarios;
- any excess successful read_file declarations must be accounted as `evidence_reuse`;
- stale-as-current and transport-ref-as-domain remain zero;
- correctness thresholds remain frozen.

The runner uses production R9 `EvidenceSourceResolver`, `ReadFileTool`, ToolRegistry, Evidence capture/freshness/search/read tools. It does not suppress, rewrite or remove tool declarations.

Pre-freeze: Ruff PASS, Pyright 0/0, focused tests PASS, dry 24/24 exact, dry scorer PASS, R0 12/12, both provider credentials present, real result dir empty, no R10 runner active.
