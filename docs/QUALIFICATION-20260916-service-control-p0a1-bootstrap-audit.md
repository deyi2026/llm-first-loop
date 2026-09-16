# Qualification — Shared Service Lifecycle Authority P0-A.1 Bootstrap Audit Follow-up

Date: 2026-09-16
Base: `49cd308209a4b9f06815141a1d985a343cc64c80`
Branch: `fix/service-control-p0a1-49cd-20260916`

## 1. Scope

P0-A.1 is a narrow follow-up discovered during the **read-only production bootstrap audit after P0-A had already reached main**. Production was intentionally left on the previously frozen c577 runtime while the audit examined whether generation-1 bootstrap and rollback were mechanically safe.

The audit found three contract violations in P0-A:

1. missing-state `read/status/show/verify` created a state-lock file despite being documented as read-only;
2. detached worker import identity followed the desired physical target, so rollback to a pre-P0-A target without `llm_loop.runtime.service_control` could not start the controller;
3. the worker checked deployment ID/generation but did not re-verify physical target bytes immediately before execution, so a pre-P0-A restart script could run after the published target became dirty.

No provider, model, LFRT, application-data schema, WebUI source, restart script, ToolRegistry policy, or semantic restart decision was changed by this follow-up.

## 2. Read-only bootstrap evidence

The pre-implementation audit was non-mutating with respect to production P0-A state and established:

- current main P0-A candidate and c577 rollback source had identical tracked WebUI tree identity;
- the c577 rollback worktree retained a verified ignored WebUI artifact tree suitable for later mechanical reuse;
- c577 and P0-A had identical effective runtime configuration under the same dual-root launch environment;
- production still had no desired-deployment record, service-control locks, per-service P0-A manifests, or service-control worker.

The three blockers were reproduced only in temporary test/audit directories.

## 3. Deterministic RED evidence

Five tests were added before production changes. Initial result: **5/5 failed for the expected reasons**.

### 3.1 Missing-state reads wrote filesystem state

The temporary store began with no data directory. `ManagedServiceDeploymentStore.read()` returned `None` but created `data/runtime/service-control-state.lock`. Model-visible `service_control(status)` and CLI `show/verify` inherited the same behavior.

### 3.2 Pre-P0-A rollback worker could not start

A temporary exact Git target deliberately contained a valid old restart script and WebUI artifact but **no** `llm_loop.runtime.service_control` module. The detached worker inherited the target as `PYTHONPATH`, failed to import the controller, and left the durable action at `accepted` instead of reaching a terminal result.

### 3.3 Publish-after-drift still executed an old target

A temporary target was published and accepted cleanly, then a tracked file was modified without changing deployment ID/generation. The P0-A worker returned success and executed the old target script. This proved generation identity alone did not protect physical target bytes when the target script predated P0-A preflight.

## 4. Minimal production repair

Only `src/llm_loop/runtime/service_control.py` changes production behavior.

### 4.1 Atomic lock-free read path

Desired deployment writes already use temporary-file + atomic rename. P0-A.1 therefore removes state-lock acquisition from `read()` and reads the immutable published snapshot directly. A concurrent missing/initial-publication race returns `None` on `FileNotFoundError`.

Result: missing-state `read`, model `status`, CLI `show`, and CLI `verify` are physically zero-write. Mutation/CAS and action writes retain their existing locks.

### 4.2 Controller identity is independent from desired target identity

The detached worker now derives the controller code root from the currently executing `service_control.py` module. Its Python import environment is bound to that current controller root, while the physical restart plan remains bound to the desired deployment target.

This distinction is required for rollback: an old pre-P0-A target does not need to contain the current control-plane module. The current controller stays alive long enough to validate and invoke the old target's restart script.

### 4.3 Worker re-verifies exact target before physical effect

While holding the existing lifecycle lease, the worker now re-reads desired deployment and calls the existing exact binding verifier immediately before invoking the target script:

- exact code root;
- exact runtime root;
- exact Git SHA;
- tracked-clean state;
- WebUI artifact identity for Web/all (Feishu-only intentionally skips WebUI).

Any mismatch is persisted as durable `failed` and returns before physical script execution. This worker-level verification applies even when the desired target is old code whose own restart script has no P0-A preflight.

## 5. Test fixture strengthening

Two existing P0-A worker-success/lifecycle-lock tests used synthetic non-Git deployments with placeholder artifact hashes. The new exact worker verifier correctly rejected those fixtures. The tests were upgraded to real temporary Git repositories with committed restart scripts and generated deployment identity; production verification was **not** weakened.

## 6. Qualification results

Focused P0-A/P0-A.1 + restart + runtime-environment gate:

- **53/53 PASS**
- Ruff: PASS
- Pyright: **0 errors / 0 warnings / 0 informations**
- shell syntax / diff-check: PASS

Expanded adjacent matrix across runtime manifest/identity, Factory, approval flow, registry pipeline/unregister, JobRegistry, tool eligibility, base tool execution/pipeline/waterfall/skills:

- **191/191 PASS**

Repository-wide implementation-state qualification:

- whole-tree security scan: PASS
- full `ci_gate.sh`: PASS
  - whole-tree Ruff: zero violations
  - environment declaration gate: **586 test files / 0 undeclared dependents**
  - Pyright: **0/0/0**
  - tier0: PASS
  - full xdist pytest: PASS
  - architecture guard: PASS

The existing 41 provider-URL side-effect-auditor warnings remain the same non-blocking baseline; P0-A.1 adds no provider traffic.

## 7. LLM-first authority boundary

P0-A.1 does not add semantic restart policy. The model continues to decide whether a restart or rollback is useful. Program code only repairs mechanical truth:

- a read-only observation must not mutate persistent control state;
- controller bytes and desired target bytes are different identities during rollback;
- physical target bytes must still match the published deployment immediately before effect.

No heuristic decides that a restart should happen, and no PID/runtime observation becomes authorization.

## 8. Production non-interference and deployment boundary

During P0-A.1 audit, implementation, and local qualification:

- production remained on the prior frozen c577 Web/Feishu code root;
- Web/Feishu were not restarted by this work;
- Ornith 8901 was not restarted or reconfigured;
- no production desired deployment or service-control lock was created;
- no WebUI artifact was copied into the P0-A/P0-A.1 worktree;
- no production generation was published.

P0-A.1 must complete normal review/remote qualification before returning to generation-1 bootstrap. Main merge and production bootstrap/deployment remain separate human checkpoints.

## 9. Rollback semantics after P0-A.1

Operational rollback remains monotonic: publish the prior qualified physical target as the next desired generation. The detached worker itself continues to run from the current P0-A.1 controller root, verifies the old target bytes under the lifecycle lease, then invokes the old target's physical restart script. Therefore the current controller worktree must remain on disk until the rollback action reaches a terminal receipt.

Reverting P0-A.1 source itself requires no application-data migration.
