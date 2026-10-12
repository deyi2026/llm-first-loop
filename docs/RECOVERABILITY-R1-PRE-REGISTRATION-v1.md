# Evidence Recoverability R1 Historical Replay — Pre-Registration v1

Date: 2026-08-26
Status: **FROZEN BEFORE REPLAY**
Provider/model calls: **forbidden**
Input manifest: `tests/fixtures/evidence_r1_historical_v1.json`

## Objective

R1 answers the historical causal question left open after Full R0: among exact source-action repeats already present in production-like event logs, how many occurred after the program had hidden the prior concrete observation, and would the new Evidence contract have made that exact observation recoverable before the repeat action?

R1 does not ask a model what it would have done and does not claim every repeat is wrong. It replays persisted events deterministically.

## Frozen cohort

The cohort is every `data/event_logs/*.jsonl` whose maximum event timestamp is at or before the Phase5 seal checkpoint `2026-08-26T08:45:17.163758+00:00`. The manifest freezes every path and SHA-256.

Frozen sanity totals, inherited from the prior root-cause audit and required to match before scoring:

- sessions: 120
- tool calls: 5,419
- same-run exact tool+args repeat instances: 226

A `run.end` resets the primary repeat-key state. This makes the primary causal cohort insensitive to a later user turn explicitly asking to run something again.

## Exact-repeat and hidden-observation rules

Exact key = `tool_name + canonical JSON arguments` with sorted keys.

A prior observation counts as **programmatically hidden** only when its concrete `role=tool` message index has appeared as `context.compressed.payload.msg_seq` before the later repeated call. Merely having some compression event between two calls is not enough.

Replay is temporal. The previous tool result is captured into an isolated Evidence store only when that historical result event is reached. At the later repeated call, R1 attempts owner-scoped `EvidenceHydration` of the previously captured EvidenceRef. The source tool is never executed.

## Frozen cause classifier

`program_amnesia_avoidable` requires all of:

1. same-run exact repeat;
2. previous successful concrete tool result existed before the repeated declaration;
3. that exact prior result was programmatically hidden before the repeat;
4. previous EvidenceRef hydrates exactly at repeat time;
5. tool is `read_file`; and
6. the historical repeated read later returned byte-for-byte the same observation.

This is deliberately conservative. It does not label commands, web calls, job polling or runtime status as avoidable because old snapshots do not prove currentness.

Other buckets are `freshness_change_observed`, `freshness_or_polling`, `model_repeat_while_visible`, `ambiguous_hidden_repeat`, and `no_temporal_prior_observation` as frozen in the manifest.

## Synthetic/stress stratum

All-history totals are never filtered. A secondary naturalistic view reports sessions separately when the first user message begins with one of the frozen synthetic/stress prefixes in the manifest (explicit long-session pressure tests, SWE-bench, operator self-tests, etc.). No result-path-based or score-based exclusion is permitted.

## Blocking R1 gates

1. Frozen input hashes and contract hashes match.
2. Sanity counts reproduce 120 sessions / 5,419 tool calls / 226 same-run exact repeats.
3. Every repeat with a temporally available prior successful observation has a stable owner-scoped EvidenceRef.
4. Every prior observation marked programmatically hidden hydrates exactly before the repeat; `lost_evidence_ref_count == 0`.
5. Replay performs zero provider/model calls and zero source tool executions.
6. Cause counts are emitted for all-history and the frozen synthetic/naturalistic strata without manual override.
7. Capture/hydration latency distributions are recorded. R1 uses them to freeze a later rollout SLO; the first historical replay does not retroactively fail on an invented latency threshold.

## Interpretation boundary

`program_amnesia_avoidable` means the old bytes were already acquired, the program removed their concrete message from the active projection, and the new contract could recover those same bytes without rerunning the source. It does **not** prove the old model would certainly have chosen hydration instead of another action; that effectiveness question remains R2 fresh-provider confirmation.
