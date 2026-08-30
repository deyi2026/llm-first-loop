# R8.7 Dynamic Tool Eligibility + Runtime Health + Typed Recovery

Date: 2026-08-30

Status: **PASS**

Base audit: `e1e7a12` (R8.6)

Owner principles:

> **Available is discoverable, not necessarily injectable.**
>
> **A failed tool should expose one typed next path, not invite blind retry.**

## 1. Scope actually implemented

R8.7 changes the prompt-facing tool surface, but does not delete healthy capabilities from `ToolRegistry`.

Implemented:

- central `Tool Eligibility` projection for local and cloud providers;
- stable nine-tool CORE prefix;
- current user-task lexical eligibility for secondary tools;
- active assistant/tool protocol preservation;
- recovery-next preservation from structured tool-result metadata;
- `off / shadow / enforce` rollback modes (`enforce` is the approved default);
- `get_tool_schema` on-demand catalog/search without adding a new tool or schema parameter;
- current-runtime quarantine for unavailable Playwright tools;
- MCP no-capability (`tools/list=0`) connection retirement;
- typed recovery for `web_fetch`, including preflight for known Toutiao anti-bot paths;
- single-source recovery guidance: a typed match replaces generic failure advice and stale experience advice for that result.

Not implemented in R8.7:

- the remaining non-`web_fetch` R8.6 recovery rules (`evolution_complete`, `schedule_cancel`, `job_kill`, etc.) remain proposed;
- installing Playwright/Chromium;
- enabling an MCP server that exposes no tools;
- Prompt Eligibility blockers unrelated to tool schemas;
- model-profile behavior canary or R9.

## 2. Central projection

Authoritative implementation:

- `src/llm_loop/tools/eligibility.py`
- `src/llm_loop/core/loop/tool_eligibility.py`
- `src/llm_loop/core/loop/engine.py`

The provider-visible set is:

```text
stable CORE
+ tools proven relevant by current user text
+ tools required by the active assistant(tool_calls) -> tool protocol chain
+ tools named by the latest structured recovery route
- runtime-quarantined tools
```

CORE order is fixed:

```text
edit_file
execute_command
get_tool_schema
read_file
search_files
search_records
skill_list
skill_load
web_search
```

Hidden healthy tools remain registered and discoverable. `get_tool_schema(tool_name="*")` lists the catalog; `get_tool_schema(tool_name="?keyword")` searches it; exact name returns the full schema. This reuses the existing single `tool_name` parameter, so R8.7 does not create another always-visible discovery tool or expand its parameter schema.

### Rollback modes

```text
TOOL_ELIGIBILITY_MODE=enforce  -> CORE + current-required projection is applied
TOOL_ELIGIBILITY_MODE=shadow   -> candidate is computed/audited; legacy provider surface remains
TOOL_ELIGIBILITY_MODE=off      -> legacy provider surface remains
```

Invalid configuration fails bounded to `enforce`; it does not silently reopen the full 61-tool prompt surface.

`PREFIX_LAYERED=1` remains available in shadow/off. In enforce, Tool Eligibility starts from canonical registry schemas instead of old prefix-layer index schemas, preventing CORE tools from losing parameter names/types.

## 3. Clean-source schema evidence

Pre-commit detached clean-source measurement was performed from base `e1e7a12` with only the intended R8.7 source files overlaid. This excludes unrelated dirty `schedule/task_store` work.

```text
registry tools                         61
all lazy compact-JSON array       22,699 chars
all full compact-JSON array       39,303 chars

simple task CORE                       9 tools
simple task raw lazy                3,425 chars
simple task provider tools wrapper  3,714 chars
reduction vs all lazy                 84.9%

ordinary URL task                     10 tools (CORE + web_fetch)
raw / provider wrapper             3,863 / 4,183 chars

schedule task                         10 tools (CORE + schedule)
raw / provider wrapper             3,866 / 4,186 chars

browser task                           9 tools
playwright_exec/test                   2 quarantined candidates
```

Detached clean checkout at implementation commit `76c2d0f` reproduced these values exactly; a docs-only amend is followed by one final fixed-point recheck.

## 4. Runtime health

### Playwright

When the Python `playwright` dependency is absent, `playwright_exec` and `playwright_test` are not projected even if the task text asks for Playwright. A stale direct call is independently refused at the registry execution boundary and receives typed replacement metadata.

This is intentionally a runtime gate, not a historical-success-rate gate.

### MCP

