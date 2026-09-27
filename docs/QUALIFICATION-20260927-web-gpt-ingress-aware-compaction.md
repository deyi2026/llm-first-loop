# WebGPT ingress-aware compaction qualification — 2026-09-27

## Scope

This change does not raise the qualified ChatGPT Web ingress envelope and does not
change the production WebGPT context metadata. The existing production contract remains:

- `CHATGPT_WEB_CONTEXT_TOKENS=262144`
- `CHATGPT_WEB_MAX_REQUEST_CHARS=150000`
- reasoning effort `high`
- LFL owns context, retrieval, compaction, tools, and durable state.

The only change is how the existing one-retry deterministic overflow compaction chooses
its shrink factor when the local transport has exact request-envelope size evidence.

## Problem

Before this change every first overflow sets `_overflow_shrink_factor=0.5`. That is the
correct conservative fallback when a provider only says “context too long” and exposes no
exact sizing authority. It is unnecessarily destructive for the WebGPT local ingress guard,
which knows both values in the same unit:

- complete rendered request chars;
- qualified rendered-request char limit.

A request that exceeds the 150K envelope by only 1–2% therefore used to cut the next
history budget in half, even though the browser had not received any bytes.

## Contract

`LLMRequestTooLargeError` is a structured `LLMProtocolError` carrying:

- `observed_chars`
- `limit_chars`
- provider identity

It remains an ordinary overflow for `is_overflow_error()` and the existing LoopEngine
control flow.

For this exact local preflight error only:

`factor = clamp((limit_chars / observed_chars) * 0.97, 0.10, 0.97)`

The 3% reserve absorbs JSON/history-projection variance. The 10% floor prevents a malformed
or extreme observed size from collapsing the budget to zero. No task semantics, relevance
classifier, or model judgment participates.

All other provider overflow errors retain the qualified fallback factor `0.5` exactly.

## Example

For the real gen134 mechanical canary shape:

- observed rendered chars: `152847`
- ingress limit: `150000`
- old factor: `0.5`
- new factor: about `0.9519`

Thus a slight envelope overshoot keeps roughly 95% of the current history budget for the
single deterministic rebuild instead of approximately 50%. If the rebuilt request still
exceeds the provider/envelope boundary, the existing second-overflow factual termination
remains unchanged.

## Safety invariants

- The 150K hard ingress guard remains authoritative and unchanged.
- Oversize WebGPT requests still fail before `composer.fill()`.
- The run still gets at most one deterministic overflow rebuild.
- Compaction still uses the existing lossless archive/atomic-tool-group path.
- Current ingress, tool protocol pairing, Project identity, BrowserSurface lease, and
  reasoning controls are unchanged.
- No ChatGPT-native file/search/history memory path is introduced.
- No other provider changes behavior unless it explicitly raises the new structured local
  envelope error.
