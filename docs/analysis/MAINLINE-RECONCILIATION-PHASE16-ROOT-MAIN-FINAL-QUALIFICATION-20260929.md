# Mainline Reconciliation Phase 16 — Root-Main Final Qualification

- Date: 2026-09-29
- Qualified head before evidence commit: `4082dca6518bf9994e2c86ffc7aaa186467657f7`
- Production baseline: `gen161@67ce123c5fa8430ab833610857fbf276d55e589d`
- Result: **PASS — no new regressions against gen161 baseline**

## Full regression

Root-main full pytest: **7301 passed / 107 skipped / 16 deselected / 9 failed**. The exact same nine failing nodes reproduce on the production gen161 worktree, so Phase 16 records **0 candidate regression failures**. This closes reconciliation by no-regression evidence; it does not claim the repository has zero pre-existing debt.

The nine production-baseline failures are:

- `tests/unit/test_arch_guards.py::test_local_imports_ratchet`
- `tests/unit/test_arch_guards.py::test_runtime_cycles_match_known`
- `tests/unit/test_resolved_episode.py::test_engine_second_run_retires_first_episode_but_episode_is_retrievable`
- `tests/unit/test_resolved_episode.py::test_engine_anchor_remap_preserves_current_tool_protocol_after_retirement`
- `tests/unit/test_runtime_paths.py::test_load_settings_materializes_persistent_knowledge_paths`
- `tests/unit/test_safety.py::test_evo1_home_subpath_allowed_home_itself_blocked`
- `tests/unit/test_safety_bypass.py::test_rm_rf_tilde_subdir_allowed`
- `tests/unit/test_safety_bypass.py::test_rm_rf_home_var_subdir_allowed`
- `tests/unit/test_timekeeping_local.py::test_source_does_not_serialize_new_wall_clock_in_utc`

## Static baseline A/B

- Ruff repo-wide: main **32**, production **32**, exact diagnostic fingerprint match, main-only **0**.
- Pyright repo-wide: main **58 errors / 0 warnings**, production **58 / 0**, 389 files each, exact diagnostic fingerprint match, main-only **0**.

These findings are gen161 baseline debt and are deliberately not repaired opportunistically during reconciliation closure.

## Positive qualification gates

- WebUI: **35 files / 263 tests PASS**, production build PASS.
- Code-nav / Skills / real-Pyright focused suite: **66/66 PASS**.
- Reconciliation runtime-delta focused suite: **58/58 PASS**.
- Runtime-delta Python Ruff: PASS.
- Restart shell syntax: PASS.
- `compileall`, `git diff --check`: PASS.
- Root knowledge/runtime path authority: PASS.
- Active config/manifests/launchd/process authority: **0** deleted-worktree references.
- Real root-main web-gpt smoke: exact `PHASE16_ROOT_MAIN_OK`, 0 tool calls, `finish_reason=stop`.
- Production `service_control verify`: **PASS / gen161**.

Browser profile internals contain nine historical strings naming the old middleware profile location inside LevelDB/Chrome log files. They are inert historical log data: active launchd, manifests, process command lines, and config all use the production-owned `data/runtime/chatgpt-web-chrome-profile`.

## Main vs production deployability ledger

Production `{prod}` is the merge-base and ancestor of current main. Main is **20 commits / 102 paths** ahead. The delta is dominated by **58 candidate Method files** and **31 docs/governance files**. Only four runtime code/script paths differ:

- `scripts/restart_feishu.sh`
- `scripts/restart_system.sh`
- `src/llm_loop/cache_guard/guard.py`
- `src/llm_loop/llm/chatgpt_page.py`

Those four paths were separately qualified during Phases 3 and 9 and again by Phase 16 focused tests. **Production is intentionally still gen161 and is not running main.** Phase 16 performs no publish, deployment, or service restart. A future deployment is a separate decision.

## Decision

Mainline reconciliation is qualified for formal closure. All reconciliation-specific topology, preservation, root authority, provider continuity, and no-regression gates pass. Remaining local-branch governance is explicitly separated into Phase 17.
