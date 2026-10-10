# Session digest and consumption pilot

## Scope and authority

This patch adds an explicit offline Session digest reader/CLI and freezes a small
paired diagnostic pilot. It adds no runtime producer/configuration/tool exposure,
automatic learning, promotion, deployment or restart. Production stays shadow.
New model calls and a dedicated Web Canary require the separately retained
user approval.

The digest is a replayable projection of recorded events, not a semantic summary
of learned facts. Model/human interpretations need separate attribution. No
controller settles statement truth, applicability, correctness or benefit.

## Explicit offline digest

From the candidate import root, bind one authorized session:

~~~sh
python -m llm_loop.knowledge.session_digest_cli build \
  --events-dir /absolute/canonical/event_logs --session-id SESSION
python -m llm_loop.knowledge.session_digest_cli show \
  --digest /private/session/digest.json --session-id SESSION --format markdown
python -m llm_loop.knowledge.session_digest_cli hydrate \
  --events-dir /absolute/canonical/event_logs --session-id SESSION \
  --digest /private/session/digest.json --event-ref event:SESSION:EVENT \
  --start 0 --max-chars 4000
~~~

Build writes only stdout. An operator can explicitly save private per-session
JSON/Markdown (0600 files, 0700 directories). Keep these outside tracked/shared
documents; cached paths grant no cross-agent access. All CLI actions require the
session. This slice installs no automatic settlement, global index or cross-agent
loading. A semantic summary can later cite exact events; it is not generated here.

The new exact-byte EventStore surface leaves ordinary fail-open read/read_cached
unchanged. The digest captures segments twice and rejects drift, damage, partial
lines, duplicate identity, seq gaps and foreign sessions. Source refs/lengths/SHA,
event raw SHA and canonical payload SHA accompany deterministic previews/coverage.
A source starting after seq 1 is incomplete; a snapshot never proves session end.
An explicit partial range can split a pair, leaving it unknown.

JSON has a content-derived digest_ref. Markdown renders the same cached projection
but is not canonical or a loader input. Paging exposes monotonic next_start.
Exact hydration reopens the bound canonical store and checks identity/seq/raw SHA.
Character continuation requires the previous event SHA. Appends mark the view
stale but unchanged old rows remain recoverable. Changed/lost/corrupt sources
never fall back to cached prose.

Discovery/preparation/hydration, Method/Experience declarations, learning_saved
writes, run outcomes and unverified message refs retain original event refs.
Transport joins only an unambiguous ordered call_id/attempt_id. HTTP knowledge
delivery also needs the exact recorded prepared-reference binding. Missing HTTP,
usage or bindings remains unknown. HTTP success does not prove attention or
adoption; adoption/completed does not establish correct application or benefit.
Exact usage payloads are observations, and missing usage is not zero.

## Fresh paired diagnostic replay

The frozen manifest is
tests/fixtures/knowledge_consumption/paired-digest-pilot-20261010.json.
Two new fixed tasks replay historical failure mechanisms: scheduler receipt
identity/coverage/terminal evidence and runtime-copy store bindings. They are
small feasibility tasks, not live production repairs or the retired v3 experiment.

| Row | Task | Arm | Advisor |
| --- | --- | --- | --- |
| 01-A | Scheduler receipt | A | shadow |
| 01-B | Scheduler receipt | B | dedicated-session canary |
| 02-B | Store bindings | B | dedicated-session canary |
| 02-A | Store bindings | A | shadow |

Use GLM-5.3, four fresh bound Web sessions, one Run per row and identical prompt,
tools, model parameters and canonical source snapshot within each pair. No
cross-row answers/conversation or independent oracle enters the provider payload.
A can search on demand. B sees bounded reference candidates and may hydrate,
apply/adapt or skip. Candidate status/freshness stays explicit; no auto-promotion.

Each row uses web-glm-knowledge-consumption-v1: at most 4 physical attempts
(including retries), 8 tool invocations, 180 seconds. Four rows total at most 16
attempts and 32 tools. Denial does not authorize a replacement Run/grant. There is
no qualified hard token/currency ceiling; collect actual whole-run usage, keeping
missing data unknown. The draft manifest creates no session/grant/model call.

## Preflight, approval and normal execution

Before approval, bind the official R9 qualified candidate/tree and record current
production/config hashes/effective shadow/neighbor services. Freeze prompt and
manifest hashes plus private real-store retrieval evidence: source refs/raw SHA,
projection fingerprints, status/freshness, risk/diagnostics, reference byte hash.
Do not substitute changed stores within a pair.

Run each row through real LoopEngine with real read-only lexical typed retrieval
and a fake provider boundary: normal Web ingress/first decision; A no appendix,
B one bounded REFERENCE; no oracle; saved conversation contains no transient
appendix. The checked-in hint fixture tests wire shape only; the separate private
real-store preflight qualifies retrieval. Neither fake answer is a task grade.

