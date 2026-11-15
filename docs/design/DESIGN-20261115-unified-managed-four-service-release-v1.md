# Unified managed release for four Mac services (v1)

Status: isolated implementation candidate; NOT a production rollout receipt.
Baseline: GitHub `main` at `1b4570429d30ee6075dcb7089bfeb4db5027add2` (Mac gen423).

## Problem and compatibility

The existing managed `target=all` intentionally restarts Web, Feishu and Learning,
not WeCom. WeCom maintains a single long-lived robot connection, and restarting
it on every ordinary `all` would interrupt real conversations. `all` therefore
must retain its current meaning, including its coverage warning and tests.

## New explicit operator entry

```
python -m llm_loop.runtime.unified_release \
  --release-id release-unique-20261115 \
  --code-root /absolute/verified/release-checkout \
  --runtime-root /absolute/runtime-root \
  --data-dir /absolute/runtime-root/data \
  --expected-generation 423 \
  --expected-sha <exact-reviewed-40-char-sha> \
  --requester <real-session-id-or-cli-operator> \
  --reason "four-service coordinated rollout"
```

The command returns `accepted=true, completed=false` and a durable journal
path, then detaches the coordinator by default; it does **not** claim deployment
success. Only terminal `status=succeeded` means four-service completion. `--status-only` reads the
journal. Reissuing the **same release ID and arguments** resumes after a
coordinator interruption. `--wait` is for controlled foreground operation only.
The existing `service_control update`, `deploy`, `restart`, and `all`
contracts remain unchanged; no new import is added to service_control.

## State machine and safety invariants

1. Validate the release ID and persist the immutable request under
   `<data-dir>/runtime/unified-releases/<release-id>.json` (mode 0600). One
   exclusive global coordinator file lock serializes four-service rollouts
   across release IDs (existing single-service operators keep their own gates).
2. Build the exact source-checkout deployment using existing source/WebUI
   binding checks; persist its deployment ID **before** the generation CAS.
   Require an explicit reviewed Git SHA; the CAS publishes **once** from
   expected generation N to N+1. Resume
   requires the same deployment ID, SHA, roots and artifact hash.
3. Admit one existing managed `all` action. Its existing detached worker
   waits for requester exit and target idle, runs the three-service physical
   restart, and writes its own verification receipt. The coordinator waits
   for `succeeded / confirmed_ok` and verifies all three live identities.
   The action preserves the real initiating requester session ID, so the
   existing requester-exit gate cannot be bypassed by an idempotency token.
4. Only then admit a separate existing managed `wecom` action. Its worker
   enforces the WeCom idle gate and protects the single long connection.
   If another managed WeCom action already has a verified success receipt
   for this exact deployment ID/generation, adopt it instead of restarting.
5. Report `succeeded` only when **both** action receipts are verified and
   Web/Feishu/Learning/WeCom all have matching live identity, running PIDs,
   and no admission barrier. The journal records both action IDs.

No stage auto-retries a failed physical restart. An ambiguous spawn window
stops instead of launching a duplicate worker. Coordinator timeout leaves
underlying managed actions intact; replay only observes or resumes their
existing receipts. A generation/identity drift stops the coordinator. Existing
managed rollback behavior remains the sole rollback mechanism; no new
unguarded rollback or direct kill/restart is introduced.

## Acceptance

- Positive: one CAS, two ordered actions, four live identities, terminal receipt.
- Negative: generation drift, first-stage failure, stale live identity,
  ambiguous spawn, duplicate caller, interruption/resume, externally completed
  WeCom restart, and malformed release ID.
- Independent GLM-5.3 reviewer PASS/P0=0/P1=0, original full R9 exit 0,
  exact-SHA remote CI before integration; no Mac production switch as part
  of isolated implementation or testing.

## Limits

This is a **Mac source-checkout** coordinator. Wheel/systemd rollout on Deepin
is not implied. It is an explicit four-service operator mode, not a silent
change to the semantics of `target=all`.

## Reviewer P2 disposition

- `verify_evidence_ready` is now polled as nonterminal until the bounded
  deadline; it is never treated as success or physically retried.
- Duplicate CLI dispatches are rejected by the global lock, with the child
  waiting briefly for the parent's PID-journal handoff; an existing live
  worker PID is reported as `already_running`, not a second success.
- The journal path is documented relative to `<data-dir>`.
- Residual P2: the coordinator does not infer failure solely from a stale
  worker PID (PID reuse can make that inference unreliable). It times out
  without replaying physical work and can be resumed by the same release ID.
- Residual P2: the per-stage 3600-second wait remains fixed in v1. This is
  a bounded observation window, not an idle-gate override; a still-busy
  service is never forced to restart and the same release ID can resume.
  Adjustable timeouts can be added after real operator evidence warrants it.

## Interrupted adoption and ambiguous spawn recovery

An adopted external WeCom receipt is reloaded by its **recorded action ID**
on resume, not by the coordinator requester/origin. The coordinator validates
target, exact deployment ID/generation, succeeded/confirmed_ok, and current
live identity before declaring completion. If any check fails, it blocks and
does not restart WeCom.

