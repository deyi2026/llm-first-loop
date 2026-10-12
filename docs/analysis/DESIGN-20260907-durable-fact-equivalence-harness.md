# Durable Fact Equivalence Harness

Date: 2026-09-07

## Purpose

This is a deterministic, test-only qualification layer for comparing two LFL execution arms after Continuity Kernel v1 closure. Its core rule is:

> **Behavioral durable-fact delta = 0; compute-only telemetry delta is allowed.**

It is deliberately not an Agent evaluator. It does not score final-answer semantics, reasoning quality, evidence relevance, tool strategy, or whether the model chose the “best” action.

## Preconditions

1. **Provider-visible payload invariant** — the exact payload sent to the provider must match across arms. Messages, tools, system prompt and reasoning contract are byte-equivalent after canonical JSON serialization. An ON-only `cache_tag`, `prefix_hint`, goal hint or system injection invalidates the comparison.
2. **Independent execution arms** — opaque run/session/execution/job/artifact/evidence IDs may differ and are structurally normalized, while their relation graph and all non-opaque facts must match.
3. **Compute telemetry allowlist is closed** — only the fixed fields in `request.usage` declared by `scripts/qualify_durable_fact_equivalence.py` are ignored for behavioral comparison. The same field names appearing in another event type are not ignored.
4. **Event order is significant** — absolute event UUID/time/seq are volatile and removed, but relative event ordering is preserved.

## Current compute-only allowlist

Inside `request.usage` only:

- cache hit/miss/read/uncached counts and hit rate;
- runtime PID;
- reserved mechanical backend measurements for actual reused-prefix tokens, new-prefill tokens, admission, eviction, resident capacity and latency.

The harness intentionally keeps model, input/output token counts, stable-prefix fingerprint/change reason, cache-prefix epoch, compaction epoch, context window and output reserve as comparison facts. If these differ, the arm is not treated as “compute-only equivalent”.

## Durable facts that remain gating

All non-allowlisted event content remains exact after opaque-ID normalization, including:

- message and run lifecycle facts;
- tool declaration/start/finish/receipt and result/effect hashes;
- Evidence/artifact provenance facts and immutable hashes;
- SubAgent topology/delivery/result/settlement facts;
- external execution ownership/terminal/cancel facts;
- interruption/recovery facts;
- history/compaction facts;
- provider/model/prefix structural facts.

A semantic-looking field such as `goal`, `completion`, `retry`, `evidence importance`, `working_state`, `next_action`, `tool relevance` or `cache_tag` is never ignored merely because it appears in a qualification record.

## Snapshot format

Each arm is a JSON object:

```json
{
  "provider_payload": {"messages": [], "tools": []},
  "events": [
    {"session_id": "...", "seq": 1, "type": "session.created", "ts": "...", "payload": {}}
  ]
}
```

Run:

```bash
python scripts/qualify_durable_fact_equivalence.py off.json on.json
```

Success emits only hashes and mechanical result flags, for example:

```json
{"qualified": true, "provider_payload_invariant": true, "behavioral_delta": 0, "compute_delta": true}
```

Raw provider payloads are not printed by the CLI.

## What this does not prove

A deterministic fixture PASS does not by itself prove a real-model StateBraid ON/OFF qualification. Real-runtime claims still require the relevant reference backend and must isolate cold/warm state. In particular, a future performance A/B should distinguish `cold-OFF`, `cold-ON`, `warm-OFF`, `warm-ON` with independent namespace/trust-domain/request identity/cache state and a defined warm-up procedure.

StateBraid/research remain read-only from the LFL workline. This harness is prepared on the LFL side so future integration work can compare durable facts without giving compute telemetry semantic authority.

## Verification

A fresh detached candidate based on `774e7d3` plus only this harness, its tests and this design passed: focused CK-FINAL + equivalence tests 14/14; Ruff PASS; `py_compile` PASS; repository Pyright `0 errors / 0 warnings / 0 informations`; `git diff --check` PASS; full `pytest tests -q -m 'not real_llm'` exit 0 in about 167.9s. The universal prompt remained 192 chars with SHA256 `ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e`, and no `src/` runtime file changed.
