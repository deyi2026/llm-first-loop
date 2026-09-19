---
method_id: derive-endpoint-from-live-pid-before-probe-64db93a2fd0f
name: derive-endpoint-from-live-pid-before-probe
description: After a restart replaces service processes, remembered endpoint literals (ports/hosts) are unverified against the new runtime. Before a canary/health probe, derive the actual bind endpoint from the live pid the status receipt already provides (e.g., lsof filtered by pid), then probe once. If a probe fails with a definitive refusal signature (connection refused, HTTP 000, exit code 7), read it as 'no listener on that port' and resolve the real listener from the live pid rather than retrying or broad-scanning. Turns a stale-literal failed probe into a deterministic pre-probe check.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1887:749ea38a37658136c2c6
evidence_refs: learning:learn:2f44a1fab9de
created_at: 2026-09-19T08:21:35.982095+00:00
updated_at: 2026-09-19T08:21:35.982095+00:00
---
## Trigger
A post-restart/deploy acceptance check requires probing a service endpoint (health/canary), and the port/host is taken from memory, a prior session, or pre-restart config, while a current authoritative status receipt already provides the live process identity (fresh pid, started_at) of that same service.

## Discriminator
Two knowledge-at-time facts: (1) before any probe, the receipt already showed newly started processes (web pid 18241 at 13:39) — the runtime was replaced, so any port remembered from before the restart is unverified, and the live pid is an authoritative handle from which the actual LISTEN address:port can be read in one command; (2) after the failed probe, curl exit code 7 / HTTP 000 is connection refused — definitively 'no listener on that port', not an auth, timeout, or transient issue.

## Short path
- Read the restart/status receipt → unknown: did the deploy reach desired generation and are target processes alive? Output: live pids + started_at proving the runtime was replaced at 13:39–13:40.
- Resolve unknown 'which address:port is the service actually bound to' directly from the live pid (lsof/netstat filtered by pid) instead of assuming the remembered port (8787).
- Probe the derived endpoint once; expected status (401 unauthenticated) confirms both aliveness and auth enforcement.
- If a probe already failed with exit 7 / HTTP 000, treat it as 'no listener on that port' and jump straight to step 2 — do not retry, swap hosts, or scan broadly.
- Stop when every checklist item is verified against receipt or live process state; explicitly report the corrected literal (8903 vs 8787) so stale memory is overwritten.

## Stop conditions
- Endpoint was derived from live process state and a single probe returned the expected status code with normal latency
- All acceptance checklist items are verified from authoritative receipts or live state, with any stale-literal corrections disclosed
- No further probing after the checklist is fully green (avoid post-sufficiency actions)

## Verification
- lsof on the live pid shows the LISTEN port actually held by the current process generation
- curl against the derived port returns the expected code quickly (here 401 in milliseconds), consistent with service alive + auth enforced
- Cross-check: the failed port has no listener among the new pids, confirming the remembered literal was stale rather than the service being down

## Counterexamples
- The status receipt itself exposes the bound port as an authoritative field — use that value directly; an extra lsof is redundant overhead.
- Probe fails with a timeout rather than connection refused — the unknown is network/firewall reachability, so local lsof on the server pid will not resolve it.
- The service runs in a different host/container namespace; local lsof on the pid does not reflect the client-reachable endpoint — service discovery/DNS is the right source.
- The receipt proves config unchanged across the restart (same config hash/generation settings) — probing the known port directly is acceptable and cheaper.
