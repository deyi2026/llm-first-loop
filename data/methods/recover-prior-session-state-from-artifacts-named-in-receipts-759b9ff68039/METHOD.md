---
method_id: recover-prior-session-state-from-artifacts-named-in-receipts-759b9ff68039
name: recover-prior-session-state-from-artifacts-named-in-receipts
description: Resuming a task that depends on prior-session operational facts (endpoints, payloads, auth): recalled paths are hypotheses, not evidence. The authoritative, untruncated record is the on-disk side-effect artifacts named inside prior command receipts. Probe a recalled path once at most; query the evidence store with a literal that appears verbatim in prior command text (not a paraphrase); read the command prefix in hits to get the scratch directory and artifact filenames; then inspect those artifacts directly instead of enumerating the workspace or cascading keyword-variant searches.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:180:6f6bda6efa3550b5af1f
evidence_refs: learning:learn:8f7ecc05db5a
created_at: 2026-09-18T02:17:40.607130+00:00
updated_at: 2026-09-18T02:17:40.607130+00:00
---
## Trigger
A resumed task where the needed facts (API details, request formats, credentials) were established by earlier tool calls, and the assistant currently holds only a remembered path or summary claim about where that state lives.

## Discriminator
Two receipt facts visible before any broad search pays off: (a) a failed read explicitly reports the path was already registered non-existent, proving the recalled location is stale; (b) evidence-store hits display prior command text whose prefix names concrete on-disk artifacts (scratch-dir cwd plus token/request/response files). Those named artifacts, not truncated evidence snapshots and not workspace files, hold the exact prior request and credential state.

## Short path
- Probe the recalled path at most once; if the receipt marks it registered-nonexistent, abandon that branch entirely rather than re-probing or hunting the workspace for it.
- Query the evidence store using a literal expected to appear verbatim in prior command text (product name, artifact filename); conceptual paraphrases like 'login token' tend to miss while command-literals hit.
- Read the command text in hits: extract the working directory and named artifact files (token files, request JSONs, saved responses).
- List and read those artifacts directly to recover the exact endpoint, headers, payload schema, and auth material in one hop.
- Verify recovered state cheaply with one minimal live call; if an edge gate blocks (e.g., UA-fingerprint 403), retry once with browser-like headers before considering further recovery.

## Stop conditions
- Exact prior request format and auth recovered from artifacts and cross-checked against evidence-store outputs; stop recovery and proceed to the actual new task.
- Named artifacts are absent because the environment was wiped; stop the artifact branch and fall back to evidence hydration with explicit ranges or asking the user, instead of issuing more keyword-variant searches.
- Recovered credentials are rejected as expired; re-authenticate via the captured registration flow rather than searching further.

## Verification
- Artifact contents match evidence-store outputs: the same response ids or tokens appear in both records.
- One live call using the recovered state either reproduces the prior success or returns an interpretable status (auth expiry, edge-gate), confirming the artifacts represent the real prior state.

## Counterexamples
- Prior commands ran in an ephemeral sandbox whose scratch directory is wiped between sessions: the artifacts are gone, and evidence-store hydration with range reads is the correct recovery path.
- Prior state was deliberately persisted as a report file inside the workspace: targeted filename search is then right, and mining command receipts is the detour.
- Artifacts contain short-lived credentials that have already expired: reading them recovers the request format but not usable auth; re-authentication is required.
- A fresh task with no prior session: there are no receipts to mine, so normal discovery applies.
