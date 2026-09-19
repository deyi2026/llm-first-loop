---
method_id: align-session-gap-with-restart-timestamps-before-broad-search-73202fbb57ff
name: align-session-gap-with-restart-timestamps-before-broad-search
description: For 'service/session appears dead' reports, first align the failure window with process lifecycle metadata already visible in status outputs (started_at, restart receipts) and with the session's event-stream gap (activity stops without completion events). If the gap sits on a restart boundary, read that process's lifecycle-specific artifact (exit/shutdown log, restart receipt) at those timestamps before any directory enumeration or record-store keyword search; broaden only if that artifact is absent or cannot explain the symptoms.
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:40ebdeaf-9a55-4606-97b4-08eb7b37a7e3:0:8a8735f834f66ae09962
evidence_refs: learning:learn:1f89c63f0ebe
created_at: 2026-09-18T12:19:45.824151+00:00
updated_at: 2026-09-18T12:19:45.824151+00:00
---
## Trigger
User reports a service/session as unresponsive (no model work visible; a session/UI element vanished). Status output already exposes process lifecycle metadata (per-service started_at, restart receipts), and the event stream shows the affected session's activity stopping — repeated pre-call events with no completion events — near one of those lifecycle timestamps.

## Discriminator
Knowledge-at-time: before any log was opened, the runtime status already showed both frontend service processes had same-day started_at timestamps (i.e., a mid-session restart), and the event stream showed the affected session emitting repeated pre-call events (message-building) with zero completion events — an activity gap aligned with that process turnover. This pair alone narrows 'why no response' from 'anything (model/network/UI/storage)' to 'what the outgoing process did at shutdown', and names the artifact to read: that process's exit/shutdown log.

## Short path
- Read runtime/process status: confirm the stack is alive; record each service's started_at / restart receipts as candidate lifecycle boundaries.
- Read the event stream for the affected session's window: determine whether activity stops silently (pre-call events present, completion events absent) and where the last activity sits.
- If the gap boundary coincides with a lifecycle timestamp, go directly to that process's exit/shutdown log and service log at that boundary — do not enumerate the project directory or keyword-search record stores first.
- Extract the causal shutdown evidence (forced kill after grace timeout / graceful-shutdown timeout cancelling in-flight tasks) and confirm the process generation change via restart receipts and pids.
- Sanity-check current health (other sessions completing normally) to separate 'was broken then' from 'still broken now', then report; stop once symptoms are explained.

## Stop conditions
- A verified lifecycle event coincides with the session's last-activity boundary and each reported symptom is explained (silent run = in-flight stream cancelled; vanished session = severed frontend connection; missing work = output never persisted).
- The lifecycle-aligned artifact is missing, rotated away, or contains no cancel/timeout around the boundary — stop this method and switch hypotheses.

## Verification
- Cancel/timeout/kill entries must timestamp inside the aligned window and belong to the pre-restart process; pid/generation must match the restart receipts.
- Every user-reported symptom must map onto the same lifecycle event; any unexplained symptom keeps the investigation open.

## Counterexamples
- Status shows no restart near the failure window (process start predates all failures): the gap must be explained by upstream request errors or network (e.g., connection-refused retry clusters), not shutdown cancels.
- Event stream shows explicit per-request errors/timeouts instead of a silent gap: read upstream/request error logs; exit logs are irrelevant.
- The gap is explained by a user-initiated interruption that cleanly resumed afterward: no service fault; do not hunt restart evidence.
