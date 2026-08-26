# Evidence Recoverability R0 Phase 3 Result v1

Date: 2026-08-26
Status: **DETERMINISTIC PASS — NOT FULL R0**
Provider calls: **0**
Production activation: **NO** (`.env` has no `EVIDENCE_MODE`; effective mode remains `off`)

## Scope

Phase 3 implements the first enforce-capable capture-before-projection path:

```text
source action
  -> complete Tool Observation (for supported projection-loss paths)
  -> durable Evidence capture
  -> bounded deterministic Projection
  -> model-visible Evidence capsule/ref
```

This phase does not claim end-to-end recoverability yet. `read_evidence`, `search_evidence`,
and `list_evidence` are Phase 4 and are not yet model-callable at this checkpoint.

## Mechanical gates passed

1. Exact ordering is `tool -> capture -> projection`.
2. Large HOT evidence is allowed to remain an excerpt; HOT never forces full bytes.
3. `full=true` cannot bypass the enforce projection budget.
4. Successful side-effect action + capture failure preserves action `success`, marks
   recoverability `failed`, does not re-execute the source action, and emits an explicit
   no-auto-rerun degradation message.
5. Capture success + projection renderer failure retains the durable EvidenceRef and falls
   back to a `ref_only` recovery handle.
6. Evidence structured metadata is retained in `Message.metadata`; the deterministic capsule
   is the only model-visible recovery handle because metadata is not sent on the LLM wire.
7. Enforce and shadow are mutually exclusive.
8. Enforce + currently enabled ToolExecutionPipeline fails closed until post-hook ordering is
   explicitly integrated; existing post hooks can replace model-visible content and therefore
   could erase a recovery capsule.
9. Off/shadow legacy behavior remains unchanged.

## Projection-loss paths covered in Phase 3

- `read_file`: enforce bypasses tool-side trim; no legacy `audit/tool_outputs` sidecar is
  generated; complete Tool Observation is captured first.
- `execute_command`: enforce bypasses command-side trim; no legacy `cmd_outputs` sidecar is
  required; action truth remains independent from Evidence capture state.
- `web_search`: enforce defers trim; concurrent child queries now propagate run contextvars.
- `web_fetch`: default `start=0` captures full extracted body before `max_chars` projection;
  explicit `start/count` remains a declared partial acquisition boundary.
- `edit_file`: full diff is captured even when legacy model view would show only the first
  80 lines; a completed edit never needs to be re-executed merely to reconstruct hidden diff.
- `dsh_task`: 30K final-answer clipping is deferred under enforce.
- `dsh_session_read`: 30K character clipping is deferred under enforce; explicit event limit
  remains acquisition scope.
- `architecture_status`: full JSON snapshot is captured before legacy 8K view clipping.
- `search_records`: all limited hits/full summaries are captured before the legacy display-six
  projection.

Explicit acquisition/query limits such as `search_files.max_results`, `web_fetch.start/count`,
subagent execution limits, and Playwright accessibility helper bounds are not falsely labeled
as complete source capture.

## Verification

- Phase 3 deterministic Evidence suites: PASS.
- Expanded projection-loss path tests (`edit_file`, `web_fetch`, DSH, introspection): PASS.
- Broad affected regression suite across Registry/pipeline, tools, factory, Archive/history,
  session, concurrency and silent-pass quality gates: PASS.
- Ruff: PASS.
- Pyright: `0 errors, 0 warnings`.
- Full repository default non-real-LLM suite:
  `pytest -q --ignore=tests/unit/test_action_guard_a3.py` -> **exit 0**.
  The ignored file is the already-stopped A3 development test with its independent broken
  `scripts.calib.action_guard` import; it is not modified to manufacture a green result.

## Runtime boundary

Current `.env`:

```text
EVIDENCE_MODE: not set -> effective `off`
TOOL_PIPELINE_ENABLED=1
```

Therefore current production behavior is unchanged. If enforce were manually enabled now,
the existing enabled tool pipeline combination is intentionally rejected until ordering is
integrated.

## What Phase 3 does NOT prove

- The model cannot yet call `read_evidence/search_evidence/list_evidence`; Phase 4 is required.
- Recovery Manifest is not yet projected across real compression/provider rebuilds; Phase 5 is
  required.
- Legacy sidecar ownership migration/GC is Phase 6.
- No MiniMax/DeepSeek effectiveness claim is made.
- Action Guard remains out of scope/P2.

## Next gate

Proceed to Phase 4 offline only:

```text
owner-injected read_evidence
+ bounded list_evidence
+ search_evidence with AND / explicit OR / quoted phrase
+ match-centered visible snippets
+ source-kind freshness checks
+ model tool registration in shadow/enforce only
```

No provider requests are required.
