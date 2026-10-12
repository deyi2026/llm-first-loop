# Evidence Recoverability R13 — Frozen Fresh Paired Long-Session Stress v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST R13 REAL PROVIDER REQUEST**
Model: DeepSeek `deepseek-v4-flash`
Conditions: isolated `off` / isolated `enforce`
A3: STOPPED
Production configuration: unchanged

R13 is the clean paired replacement after R12 removed the production enforce+pipeline startup blocker. It uses the actual Web -> LoopEngine -> DeepSeek -> ToolRegistry path, current production pipeline settings, separate per-mode DATA_DIR/LFL_DATA_DIR, identical fresh source bytes/user turns, and a copied provider registry with only DeepSeek `history_budget_chars=50,000` for compression stress.

Pre-request analyzer corrections are frozen: ordinary non-success tool results are diagnostic only; blocking run integrity is unresolved `run.end` error; cache.window boundary backjumps are diagnostic-only and not prompt-structure gates.

Per-mode and paired blocking gates are exactly `docs/RECOVERABILITY-R13-PRE-REGISTRATION-v1.md` plus this frozen harness. No post-request threshold/task/analyzer edits are allowed.

Pre-freeze: unseen source tokens/hashes prepared, Ruff PASS, Pyright 0/0, analyzer/gate tests PASS, current production R12/R9 code already R0/full-repo green. Port 8919 is dedicated to each sequential subprocess run.
