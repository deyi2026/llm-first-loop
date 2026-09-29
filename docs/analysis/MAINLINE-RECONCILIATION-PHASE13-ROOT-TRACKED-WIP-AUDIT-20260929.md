# Mainline Reconciliation Phase 13 — Preserved Root Tracked-WIP Audit

- Date: 2026-09-29
- Canonical main: `87d249b623972942756a457dd606659fac50623e`
- Preserved root: `wip/main-pre-reconcile-20260929@8454c8a9813947173bc5696dcb5d5309d21cdf3b`
- Result: **PASS — no tracked WIP migration remains**

## Executive result

- Frozen tracked scope: **31 files**, SHA drift **0**, index unchanged.
- **17/31** are byte-identical to current main.
- **5/31** differ only because current main is a semantic/strict superset.
- **9/31** are obsolete/conflicting and must not be replayed as-is.
- Migration candidates: **0**.
- Separate-qualification candidates inside this 31-file scope: **0**.
- Root also contains **805 untracked files**. They are explicitly out of Phase 13 scope and block physical root/WIP retirement until separately audited.

## Per-file disposition

- `.env.example` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP has zero WIP-only lines; current main adds the browser-provider configuration documentation used by production web-gpt.
- `scripts/embedding_server.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `scripts/embedding_warmup.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `scripts/restart_feishu.sh` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — Phase 3 migrated runtime.launch/legacy takeover semantics; remaining WIP-only delta is comment wording only.
- `scripts/restart_system.sh` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/cache_guard/guard.py` — **OBSOLETE_OR_CONFLICTING** — Useful live perf_block re-resolution was already migrated in Phase 3; replaying the residual WIP would replace host-local timestamp authority with datetime.now(UTC).
- `src/llm_loop/config.py` — **OBSOLETE_OR_CONFLICTING** — WIP is an older config surface: replay would remove current ChatGPT/DeepSeek browser provider settings, working-set first-view configuration, and canonical runtime-root Knowledge path hydration. Its single WIP-only env=env_values call is the superseded path-binding behavior.
- `src/llm_loop/core/subagent_delivery.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/factory.py` — **OBSOLETE_OR_CONFLICTING** — Phase 2 rejected this WIP: it would re-register convergence_decide, remove current external browser-client factories, and regress Experience/Method semantic wiring.
- `src/llm_loop/introspection/docs_search.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/introspection/search.py` — **OBSOLETE_OR_CONFLICTING** — Phase 2 rejected this WIP: only WIP-only behavior is datetime.now(UTC), conflicting with host-local time authority and dropping current Experience semantic diagnostics.
- `src/llm_loop/introspection/tools_docs.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/introspection/tools_status.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/memory/archive.py` — **OBSOLETE_OR_CONFLICTING** — Residual WIP reverts host-local timestamp authority to UTC and weakens TTL comparison from parsed datetimes to lexicographic ISO-string comparison.
- `src/llm_loop/memory/embedder.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `src/llm_loop/memory/retriever.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — Phase 2 residual analysis found zero WIP-only lines; current main is a strict semantic superset including Experience semantic cache/warm/rank support.
- `src/llm_loop/memory/store.py` — **OBSOLETE_OR_CONFLICTING** — Phase 3 rejected the WIP after production proved a semantic superset; remaining WIP-only lines revert all new timestamps/IDs/observed_at/decay time to UTC.
- `src/llm_loop/methods/learning_plane.py` — **OBSOLETE_OR_CONFLICTING** — Replaying WIP would remove current MethodDiscovery injection and method-discovery diagnostics from reflection; this capability was separately production-qualified.
- `src/llm_loop/methods/store.py` — **OBSOLETE_OR_CONFLICTING** — Only WIP-only behavior is UTC timestamp generation, conflicting with the established host-local time authority.
- `src/llm_loop/runtime/resolver.py` — **OBSOLETE_OR_CONFLICTING** — WIP parser is the older global-only runtime.toml model; replay would remove service-scoped semantic/chatgpt_web/deepseek_web authority and many current schema keys. Current parse_runtime_toml is a strict superset.
- `tests/scripts/test_restart_feishu_heartbeat.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — Current main asserts the same runtime.launch behavior and additionally locks legacy-process takeover; WIP-only delta is formatting.
- `tests/unit/test_cache_block_reclassification.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_docs_search.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_emb_prewarm_debounce.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_embedder_v2.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_learning_journal.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — Phase 2 residual analysis found zero WIP-only lines; current main adds repair requeue and Method semantic discovery/filtering coverage.
- `tests/unit/test_memory_concurrent_write.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_method_learning.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_p1_final.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_retriever_fallback.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.
- `tests/unit/test_subagent_settlement.py` — **ABSORBED_OR_SUPERSEDED_BY_MAIN** — WIP working-tree bytes are SHA256-identical to current canonical main.

## Why no migration remains

- The valuable restart/cache portions were already migrated during Phase 3.
- Phase 2 already rejected the four semantic overlap files where replay would regress production behavior.
- Current main retains the project-wide host-local timestamp authority; the residual UTC-based WIP in cache/search/archive/memory/method stores conflicts with that authority.
- Current main has service-scoped semantic/browser runtime configuration, current ChatGPT/DeepSeek browser providers, MethodDiscovery wiring, and newer Experience semantic support that the old WIP would remove.

## Validation

- Focused current-main suite across runtime resolver, cache guard, restart, learning/method, memory/retriever/archive, docs search, and SubAgent settlement: **156 passed**.
- A broader run including `test_timekeeping_local.py`: **159 passed / 1 failed**. The single scanner failure is the same known baseline previously reproduced on untouched gen161 and is outside these WIP paths.
- Production `service_control verify`: **PASS / generation 161**.

## Branch-level retirement evidence

- WIP branch-only commits vs main: **2**; main-only commits: **64**.
- `git cherry main wip/main-pre-reconcile-20260929` reports both WIP-only commits as `-` (patch-equivalent).
- Therefore the branch itself carries no unique committed patch relative to main; its only current preservation value is the uncommitted root content.

## Safe retirement plan

1. **Do not migrate any of the 31 tracked files.** Their tracked semantic review is complete.
2. **Audit the 805 untracked files separately.** Do not clean/switch/delete the root worktree before that audit.
3. After untracked preservation, re-freeze the 31 tracked paths; under an explicit destructive checkpoint, restore only those exact paths from `wip/main-pre-reconcile-20260929` HEAD. This makes the root clean without touching preserved untracked assets.
4. Reconfirm the WIP branch remains all-minus patch-equivalent to current main. Then remove the clean linked canonical-main worktree and switch the primary root worktree to `main`.
5. After root is clean on canonical main and production is reverified, delete the unattached local WIP branch. No remote ref deletion is part of this plan.

Phase 13 intentionally performs **no root-WIP mutation**.
