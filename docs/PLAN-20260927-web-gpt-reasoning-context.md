# WebGPT reasoning/context qualification plan

## Objective

Advance the qualified gen130 ChatGPT Web provider without changing LFL's authority model:

1. Make browser reasoning strength explicit, configurable, and mechanically verified before every provider decision.
2. Replace the inherited 131,072-token WebGPT registry context with an explicit configurable budget; qualify 262,144 first.
3. Add cache-prefix stability facts without treating browser/provider cache as memory or correctness authority.

## Frozen invariants

- LFL LoopEngine remains the sole context/tool/agent authority.
- Every WebGPT provider decision starts from the configured Project root with a fresh outer ChatGPT thread.
- Browser ownership remains exact `target_id` + Project identity; no URL heuristic rebinding.
- No `bring_to_front` or equivalent foreground activation.
- No private ChatGPT API/cookie/token inspection. Only visible/accessibility page semantics are used.
- Configured context tokens are an LFL operational projection budget, not a claim about ChatGPT Web's physical maximum.
- Cache telemetry is diagnostic only; a cache hit cannot restore context that LFL did not send.

## Qualified live UI contract (2026-09-27)

On the exact leased production target, the visible button `aria-label="选择 ChatGPT 模型"` exposes model/strength state. Opening it and activating the visible `menuitem` named `强度` exposes a status of the form `<level>，第 N 项，共 5 项。`; left/right arrows adjust it. Observed levels are:

1. `即时`
2. `中`
3. `高`
4. `极高`
5. `Pro`

The probe was performed through CDP without foreground activation and restored the page to `5.6 高`.

## Implementation

### A. Reasoning strength

- Add `chatgpt_web_reasoning_effort` / `CHATGPT_WEB_REASONING_EFFORT` with normalized values `instant|medium|high|xhigh|pro`; default `high`.
- Add `ChatGPTPageAdapter.observe_reasoning_effort()` and `ensure_reasoning_effort()` using only the qualified accessible controls.
- `_SurfaceOwnedTransport.exchange()` ensures the configured effort after Project reset and before sending the LFL snapshot.
- Fail closed if the control cannot be observed or the requested level cannot be mechanically confirmed.

### B. Context budget

- Add `chatgpt_web_context_tokens` / `CHATGPT_WEB_CONTEXT_TOKENS`; default 262,144 for this provider only.
- Register `chatgpt-web/web-gpt` with that explicit `ModelSpec.context`.
- Preserve the existing shared routing math (safety margin, output reserve, tool-schema reserve); do not add a second context policy.

### C. Cache-prefix stability

- Keep request serialization canonical and separate stable protocol instructions from request-specific payload.
- Compute non-authoritative fingerprints/character counts for the stable wrapper and current JSON payload so drift is observable in tests/runtime diagnostics without exposing or depending on provider cache internals.
- Do not alter fresh-thread semantics solely for cache reuse.

## Qualification gates

- Unit tests for all five UI strength levels, no foreground activation, idempotent no-op when already correct, bounded navigation to target level, and fail-closed unknown state.
- Config/resolver/provider-registration tests for reasoning effort and 262,144 context.
- Existing ChatGPT Surface/WebGPT suites remain green.
- Real-page no-message probe confirms `high` can be observed/set in the minimized dedicated browser.
- Production canary after Web-only deployment checks runtime model catalog/context metadata, exact reasoning state before/after a provider call, no Surface errors, and unchanged Feishu/Learning PID/head.
