---
method_id: scoped-terminal-check-via-receipt-contract-533a1957add3
name: scoped-terminal-check-via-receipt-contract
description: When an async action (service_control restart/publish, background job) returns an acceptance receipt embedding its verification contract — acceptance≠completion, scoped check entry (status by action_id, or event_stream query=service_action_terminal) and wait semantics — follow that contract: schedule one short recheck for the named handles, then issue only action_id-scoped status reads. Unfiltered workspace status/audit or event sweeps answer nothing the scoped handles don't, and import stale signals (old generation lags, superseded failed records) that spawn out-of-scope side quests.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8edca76a-022e-442c-9819-960bcdff7f8a:1263:f2b89d0d52b38c33e242
evidence_refs: learning:learn:6641097329cd
created_at: 2026-10-10T07:54:03.455503+08:00
updated_at: 2026-10-10T07:54:03.455503+08:00
---
## Trigger
Follow-up is needed for an accepted background/async action (restart, publish, job) whose receipt explicitly states acceptance≠completion and names the scoped terminal-state check entry and handle(s); the open unknown is that action's terminal state.

## Discriminator
Knowledge-at-time: before any follow-up query, both restart receipts already contained the exact narrow next hop — service_control(action=status, action_id=…) or event_stream(query=service_action_terminal) — plus two-phase wait semantics implying immediate checks return non-terminal (running/waiting_for_idle). The workspace-wide status/audit dump and the unfiltered event sweep were chosen over these already-named scoped entries, and neither answered the target unknown.

## Short path
- Issue the async actions; from each receipt extract action_id, wait semantics, the named check entry, and the failure/pending-acknowledge rule.
- If wait semantics imply deferred execution (requester-session-end → target-idle), schedule one short recheck naming the action_ids and the reporting contract; do not query terminal state yet.
- At recheck, query only the named scoped entries: service_control(action=status, action_id=…) per action; event_stream only with the receipt's query token.
- Map each action_id to an explicit succeeded/failed; on failed, capture reason and pending-acknowledge state, report, and issue no new publish without authorization.
- Escalate to broader discovery only if a scoped entry errors or contradicts the receipt; treat historical records it surfaces as out of scope unless the user's goal covers them.

## Stop conditions
- Every receipt action_id has an explicit timestamped terminal read (succeeded/failed) from its scoped entry, reported to the user.
- Failed terminal states are captured with reason + pending-acknowledge note and reported; no auto-republish.
- Scheduled recheck confirms all named handles terminal; no discovery remains pending for the user's ask.

## Verification
- Path contains zero unfiltered workspace-wide status/event queries; each status read is action_id-scoped via the receipt's named entry.
- Final report maps each action_id to exactly one terminal status; acceptance is never announced as completion.
- Any clarification of incidental historical records is either justified as user-scope or omitted from the reply.

## Counterexamples
- Receipt is a bare ack with no verification contract or handle: discovering the check entry (possibly broad) is then necessary.
- User goal is workspace-wide state ('what's running/stale everywhere?'): the broad status sweep IS the target query, not friction.
- Receipt already carries synchronous terminal state inline (status=succeeded): stop immediately — no recheck, no further reads.
- Wait semantics don't apply (target known idle, no active sessions) and a scoped status read returns terminal immediately: skip scheduling and answer directly.
