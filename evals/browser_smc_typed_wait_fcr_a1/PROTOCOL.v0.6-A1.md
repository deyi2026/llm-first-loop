# Browser v0.6-A1 Typed Wait Read-Only FCR Smoke

This is a **read-only first-call-readiness smoke**, not a task-generalization study.

## Surface

Exactly four tools are exposed:

- `browser_perceive`
- `browser_wait_scope`
- `browser_wait_object`
- `get_tool_schema`

No Browser mutation tool is exposed. Chrome is mechanically pre-opened to the loopback fixture by the qualification harness so navigation is not part of A1.

## Frozen tasks

1. `scope_ready`: snapshot the already-open page, then wait on the observed document scope until `document_ready_state == complete` using `browser_wait_scope`.
2. `object_enabled`: snapshot the already-open page, select the exact `Ready control` object GroundingRef, then wait until that same object is enabled using `browser_wait_object`.

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
- strict serial execution; no fallback.

## Pre-registered gate

A1 PASS only when both rows meet every condition:

- mechanically complete; exact frozen provider surface; no fallback / SecurityAgent;
- expected typed wait tool is the first typed wait tool used;
- a successful `browser_perceive(snapshot)` occurs before the first typed wait;
- first typed wait supplies exactly its six required top-level fields;
- durable typed-wait ToolResult reports `predicate_result.result = satisfied`;
- typed wait tool failures = 0;
- legacy `browser_perceive(action=wait)` misuse = 0;
- `browser_perceive(snapshot, predicate=...)` misuse = 0;
- Browser mutation calls = 0.

No row replay or post-hoc gate edits. If A1 FAILs, v0.6-A2 does not start.
