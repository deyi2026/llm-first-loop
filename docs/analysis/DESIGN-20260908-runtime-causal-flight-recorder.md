# Runtime Causal Flight Recorder — implementation contract

Status: phased local implementation.  This is observability, not a semantic controller.

## Non-negotiable invariants

1. System prompt, provider messages, tool schemas and provider parameters are byte/field identical
   with and without causal observability.
2. No hidden LLM call, no automatic retry, no prompt injection, no semantic root-cause judgment.
3. Normal primary requests add no new EventStore append; Causal Core piggybacks `request.meta`.
4. No per-request git/source-tree scan. Runtime/source/config identity is snapshotted at startup.
5. No stage repeatedly serializes/hashes the full prompt. Existing stage counters/statistics are reused;
   the final messages+tools structure is serialized once by existing `request.meta`, then hashed once.
6. Rule/experience/memory exposure may be recorded as exposure only, never as semantic causation.
7. Diagnostic comparison is deferred/read-only. Reference attempts are mechanical (previous provider
   success / same provider+model / explicit attempt), never program-scored "healthy" answers.

## Phases

- P0-A Causal Core: runtime snapshot, attempt identity, compact request-build influence facts.
- P0-B Read-only diagnoser: `architecture_status(dimensions=["causality"])` + offline CLI; no new tool.
- P0-C qualification: historical incident oracles (recent-dialogue loss, 4096 reasoning-only stop,
  cache/prefix drift, 1210 deep-wire case, restart identity, normal user-turn non-false-positive).
- P1 payload trace convergence: keep deep wire fingerprinting explicit/on-demand; retire the current
  default-on standalone `payload_trace.jsonl` after coverage is proven.

## Performance gate

Always-on primary path target: 100K p95 <0.2ms and 1MB p95 <0.5ms incremental CPU for the only new
O(payload) operation (SHA256 of serialization already produced by request.meta), zero new EventStore
writes, zero background scanners/threads/network calls.

## P0-B implemented read-only surface

`architecture_status(dimensions=["causality"])` performs the diagnosis only on explicit request;
ordinary status dimensions return without reading EventStore causality history.  The existing tool
schema is unchanged: causality is advertised in the status result's available-dimensions hint rather
than by adding a tool or changing the schema contract.  `scripts/diagnose_runtime_causality.py`
provides the same read-only report offline.

The report is deliberately bounded to `observed_facts`, `earliest_mechanical_divergence`,
`constraint_hits`, `unchanged_facts`, and `unknown`.  A divergence is a mechanical difference, never a
semantic root-cause verdict.  Normal user-content growth changes the final payload fingerprint but is
not by itself classified as a program-mechanism divergence.

Fallback and exact ERR1210 retries emit `request.attempt` only when such an exceptional provider call
actually occurs.  Normal primary requests still use the single existing `request.meta` write.
