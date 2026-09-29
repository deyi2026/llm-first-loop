# Deployment Qualification — Canonical Main → Production gen161

- Date: 2026-09-29
- Qualified source: `43e02a35d2e1bac85fc7e9278178ed446685319a`
- Production baseline: `67ce123c5fa8430ab833610857fbf276d55e589d` / gen161
- Verdict: **QUALIFIED_FOR_DEPLOYMENT**
- Deployment performed in Phase 20: **no**

## Why the delta is bounded

Production gen161 is the merge-base and ancestor of current main. Main is **32 commits / 125 paths** ahead, but the path ledger is dominated by governance and knowledge assets: 45 docs, 66 runtime Method records, 3 tests, 7 other repository/experience paths, and only **4 runtime code/script paths**.

Those four deployable runtime paths are byte-identical to the versions already qualified in Phase 16:

- `scripts/restart_feishu.sh` — `e320fcf1a0e2f60fb7af17d6183c47b6862e75893e261188552ca4c75f247ddc`
- `scripts/restart_system.sh` — `024442d9262d8043b490de6d128ee6079d4d5679e3ddb553a47dc91bc06352fb`
- `src/llm_loop/cache_guard/guard.py` — `5fdb22d3d75ee379bae1090b685b13e0e00c049474224592cbcb39647f9a247d`
- `src/llm_loop/llm/chatgpt_page.py` — `04d82ea090f564b67364cddf0a68280875c5a0e53ff501f241e8171ac2c94bec`

No commit after the Phase16 qualification changed these paths. WebUI source is also identical between main and gen161. `docs/ai_rules.md`, `methods/`, and `skills/` are content-identical across the code roots.

## Shared knowledge data is not waiting for deploy

The running gen161 manifests bind `data_dir` to canonical `<repo-root>/data`, `methods_dir` to `<repo-root>/data/methods`, and `experiences_dir` to `<repo-root>/experiences`. Therefore the 66 additional tracked candidate Method records are already part of the shared runtime data plane. A code deployment changes the code root; it is not what makes those runtime Method records visible.

## Current qualification gates

- Runtime changed tests: **20/20 PASS**.
- Broadened cache/ChatGPT/restart adjacency: **108/108 PASS**.
- Code-nav / Skills / real-Pyright focused suite: **66/66 PASS**.
- WebUI: **35 files / 263 tests PASS**; `tsc -b && vite build` PASS.
- Restart shell syntax, runtime-delta Ruff, `compileall`, and `git diff --check`: **PASS**.
- Full main pytest: **7301 passed / 107 skipped / 16 deselected / 9 failed / 3 warnings**.
- Exact production replay of those failures: **9/9 same nodes** → candidate-only failures **0**.
- Ruff historical scope (`src tests scripts`): **32 vs 32**, exact fingerprint, main-only **0**.
- Supplemental broad Ruff scope (`.`): **148 vs 148**, exact fingerprint, main-only **0**.
- Pyright: **389 files / 58 errors / 0 warnings** on each side; exact fingerprint; main-only **0**.
- Real root-main Web-GPT smoke: exact `PHASE20_ROOT_MAIN_OK`, `tool_calls=0`, `finish_reason=stop`, provider `chatgpt-web`, xhigh reasoning, isolated canary session store.
- Active authority stale non-production worktree refs: **0**.
- Live process stale non-production worktree refs: **0**.
- Root clean; **3 local branches / 2 worktrees**.
- Production `service_control verify`: **gen161 PASS**.

The nine pytest failures and static findings are therefore existing production-baseline debt, not candidate regressions. The qualification rule is candidate-only regression = 0, and that gate passes.

## Decision

`main@43e02a35d2e1bac85fc7e9278178ed446685319a` is **QUALIFIED_FOR_DEPLOYMENT** as a no-new-regression successor to production gen161.

Phase 20 intentionally does **not** publish, restart, or cut over any service. The next phase is a separate generation-CAS deployment boundary and requires explicit owner authorization plus an immediate preflight before mutation.
