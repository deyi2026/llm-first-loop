---
method_id: read-anchor-declaring-consumer-config-first-56fdc99e9f98
name: read-anchor-declaring-consumer-config-first
description: Read the declaring config first: when a deploy/integration task anchors on an exact local endpoint or provider id that a consumer-side config in the working repo declares, read that config before reverse-engineering adjacent infrastructure (unrelated plugin subtrees, READMEs, unrelated listening ports, process tables). The config entry is the authoritative spec — base_url, model ids, auth env — that the producer must satisfy; widen the search only if the declaring config is missing or contradicts the anchor. Prefer the live repo copy (fresh mtime) over stale eval-search copies.
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:374:fd4ed0c2c72b5324b090
evidence_refs: learning:learn:ca3ce4fa2566
created_at: 2026-10-13T19:16:42.593656+08:00
updated_at: 2026-10-13T19:16:42.593656+08:00
---
## Trigger
Task deploys/verifies a local producer service that a consumer config in the session's working repo references by an exact anchor (port/provider id, e.g. 127.0.0.1:8904 for provider 'workbuddy'); the anchor probe fails (connection refused) or its behavior is disputed, and a prior approved plan already names the target config record and its pending edits.

## Discriminator
At friction time these facts already existed: (a) the approved plan named the exact consumer record — LFL data/providers.local.json, provider 'workbuddy', api_key_env/reasoning_control edits; (b) the anchor port 8904 was fixed; (c) the session cwd was the consumer repo itself (pwd → ~/Project/llm-first-loop-mirror), so `ls data/providers*.json` + one read yields an entry whose base_url is exactly http://127.0.0.1:8904/v1. None of the subsequently enumerated adjacent artifacts (cordis patch layers, plugin README/bin.js/lib, shim ports 50179/50180→401, 3080→404, process table) declared that anchor.

## Short path
- Probe the anchor endpoint once (curl 127.0.0.1:8904) — unknown: is the producer up? Result: refused → producer down.
- From session cwd, ls data/providers*.json and read the entry matching the plan — unknown: what exactly must the producer supply? Yields base_url, model ids, auth env, current reasoning_control.
- Start/repair the producer bound to the config's exact anchor (~/workbuddy2api converter on 8904) — unknown: does the declared contract answer?
- Re-probe the anchor and exercise declared models through it; apply config edits with a pre-change backup and re-read to confirm — unknown: is the consumer-side contract satisfied?
- Stop once the config-declared contract is verified live; widen search only if the declaring config is missing/contradictory — bounded locate, preferring the live repo copy (fresh mtime) over eval duplicates.

## Stop conditions
- Config entry and live endpoint agree on base_url/port, declared models answer through the anchor, and config edits are confirmed by re-read — provenance chain complete.
- Declaring config absent or its anchor contradicts the probe — abandon the config edge and re-anchor via a bounded search for files declaring the anchor string only.

## Verification
- Endpoint actually served equals the config base_url byte-for-byte (http://127.0.0.1:8904/v1).
- Models exercised come from the config/producer-declared set; adjacent services (401 shims on 50179/50180, 404 on 3080) were never referenced by the consumer config.
- Every config mutation has a pre-change backup (.bak-before-effort) and a post-edit re-read showing the new values in effect.

## Counterexamples
- Anchor endpoint/id is declared in no local config and appears only in a runtime error/log — then tracing the emitting component is the correct first move, not friction.
- Task explicitly targets the adjacent component itself (e.g. auditing the dsh workbuddy-connect patch layers or plugin internals) — reading those files is then on-target.
- Consumer config has a known concurrent writer and a finality claim is imminent — re-read the record at claim time (fresh-read method) instead of trusting the early read.
