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
python -m llm_loop.runtime.service_control release-four \
  --release-id release-unique-20261115 \
  --code-root /absolute/verified/release-checkout \
  --runtime-root /absolute/runtime-root \
  --data-dir /absolute/runtime-root/data \
  --expected-generation 423 \
  --expected-sha <exact-reviewed-40-char-sha> \
  --requester <real-session-id-or-cli-operator> \
  --reason "four-service coordinated rollout"
```

The command returns a durable journal path and detaches the coordinator by
default; it does **not** claim deployment success. `--status-only` reads the
journal. Reissuing the **same release ID and arguments** resumes after a
coordinator interruption. `--wait` is for controlled foreground operation only.
The existing `update`, `deploy`, `restart`, and `all` contracts remain unchanged.

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
