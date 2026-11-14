# M5-D: explicit read-only restart recovery Web view

Status: isolated candidate. No production deployment, automatic resume,
Provider retry, Tool replay, queue re-dispatch or service restart.

Base: M5-C 1351d6cffbbaf8ba82dd7bd9d83af1d50200dd80.
M5-A and M5-B both have independent GLM-5.3 PASS P0/P1=0 and original full
R9 exit 0. M5-C review PASS P0/P1=0; its R9 is separately pending.

## 1. Endpoint and authority

GET /api/v1/sessions/{session_id}/durable-recovery is an explicitly invoked
low-frequency diagnostic view. It inherits the existing build_app router-wide
Depends(require_api_key) policy; no new authentication mechanism or session
identity is invented.

The handler verifies session existence, then the helper:
1. Reads strict EventStore source bytes. It requires exactly one
   run.durable.opened event for the session and extracts generation and
   authorization identity from the trusted event payload. No auth ID in URL.
2. Requires 32 lowercase hex generation and authorization IDs; otherwise HOLD.
3. Reads the existing TaskBudgetStore root from settings.data_dir/task_budget_t1_web.
4. Calls M5-A assess_durable_run and M5-C inspect_run_effect_evidence.
5. Returns only reason codes, counts, budget phase/revision and source digest.
   It does NOT return authorization ID, run generation, Provider payload,
   Tool arguments, model text, reasoning, prompts, or raw file contents.

Any missing, corrupt, ambiguous or multiple Run identity returns
unknown_HOLD. No default reissue or inference from matching SHA is allowed.

## 2. Non-interference

The existing high-frequency /continuity route continues using its hot event
snapshot and is not modified. The new view is opt-in because strict
EventStore and TaskBudgetStore double reads can be more expensive.

The view never calls BackgroundRunner.start, engine.run_stream, queue dispatch,
Provider transport, Tool execution, TaskBudgetStore mutation or EventStore
append. It never creates a new authorization or new Run. The result always
contains auto_resume_allowed=false and old_run_replay_allowed=false, even
when a zero-effect M5-A terminal is completed_verified.

The old M4-C sample has no M5 strict opened fact, so the Web view returns
unknown_HOLD/no_durable_run_identity. The M5-C offline audit continues to
report its one unresolved Provider liability. Neither route can clear it.

## 3. Acceptance and outstanding gates

Offline Web TestClient tests cover missing identity, strict opened/fenced
without terminal, unknown Provider dispatch, corrupted EventStore, multiple
Run identities, missing session, existing Web authentication, fresh EventStore
object after process restart, a verified zero-effect terminal that still
cannot replay, byte-exact non-mutation and corrupt budget. No live Provider.

Still outstanding: M5-E dual-worker and SIGKILL matrix across Provider,
Tool, finalizer and nonce revocation, plus authenticated remote Provider
settlement and Tool reservation-to-effect causal binding. The existing
HumanTurnQueue stale reaper and SSE no_active_run behavior must remain
non-replaying. Do not label M5-D as production automatic recovery.

Gate: independent GLM-5.3 PASS P0/P1=0, then original full R9 exit0, then
Host review_admission/remote CI/A.5/privacy verification before main/push.
Managed Mac/Deepin deployment or restart requires separate authorization.