For `spawn outcome unknown`, do not repeat `release-four` expecting it to
re-spawn a worker. Inspect the journal's phase action ID, the durable action
file, recorded worker PID, per-action restart log, runtime manifests and
service-control barriers. If any physical side effect is uncertain, STOP and
seek operator adjudication. Only when there is positive evidence that the
original action never reached a physical restart may an operator arrange
a single controlled recovery using the existing managed worker path. Never
run `restart_mirror.sh` directly or clear barriers to force completion.

- Reviewer P2 accepted: a `spawn_intent` whose spawn call raises remains
  fail-closed. The caller cannot prove whether the exception happened before
  or after a child process was created; clearing the intent could permit a
  duplicate physical restart. Require manual evidence instead.

## Latest independent review and minimal repairs

A follow-up GLM-5.3 review of `fa1a8e5e9` returned REVISE/P0=0/P1=1:
phase2 could discover its own accepted WeCom action after a crash before
`phase2_action_id` was journaled, then reject it as an identity mismatch.
The coordinator now routes every such own action through the same
`_start_or_recover_action` path used by phase1, persisting the action ID
before any worker spawn. The targeted negative test injects exactly this
accepted-but-not-journaled state and verifies one spawn and no replay.

Additional reviewer P2 disposition:

- Existing external WeCom action in flight is now adopted by exact action ID,
  then awaited through the existing receipt/verification path. A failed or
  unverified external action blocks a second reconnect, rather than being
  silently ignored. An ambiguous pair of in-flight actions blocks.
- A detached coordinator's recorded PID is not an authority for liveness
  (PID reuse). Global `flock` ownership plus the per-action spawn-intent
  journal are the safety authorities; acquiring the lock permits resume.
- The unused terminal-status constant was removed. Existing action status
  contract has only `succeeded` and `failed` as terminal states;
  `verify_evidence_ready` remains nonterminal and is awaited.
- The initial journal file and its containing directory are fsynced,
  matching the durable atomic-write contract used on later updates.
- The child lock-handoff timeout is intentionally fail-closed: it logs an
  explicit error, does not claim release success, and does not mutate a
  journal while a different coordinator owns the global lock. A later
  operator-initiated same-ID resume rechecks existing action receipts.

No direct service restart, forced idle override, or `all` semantics change
was introduced by these repairs.

## P2 closure after the exact-SHA review

GLM-5.3 review of `83288ef3` returned PASS/P0=0/P1=0/P2=4. The worker
identity P2 was addressed by validating `release_id` and `data_dir` from the
opened journal against the requested path in both the worker entry and the
locked coordinator; read-only status also validates identity. Negative tests
cover swapped release IDs and data directories before any CAS or restart.

The source-checkout Python path is intentionally derived from this module's
package root. Installed wheel/Deepin rollout remains out of scope. PID/lock
handoff and fake-store test coverage remain explicitly documented residuals;
no real service was restarted by these tests. The production release still
requires independent review of the revised SHA, original R9 exit 0 and
exact-SHA GitHub CI before any operator-controlled switch.

## Final reviewer P2 residuals

The independent GLM-5.3 review of source candidate `e00dd6b3` returned
PASS/P0=0/P1=0/P2=5. These nonblocking residuals remain explicit:

1. In the tiny worker-spawn/PID-write gap, a crash can leave an accepted
   action with unknown spawn outcome. This **blocks** rather than launching a
   duplicate physical restart; a human must reconcile durable action and
   process evidence.
2. Two detached coordinator processes may be briefly alive during a lock
   handoff, but only one owns the global flock and can issue managed actions.
   An action's own durable spawn intent independently prevents a second
   physical restart.
3. Intermediate directory symlinks are not a separate sandbox authority.
   The operator-supplied data root is resolved before use, the journal and
   lock/log leaf files are O_NOFOLLOW, and all writes are in the explicit
   operator-controlled data directory. Do not treat this as an authorization
   mechanism for arbitrary untrusted callers.
4. The detached worker path re-reads the journal under its own global lock;
   the worker entry and locked run both validate the immutable release ID and
   data root before CAS or restart. Same-user concurrent journal tampering is
   outside the trust boundary; no false-success outcome is permitted.
5. A detached child can fail its bounded lock handoff and leave a nonterminal
   `dispatching` journal. The action ledger and managed service identity are
   the authoritative recovery facts; a later same-ID operator resume
   reconciles them without replaying a physical restart.

The architecture manifest is a mechanical declaration only. It does not
replace the independent reviewer, original R9, GitHub CI, or managed release
preflight. Deepin production and the Qwen 131K model are outside this change.

## R9 host-local timekeeping correction

The first original full R9 on `b26fe7b26` returned exit 1 with one genuine
new red: `tests/unit/test_timekeeping_local.py::test_source_does_not_serialize_new_wall_clock_in_utc`
(15,325 passed, 1 failed). The coordinator's new `_now()` used
`datetime.now(UTC).isoformat()`, violating the existing host-local timestamp
contract. It now calls the authoritative `system_local_now_iso()` helper;
negative regression checks both `updated_at` and `completed_at` UTC offsets.
The guard/test was not modified or weakened. A new exact-SHA independent
review and original full R9 are required before GitHub integration.
