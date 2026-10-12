# Browser v0.6-A1.1 Mechanically Typed Wait — Read-Only FCR Smoke

This is a **read-only first-call-readiness smoke** for the two exact failures observed in v0.6-A1. It is not a task-generalization study and it does not reopen A2 unless this frozen gate passes.

## Intervention under test

Production commit `8df9067a` changes only program assistance:

- live CDP capture supplies the already-canonical `document_ready_state` fact through one fixed internal `document.readyState` probe; generic/model-supplied `Runtime.evaluate` remains denied;
- the model-facing generic `browser_wait_scope/object` pair is replaced by mechanically typed waits whose semantic values have one JSON type on the lazy provider surface:
  - `browser_wait_scope_url`
  - `browser_wait_scope_ready`
  - `browser_wait_scope_count`
  - `browser_wait_object_state`
  - `browser_wait_object_text`
- fixed Predicate relations/types are compiled by the program; the model still selects the observed ref, semantic condition, whether to wait, and whether the task is complete;
- there is no string-to-boolean coercion, target selection, automatic snapshot/latest/retry/replay/rebind, mutation, or program-side task completion.

## Surface

Exactly seven tools are exposed:

- `browser_perceive`
- `browser_wait_scope_url`
- `browser_wait_scope_ready`
- `browser_wait_scope_count`
- `browser_wait_object_state`
- `browser_wait_object_text`
- `get_tool_schema`

The old generic `browser_wait_scope` / `browser_wait_object` tools and all Browser mutation tools are absent.

The committed preflight must prove these machine facts before any model request:

- `browser_perceive.action = snapshot|hydrate|diff`, with no predicate field;
- `scope_ready.state = loading|interactive|complete` and has no model-owned operator/value;
- `object_state.value` is JSON `boolean` and its property enum contains only live-observable state properties;
- `scope_count.count` is `integer >= 0`;
- every wait has `interval_ms=1..5000`; exact required fields match the frozen contract;
- unsupported live `visible` is not advertised.

## Frozen tasks

The user prompts and fixtures are byte-for-byte the same semantic tasks as v0.6-A1; only the tool interface changes.

1. `scope_ready`: snapshot the already-open page, then wait on the observed document scope until `document_ready_state == complete`. Expected first typed wait: `browser_wait_scope_ready`.
2. `object_enabled`: snapshot the already-open page, select the exact `Ready control` object GroundingRef, then wait until that same object is enabled. Expected first typed wait: `browser_wait_object_state`.

The second fixture starts disabled and enables itself after a fixed local timer. No model mutation is needed or allowed.

## Runtime freeze

- same local Ornith / 8901 single server;
- Thinking ON, reasoning effort medium;
- temperature 0 / top_p 1 / top_k 0 / min_p 0;
- input 184K / output 16K;
- max iterations 8;
- worker timeout 180s;
- lazy tool schema ON;
- fresh session, DATA_DIR and Chrome profile each row;
- exact isolated Chrome target; mock/basic keychain flags;
- strict serial execution; no fallback;
- no row replay.

## Pre-registered gate

A1.1 PASS only when both rows meet every condition:

- mechanically complete; exact frozen provider surface; no fallback / SecurityAgent;
- expected task-specific typed wait is the first typed wait tool used;
- a successful `browser_perceive(snapshot)` occurs before the first typed wait;
- first typed wait supplies exactly its tool-specific required top-level fields;
- first wait semantic value has the frozen JSON type (`str` for ready-state enum, `bool` for object state);
- durable typed-wait ToolResult reports `predicate_result.result = satisfied`;
- v0.6-A1 root cause is closed:
  - `scope_ready`: final observation reason is null/empty, not `property_unobserved`;
  - `object_enabled`: first wait value is actual JSON boolean, not a string;
- typed wait tool failures = 0;
- old generic wait calls = 0;
- legacy `browser_perceive(action=wait)` misuse = 0;
- `browser_perceive(snapshot, predicate=...)` misuse = 0;
- missing-Predicate failures = 0;
- scope-target mismatch failures = 0;
- Browser mutation calls = 0.

No post-hoc gate edits. If either row fails, v0.6-A2 remains closed. If both rows pass, A1.1 qualifies only this read-only FCR interface; A2 still requires its own frozen protocol before any main-matrix requests.
