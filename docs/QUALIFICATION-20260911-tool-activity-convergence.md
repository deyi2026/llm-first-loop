# Tool Activity / UI Convergence Qualification — 2026-09-11

## 1. Scope and disposition

This qualification converges the historical WebUI candidate
`feature/webui-tool-activity-parity-20260909@bb419592` onto the current
`integration/convergence-20260911` baseline without merging the historical branch as a unit.

Qualified implementation tip before this document:

- base: `b5b530e910426084b86b5c39ab2e3d1f0789c77a`
- `b78e6f0` — `feat(web): stream exact tool result facts`
- `633243e` — `feat(webui): show exact live tool activity`

The old candidate was one commit and nine WebUI files, but its merge base was `d59169f` while
current integration had 49 integration-only commits. A dry-run cherry-pick produced a content
conflict in `webui/src/core/conversation.ts`; the current file also owns durable Human Turn queue
semantics that did not exist in the old candidate. Therefore the old branch is evidence/source,
not an admissible merge unit.

## 2. Findings that changed the original design

### 2.1 `tool_round` is start/progress, not success

The historical UI treated later reasoning/answer activity or a later round as evidence that a
previous tool had completed. That is not a truthful execution status. The backend execution path
already has the exact terminal `ToolResult.status`, `tool_call_id`, tool name, and duration after
execution. Convergence therefore adds an observability-only `ToolResultInfo` carried by
`StreamDelta.tool_result` and the Web SSE `tool_result` event.

No model-visible message, tool schema, tool selection rule, completion rule, or provider request is
changed by this event. The UI renders only mechanical execution facts already known by the runtime.

### 2.2 History status must not be parsed from presentation text when structured truth exists

`Message` already persists `status`, `tool_name`, and `duration_ms`, but the Web history response did
not expose them. The historical UI consequently parsed Chinese receipt text such as
`[状态: success]`, turning a rendering convention into a protocol.

The qualified path exposes those three mechanical fields through the history API. New history uses
structured status first. Receipt-text parsing remains only as a compatibility fallback for legacy
rows that genuinely lack structured status.

### 2.3 A new post-execution SSE yield needs a persistence boundary

Adding `tool_result` after execution creates a new client-disconnect point. When EventStore is
disabled, relying only on the normal loop-end `SessionStore.save()` could leave JSON recovery behind
already-executed tools if the client disconnected exactly at the first `tool_result` yield.

The qualified backend records every result in the execution batch first, then attempts one
run-owned `SessionStore.save(sess)` before exposing any `tool_result` event. Only after the complete
batch has crossed that persistence boundary are terminal UI events yielded. Where Event/WAL is
enabled, those durable facts remain in force as before.

## 3. UI semantics

The current queue-aware `webui/src/core/conversation.ts` was preserved and tool activity was
hand-merged onto it; the old file was not copied over the current Human Turn queue implementation.

The qualified UI contract is:

- `tool_round` creates/refreshes `running` for the exact `tool_call_id`.
- `answer_delta` and `reasoning_delta` never infer tool completion.
- `tool_result` settles the exact tool id to its structured terminal status and duration.
- a duplicate/replayed `tool_round` cannot regress an already terminal result to running.
- final `done.tool_calls` reconciles the final view; if an old backend supplies no status, the UI
  uses neutral `completed` / “已结束”, not success.
- stream/network interruption marks only still-running rows `interrupted`; exact terminal rows are
  preserved.
- history pairs an assistant declaration only with immediately following tool receipts by exact
  `tool_call_id`; unmatched/orphan receipts remain visible rather than being swallowed.
- ordinary UI does not display raw tool-call ids.
- paired result bodies remain user-expandable, but are collapsed at the individual row level;
  the projection is display-only and is never written back to session history.

## 4. RED → GREEN evidence

The following failures were reproduced before implementation:

1. Web history contract lacked `status/tool_name/duration_ms`.
2. SSE contained no exact `tool_result` terminal event.
3. The current queue-aware frontend had no live ToolActivity wiring after the historical branch
   diverged.
4. A structured `failure` paired with stale receipt text `[状态: success]` was rendered as success by
   the historical parser.

Regression coverage now includes:

- exact direct-SSE order: `tool_round < tool_result < done`;
- the same exact event through `BackgroundRunner` / EventBus;
- EventStore-disabled two-tool execution followed by generator close at the first `tool_result`,
  with fresh JSON reload proving both declarations and both successful receipts are present and no
  orphan remains;
- same-round multi-tool running state;
- exact failure surviving later answer text and replayed start events;
- old-backend no-status compatibility rendered as neutral completion, not success;
- structured history status overriding contradictory legacy text while preserving duration;
- legacy standalone receipt fallback, including interrupted receipts.

## 5. Qualification gates

Fresh detached committed-state verification was performed on
`633243e49d8deb2aac7688abf9f90e6925149022`:

- `scripts/ci_gate.sh`: PASS
  - all-tree Ruff: zero violations
  - env-pin declaration scan: 522 test files, zero undeclared dependencies
  - Pyright: 0 errors / 0 warnings / 0 informations
  - tier0: PASS
  - xdist full pytest: PASS
  - guard report: PASS
- WebUI: 20 test files / 120 tests PASS
- WebUI `tsc --noEmit`: PASS
- WebUI production build: PASS
- whole-tree `scripts/git_security_scan.sh --tree`: PASS, 1544 tracked files scanned
- fresh worktree remained clean after verification

Non-blocking existing warnings were limited to the repository's side-effect audit notices, React
`act(...)` test warnings, Vite chunk-size warning, and dependency deprecations; none produced a new
failure.

## 6. LLM-First / authority boundary

This change does not grant the program new semantic authority. The runtime reports only facts it
mechanically knows: declaration/start identity, exact terminal status, duration, and persisted
receipt identity. It does not decide whether a tool result is useful, whether another tool should be
called, whether the task is complete, or whether the model should continue.

`toolActivities` is a WebUI-only projection. It is not persisted into the Session, injected into the
prompt, sent to a provider, used for tool eligibility, or used for completion/retry policy.

## 7. Release state

At qualification time:

- implementation is local-only and unpushed;
- no Web/Feishu/local-model service was restarted for this candidate;
- no live model request was required for the deterministic protocol/UI qualification;
- integration admission, any live 8903 UI canary, and remote publication remain separate explicit
  actions.
