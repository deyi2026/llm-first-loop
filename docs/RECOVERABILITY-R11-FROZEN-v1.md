# Evidence Recoverability R11 — Frozen Long-Session Stress v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST R11 REAL PROVIDER REQUEST**
Model: DeepSeek `deepseek-v4-flash`
Conditions: isolated `off` then isolated `enforce`
A3: STOPPED
Production configuration: unchanged

R11 uses actual mirror Web/LoopEngine sessions with a copied per-condition provider registry whose only deliberate stress change is DeepSeek `history_budget_chars=50000`. Each condition has a separate `DATA_DIR`, event log, Evidence store, audit directory and Web process. The global `.env` and `data/providers.json` are not edited.

Ten fresh source files and a fixed 12-turn user scenario are shared byte-for-byte across modes. Each mode receives an unscored warmup session before its measured session.

Blocking gates and paired thresholds are exactly those in `docs/RECOVERABILITY-R11-PRE-REGISTRATION-v1.md` and the frozen harness. No post-hoc threshold or task prompt changes are allowed after request #1.

Pre-real verification: source hashes prepared, Ruff PASS, Pyright 0/0, analyzer/gate tests PASS. The harness verifies this machine lock before each real mode run.