Adjacent gates separately verify actual GLM exclusive child dispatch, budget
policy and Web budget binding. These separate offline tests are not one live
Web-to-provider efficacy run. Present the four-row plan as the concrete approval
request. Import/runtime release changes require separate explicit authorization.

After approval, preflight each actual session/ingress/Run identity, resolved GLM
endpoint and installed grant/exclusive transport. Execute via normal Web, never
a direct provider call or fixture bypass. Recheck actual Web provenance/wire
before grading. Only dedicated B sessions get the Canary; default/global mode
and Feishu/Learning remain unchanged. Restore and verify previous configuration/
pointer between rows and at the end. Stop on source/identity mismatch, 1210/
unknown transport, missing terminal/quiescence or budget refusal.

## Outcomes and independent grading

The preparation matrix exposed intermittent cas_contention_exhausted in the
existing eight-tool test: same-execution parallel ledger transactions raced
through the 12 bounded CAS retries before a tool ran. A local transaction mutex
removes that self-contention. Tool/provider execution stays outside the mutex;
cross-process CAS retries, denial semantics and budget limits remain unchanged.
This is a mechanical prerequisite for the pilot, not a new TaskBudget policy.

Preserve each prompt SHA, session/Run/grant refs, transport terminal facts, actual
reference bytes and delivery/hydration/declaration receipts, final answer event/
hash and explicit digest. Search/save frequency or record_use alone is not benefit.

A separate assessor, blind to arm, grades required facts and forbidden claims
against fixed evidence with attributed answer/source refs. The owner can grade;
an extra model assessor needs authorization. No regex/controller decides semantic
correctness. Appropriate skipping is valid.

Record correctness, first completion correctness, failed receipts, rework calls,
whole-run time and input/output tokens over all rounds/retries; never cherry-pick
the final successful attempt. Report both paired deltas, errors, unknowns and
costs. If both arms are initially correct, report the ceiling effect; if B adds
cost without benefit, report that. Two pairs are feasibility observations, not
stable efficacy. Broader/weak-model rollout needs a new preregistered evaluation.
Benefit verification stays open until real rows and independent grades exist.

## Stopped first attempt and API authentication prerequisite

The first authorized 01-A request returned HTTP 403 before any user event, Run,
budget creation or Provider attempt. All four prepared sessions contain only
their creation event; the other three rows were not submitted. Their exact
digests validate the recorded absence of execution, not task correctness or
consumption benefit. Keep this attempt and its one-shot submission marker.

The original client supplied neither a browser session cookie nor an API Bearer
header. Direct loopback does not satisfy the selected budget gate. Separately,
an offline regression exposed a wiring defect: direct request_authenticated
calls ignored an otherwise valid Authorization header when no FastAPI dependency
had supplied parsed credentials. The minimal repair parses that header using
FastAPI's existing scheme parser and reuses the existing Bearer validator.
It preserves explicit credentials, browser cookies and every other budget gate.
The original headerless request remains correctly denied after this repair.

A future automation request must supply the configured WEB_API_KEY in a Bearer
header, loaded only in client memory. Do not persist the key, authorization header
or cookie in commands, trial artifacts or logs. No key change or cookie issuance
is part of this patch. Offline authentication tests make no Provider calls.

The original stop-on-denial rule still applies. An independently qualified auth
patch and a new four-row attempt require explicit approval before merge/publish,
new session/grant issuance or model calls. Recheck the current release, source
snapshot, effective shadow and exact Web-only deployment scope at that point.
Use new identities, retain the same frozen task prompts and limits, and report
the stopped attempt separately. Restore and verify shadow after the new trial.

## Stopped authenticated attempt and isolated IO timeout

The authenticated retry reached one budget-owned GLM transport attempt, then
ended with isolated_transport_open_failed:ReadTimeout before response headers.
HTTP 200 and SSE done represented a terminal program error, not a model answer.
Provider status and token usage were missing and remain unknown. The frozen
unknown-transport stop applies; the other three rows were not submitted, and
the Web configuration and temporary credential were restored/revoked.

The normal client supplied a 120-second timeout, but the budget transport helper
reduced all IO waits to one second, including independently owned child-process
transports. Real loopback regressions reproduce the same opening ReadTimeout
with headers delayed 1.3 seconds, and a worker ReadTimeout with body delayed
1.3 seconds. No external Provider request is part of those regressions.

For an explicitly bound isolated transport, the helper now uses the existing
qualified worker IO bound of at most 60 seconds, respecting smaller configured
timeouts. The parent still checks the exact Run budget while polling IPC and can
terminate/reap its exclusive child during blocked IO. The non-isolated budget
fallback retains its one-second timeout; no-budget traffic retains its original
timeout. A local exit never proves remote completion or billing settlement.

Preserve the stopped Run's exact event window. A later user-initiated Run in the
same session is separate evidence, and cannot fill a frozen pilot row or supply
a paired benefit grade. A newly qualified release and new one-Run-per-session
matrix need separate approval before dispatch; do not resume the stopped grant.
