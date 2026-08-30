# R8.6 Tool Eligibility + Recovery Audit

Date: 2026-08-30

Status: **AUDIT PASS / IMPLEMENTATION NOT STARTED**

Scope: this phase audits which tools deserve prompt visibility and how failed tools should recover. It does **not** change production tool registration, tool-schema projection, MCP configuration, or model behavior.

Authoritative machine-readable files:

- `docs/injection-governance/tool-eligibility/matrix.json`
- `docs/injection-governance/tool-eligibility/recovery-policy.json`
- `docs/injection-governance/tool-eligibility/web-fetch-case.md`

## 1. Owner rule

Prompt Eligibility already established:

> Resolved is retrievable, not injectable.

Tool Eligibility extends the same principle:

> **Available is discoverable, not necessarily injectable.**

A capability existing in `ToolRegistry` is not sufficient reason for its schema to appear in every provider request.

Default visibility should be reserved for capabilities that are both broadly useful and currently healthy. Everything else should be discovered when the current task, runtime state, or failure path requires it.

## 2. Current evidence baseline

Using the current runtime configuration with a detached **clean committed source** baseline, the registry contains **61 tools**.

Current serialized schema size:

| Surface | Tools | Serialized chars |
|---|---:|---:|
| Current cloud lazy surface | 61 | 22,692 |
| Current full schemas | 61 | 39,295 |
| Proposed universal CORE | 9 | 3,418 |

The proposed universal CORE therefore removes **84.9%** of the clean-source cloud lazy-schema characters before task-specific tools are added.

Reproducibility note: the first exploratory measurement was run against the existing dirty workspace and produced slightly different schema byte counts because an unrelated pre-existing `schedule` edit changed that tool's description/schema. Those dirty-overlay bytes are **not** used as the canonical audit baseline. All authoritative schema-size numbers in this report and `matrix.json` are from detached clean source and measure the compact-JSON serialized **whole tools array**. Historical call/success counts are different: they are a point-in-time scan of append-only event logs frozen at `2026-08-30T23:37:03+08:00`; later runs may increase those counts and are not expected to reproduce them byte-for-byte.

The nine universal CORE tools are:

```text
read_file
edit_file
execute_command
search_files
web_search
search_records
get_tool_schema
skill_list
skill_load
```

This is not a proposal to delete the other tools. It is a proposal to make them task/state-discoverable instead of always prompt-visible.

Current audit classification of the 61 live registry tools:

```text
CORE          9
DISCOVERABLE 49
DEGRADED      1
QUARANTINED   2
```

`web_fetch` is the single DEGRADED tool because it is healthy for ordinary pages but has strongly context-dependent failure modes. `playwright_exec` and `playwright_test` are QUARANTINED in the current runtime because `.venv` lacks the `playwright` package and the host has no `chromium` executable.

## 3. Why success rate alone is not the classifier

Low success rate can mean very different things:

1. **Deterministic environment failure** — same call cannot succeed until runtime changes. This should quarantine the capability.
2. **State/precondition misuse** — the tool is healthy, but only valid after another state exists. This should make it discoverable under that precondition.
3. **Context/domain mismatch** — the tool works in some contexts and fails predictably in others. This should use context-aware routing/recovery.
4. **Normal business failure** — e.g. stale schedule id or missing record. The tool remains healthy; the caller needs a valid identifier.
5. **Transient transport failure** — one bounded retry can be legitimate.

Examples from the frozen usage snapshot (`2026-08-30T23:37:03+08:00`):

- `mcp_dsh_write`: historical 0/3, all sandbox read-only failures -> deterministic, retire/quarantine.
- `evolution_complete`: low aggregate success, but failures are mostly invalid arguments/state preconditions -> keep discoverable, expose only when an executing evolution exists.
- `schedule_cancel`: failures are stale/not-found schedule ids -> require a valid `sid`; do not quarantine the tool.
- `web_fetch`: aggregate success is low because domain mix matters; static docs/GitHub succeed while anti-bot sites often fail -> DEGRADED + context-aware recovery.

## 4. MCP audit

Current `.env` resolves to one MCP server: `dsh`.

Live probe:

```text
initialize     PASS
tools/list     PASS
tools returned 0
registry MCP tools 0
```

Therefore the current `dsh` MCP connection is a **no-capability configuration**. It should not occupy an active capability surface. Recommended state is QUARANTINED/DISABLED until all re-entry gates pass:

```text
tools/list > 0
schema valid
health probe PASS
tool allowlist/dedupe review PASS
```

Historical `mcp_dsh_write` is not in the current registry. It remains only historical evidence and should be treated as `RETIRED_HISTORY_ONLY`.

## 5. Skill-aware recovery must happen before or at failure, not after blind retry

Current runtime has `web-fetch-fast` as an external Skill. Its documented purpose explicitly covers anti-bot/article sites and tells the model not to blindly retry `web_fetch`.

However the current automatic Skill matching path runs **after tool execution** via `_inject_experience_tips()` -> `_match_skills()`. This means it can help a later attempt but cannot prevent the first predictable failure.

The recovery design should instead support two entry points:

```text
preflight context match
    -> route or recommend the preferred skill/tool before a known-bad call

tool failure classification
    -> emit one short, exact recovery record for the matched failure class
```

The recovery record should be structured conceptually as:

```text
failure_class
retry_same_tool
preferred_tool
preferred_skill
precondition
reason
```

It should **not** become another large always-on prompt block.

## 6. Recovery policy principles

The proposed `recovery-policy.json` freezes these rules:

- same-tool retry only for transient failures or corrected parameters;
- deterministic failures route to a different capability or stop;
- state-precondition failures tell the model which state/schema to inspect before another call;
- stale identifiers are not retried unchanged;
- known domain failures may prefer a Skill before the generic tool;
- security-policy blocks stop and report the boundary; ordinary recovery must not suggest weakening SSRF/private-target protections;
- recommended Skills/replacements must themselves pass runtime health checks.

The last rule matters now: `web-fetch-fast` documents Chromium as its final fallback, but the current runtime has neither `playwright` nor `chromium`. A static Skill must therefore not be treated as proof that every fallback it describes is currently executable.

## 7. Recommended visibility model

### CORE

Always eligible, small universal set. These are generic building blocks and discovery primitives.

### DISCOVERABLE

Healthy capability with a meaningful task/state precondition. It should be absent from the default prompt and added only when eligibility is proven.

Examples:

- `job_output` only when an active background job exists;
- `schedule_cancel` only with a valid schedule id;
- `evolution_complete` only with an executing evolution;
- Goal/Task tools only for an active long-running workflow;
- Feishu tools only on explicit outbound intent and configured capability;
- model-switch tools only when model selection is relevant.

### DEGRADED

Useful but context-sensitive. The caller should see a health/context policy and an exact recovery path.

Current example: `web_fetch`.

### QUARANTINED

Current runtime cannot satisfy deterministic prerequisites. The tool should not be prompt-visible until a health probe re-admits it.

Current live examples: `playwright_exec`, `playwright_test`.

Non-registry example: MCP `dsh` server currently returns zero tools.

## 8. Implementation gates before any behavior change

This audit does not authorize immediate dynamic projection. Implementation should satisfy all of these first:

1. **Deterministic projection**: same task/state produces byte-stable tool schemas.
2. **Universal escape hatch**: `get_tool_schema` / discovery remains available so hidden capabilities are recoverable.
3. **No capability loss**: a discoverable tool must be discoverable before it is removed from the default surface.
4. **Runtime health**: QUARANTINED/DEGRADED decisions use current dependency/server health, not only historical statistics.
5. **Failure classification**: recovery uses typed failure classes, not substring-only blind retry loops.
6. **Skill health parity**: a recommended Skill must not advertise a fallback that is impossible in the current runtime without being marked unavailable.
7. **Telemetry**: record selected surface, hidden-tool discovery, recovery route, retry count, and final success without injecting telemetry into conversation history.
8. **R0/R8.5 invariants**: tool projection must not resurrect resolved episodes or change user-truth ordering.

## 9. Proposed acceptance metrics for implementation

```text
default cloud tool-schema chars <= 5,000
universal default tools <= 12
hidden-but-needed discovery success = 100% in fixtures
quarantined tool direct calls = 0
known deterministic same-tool retries = 0
failure -> recommended route accuracy = 100% in policy fixtures
security block -> unsafe bypass suggestion = 0
tool protocol violations = 0
R0 frozen diff = 0
```

Behavior canary remains **NOT STARTED**. Tool Eligibility implementation should be validated before combining it with model-profile behavior changes.
