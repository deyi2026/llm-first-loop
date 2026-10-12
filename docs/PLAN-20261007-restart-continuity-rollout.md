# Restart continuity rollout after FR-1 first review

User authorization: “按顺序执行” following the ordered proposal to validate a minimal current-main candidate, merge, then deploy only after the FR-1 T+24h first review passes. This runbook prepares that conditional action; nothing is published or restarted by creating it. Live tests use GLM-5.3 only. No git push or external messages are authorized.

## Prerequisites

Read RESULT-20261007-restart-continuity-main-integration.md, the full original FR-1 authorization/stop criteria in PLAN-20261006-fr1-semantic-method-activation-authz.md, and fresh durable T+24h review evidence. The first existing read-only review is scheduled for 2026-10-07 20:00 Asia/Shanghai. Elapsed time, a previous T+0 PASS or an incomplete review is insufficient. Require PASS on the original required activation/stability criteria with source/time references; unknown required evidence blocks rollout. Preserve the independent 7d/28d observations.

Pin the main delivery HEAD, source SHA256s, native recovery result, clean candidate and artifact before acting. Refresh actual live/desired identities, configuration provenance, runtime health and queues. Source drift, pending conflicting lifecycle action, a critical condition or unexplained config/model change blocks this package; do not force/stash/replace user work or broaden into unrelated fixes.

## Current reviewed baseline

| Surface | Source | PID | Model / scopes |
|---|---|---:|---|
| Desired gen 181 | 3e502592bba38e88a309d8fa958a1c6a09712594 | — | deployment deploy-12fd22aa194c46fcb396f1390b9d4bbe |
| Web | a519f41b9486a4ce7eab5c94dd37f19f4c98dc3c | 40200 | glm/glm-5.3; Memory=1, other semantic scopes=0 |
| Feishu | a519f41b9486a4ce7eab5c94dd37f19f4c98dc3c | 40406 | glm/glm-5.3; Memory=1, other semantic scopes=0 |
| Learning | 3e502592bba38e88a309d8fa958a1c6a09712594 | 68464 | glm/glm-5.3; Memory=1, Method=1, other scopes=0 |

Snapshot configuration hashes: Web 6415cdd8a88380421cbeaf489933a35b5f52f2382a67ebdc261069bb5102b884; Feishu f3977b13c0d971324fbda86932a6b7640dbbb2f88856cdc2b490d7ba83fb1cd0; Learning a1d212830f0c4d8ba38d8db3769c361dc832345c9366862c7b45a65bfc55f824. Refresh and explain differences before mutation.

Entire live→candidate path census and full patches are retained in the validation evidence. Both live source deltas have four runtime source paths: browser/attestation.py (default constructor fail-closed factory rename), factory.py (matching call rename plus import ordering), core/loop/engine.py and core/recent_continuity.py (the tested anchor repair). Source hunks have been read. No scripts, dependency locks, frontend source or runtime configuration change. Web/Feishu's larger 37-path census also includes docs/evals/experiences and 17 Method files; these are all candidate status and byte-identical to the existing canonical runtime files. They are not promoted or copied into the runtime as part of rollout. Learning's census is 13 paths before final evidence-only commits. Recompute the complete final delta and reject unreviewed runtime additions.

## Prepared candidate and rollback artifacts

Use the clean fix/restart-continuity-main-20261007 worktree as code_root and the canonical project as runtime_root. Root has pre-existing tracked/untracked changes, so it is not a publishable code_root. Shared runtime venv is intentional; managed dual-root launch explicitly binds PYTHONPATH to code_root/src.

Candidate Web UI was built from the candidate source using existing lock-aligned dependencies. Its complete artifact hash equals the recorded prior artifact: 52970dd259d30bebd55269fbf6aa3f99253c032fd9e42d659cd8d86db95aa879.

Two detached clean rollback worktrees already exist under .worktrees: restart-continuity-rollback-a519f41b9-20261007 for Web/Feishu's exact live source, and restart-continuity-rollback-3e502592b-20261007 for Learning/previous desired. Their copied prior Web UI artifact has the exact same verified hash. Read-only build_deployment binding checks passed; neither has been published. Preserve runtime.toml, .env and semantic overrides.

## Ordered execution through managed authority

1. Reconfirm all prerequisites and save fresh baseline/config/queue/health evidence. Freeze code_root HEAD and artifact SHA256. Use the current schema; validate an effective-config dry run without altering defaults.
2. Publish the clean candidate through llm_loop.runtime.service_control publish with code_root=candidate, runtime_root=canonical root and an explicit expected_generation equal to the freshly read desired generation. Retain the new deployment/desired receipt; do not use all-service update.
3. Accept/restart **Web only**, through managed authority with the newly published generation CAS (the current CLI restart derives and CAS-checks its freshly read desired generation). Keep admission/requester/idle gates intact. Require terminal succeeded/confirmed_ok; record Web's new source/PID/config hash and health/UI statuses. Feishu and Learning must retain their original PIDs/configs. Run a GLM-5.3 continuity smoke through an isolated native session against the same pinned candidate if fresh runtime validation is needed; do not send messages to people.
4. Observe Web readiness, foreground settlement, errors/queues and unchanged other services for at least five minutes using short, nonblocking reads. Any failed/unknown required check stops further rollout. Do not run a broad concurrent restart.
5. If the canary passes, restart **Feishu**, then verify its terminal receipt/model/config/health and that Web/Learning remain stable. Only then restart **Learning**, preserving the existing service-specific Method=1 override, and verify its manifest/queue/embedding/FR-1 canary invariants. Keep current health unknowns explicit. No configuration or semantic-scope experiment belongs to this rollout.
6. Record final service identities, managed generations/receipts, unchanged user-work hashes and FR-1 evidence references. Pause the follow-up condition automation after successful completion or a terminal failed review/rollout requiring a new direction. Do not alter the original read-only FR-1 automations.

## Failure and rollback

On a new critical regression, preserve receipts, stop sequential rollout and roll back only services already changed. Publish the prepared source matching each affected service's original live HEAD with fresh expected_generation CAS, restart only that service, and verify restored source/model/config/health. For Web/Feishu this is a519f41b9; for Learning it is 3e502592b. Do not roll back an untouched service. Restore the previous desired source 3e502592b through a final CAS publish without an all-service restart; generations remain monotonically increasing, not reset to 181. Preserve admission/idle gates and the canonical semantic configuration throughout. Unknown rollback health is not success.