Current `dsh` MCP can initialize and answer `tools/list`, but returns zero tools. R8.7 now treats that as no capability:

```text
connect
-> tools/list == []
-> close stdio connection
-> register 0 tools
```

The same rule applies on MCP refresh. Re-entry still requires non-empty valid tools plus the R8.6 health/allowlist/dedupe review.

## 5. `web_fetch` typed recovery exemplar

Authoritative implementation:

- `src/llm_loop/tools/recovery.py`
- `src/llm_loop/tools/registry.py`
- `src/llm_loop/tools/builtin/web_fetch.py`

### Preflight

A Toutiao hostname is recognized before the generic fetcher performs any network request:

```text
failure_class=known_domain_anti_bot
retry_same_tool=no
preferred_skill=web-fetch-fast
next=skill_load:web-fetch-fast
```

The registry fixture proves the wrapped `web_fetch` implementation is called **zero times** in this branch.

### Post-failure classes

Applied classes:

- `403/418` -> `anti_bot_or_access_reject`, no same-tool retry, prefer `web-fetch-fast` / `web_search`;
- `404` -> `url_not_found`, no retry, find canonical URL with `web_search`;
- `429` -> `rate_limited`, retry only later, prefer alternate source now;
- JS shell after generic fallback -> `javascript_shell_or_anti_bot`, no retry, load `web-fetch-fast`;
- timeout / 5xx -> `transient_transport_or_server`, at most one bounded retry;
- security/private-target block -> `security_policy_block`, stop; no routine suggestion to weaken SSRF protection.

The tool's own failure body now reports only the fetch facts. When a typed policy matches, `tool_result_to_message()` emits that typed policy instead of appending the old generic retry advice or a potentially conflicting historical experience tip.

Structured recovery is also copied to `Message.metadata.tool_recovery`; the next projection may keep the recommended hidden tool visible without making the recovery prose a permanent prompt injection.

## 6. Verification so far

Focused R8.7 + MCP + schema suite: **34/34 PASS** in detached clean checkout.

Web-focused suite after making typed recovery the single advice source: **66/66 PASS**.

R1-R8.5 / history / tool protocol / fallback / 1210 / Evidence / factory / MCP / web adjacent suite: **572/572 PASS** in detached clean checkout.

Touched production + R8.7 test pyright: **0 errors / 0 warnings**.

Two repository-wide pre-existing test debts were explicitly reproduced against `e1e7a12` and are not R8.7 regressions:

- `tests/unit/test_config.py::test_load_settings_full` still expects `DATA_DIR="./data"`, while the base implementation already uses an absolute `_DEFAULT_DATA_DIR`;
- `tests/unit/test_loop_mixin_split.py::test_complexity_reduction` caps `engine.py` at 1172 lines while base `e1e7a12` is already 1276 lines. R8.7 moved its projection logic into `_ToolEligibilityMixin`; current engine delta versus base is only the integration seam.

Final gates: pyright 0/0; py_compile PASS; R0-1~R0-4 PASS with frozen directory hash `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`; exact 22-file staging boundary + security scan PASS; detached clean checkout status before/after clean. The only clean-checkout setup required was read-only mounting of Git-ignored `.codeartsdoer/specs/ev_recov` for its existing Evidence contract test and `data/event_logs` for canonical R0 replay; both were removed before the clean-status assertion.

## 7. Remaining boundaries

R8.7 closes the tool-schema branch of Prompt Eligibility, but it does not clear the remaining Prompt Eligibility blockers (legacy resolved migration proof, model-switch replay, Evidence Manifest bypass, legacy/unresolved Cognitive memory, local behavior hint, unknown producer fail-open, round-exhaustion consumed mismatch).

Therefore:

```text
R8.7 tool eligibility implementation = PASS
R8 model-profile behavior canary      = NOT STARTED
R9                                      = NOT STARTED
```

## 8. Live activation boundary

R8.7 is code-level PASS but the already-running mirror services were **not restarted in this phase**. `scripts/restart_mirror.sh` intentionally starts from the current mirror working tree (`PYTHONPATH=<mirror>/src`). At closeout the worktree still contains unrelated pre-existing dirty Cognitive/scheduler/web source changes that are outside the R8.7 allowlist. Restarting now would load those changes together with R8.7 and destroy causal isolation.

No `refresh_config` or ad-hoc launch path was used. The live process should be reloaded only after those unrelated source changes are independently committed/removed or otherwise made safe for a controlled restart. This is a deployment-activation boundary, not an R8.7 code/test failure.
