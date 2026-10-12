# Qualification — Shared Service Lifecycle Authority P0-A

Date: 2026-09-16
Base: `2c4b9b087f5d2fad2cf2c5c026194038c7613c5c`
Branch: `fix/service-control-p0a-2c4-20260916`

## 1. Problem and authoritative incident evidence

P0-A closes a reproduced ownership defect in the shared LFL Web/Feishu lifecycle. A normal Web session (`91befb7a-f24e-4fb5-bcdf-de3321c01fd1`) used generic `execute_command` to signal the long-lived shared services, including the observed incident shapes:

- `kill -TERM 17029 15769`
- `kill -TERM 58992 59055`
- an earlier `kill -TERM 12038 12121` followed by direct service launch attempts.

The durable tool journal did not lose the action. For the second incident it recorded, in order:

`tool.execution.started → tool.execution.finished(status=success) → tool.execution.receipt_committed`.

The defect was therefore not WAL recovery or receipt persistence. The generic shell genuinely held physical authority to mutate a shared runtime that also served other sessions.

Read-only audit identified the missing boundary:

- CatastrophicGuard intentionally protects only narrow irreversible system-destruction patterns; ordinary `SIGTERM` is outside that contract.
- Production `EXEC_MODE` was unset/empty, so its optional command classification did not restrict the action.
- Web/Feishu do not receive the interactive CLI approval callback.
- Session `run_lease` / `management_lease` protect one session's state, not a shared service.
- JobRegistry ownership protects processes spawned by an owning session; Web/Feishu are not those jobs.
- `maintenance.lock` coordinates watchdog behavior; it does not prove who is authorized to initiate maintenance.
- `restart_mirror.sh` already owns the correct physical stop/start mechanics and stale-PID/run-lock handling, but previously had no caller authority contract.

## 2. Authority model and LLM-first boundary

The model retains semantic authority to decide whether a restart is useful. P0-A does not add a program rule that decides *when* Web or Feishu should be restarted.

The program now owns only the mechanical hard boundary:

1. which exact deployment is eligible to control the shared services;
2. which surface may execute shared lifecycle mutations;
3. stale-generation / root / Git / artifact checks;
4. serialization of deployment publication versus physical restart;
5. durable lifecycle action receipts.

PID, cwd, historical manifest text, or a successful generic-shell approval are observations, not lifecycle capabilities.

This is an LFL tool/control-plane fail-closed ownership fence. It does **not** claim to be an adversarial same-Unix-UID sandbox against arbitrary malicious native code. The exact reproduced and normal LFL tool paths are mechanically fenced; stronger OS isolation, if ever required, remains a separate layer.

## 3. Narrow implementation

### 3.1 Operator-published desired deployment

`src/llm_loop/runtime/service_control.py` introduces closed-schema `managed-service-deployment/v1` state:

- deployment ID;
- monotonic positive generation;
- exact 40-character Git SHA;
- absolute code root;
- absolute runtime root;
- SHA256 of the ignored `webui/dist` artifact tree.

Unknown or missing fields are rejected. Publishing is generation-CAS: observed generation `N` may only publish generation `N+1`. The target Git worktree must be tracked-clean. Ignored WebUI artifacts remain allowed but become part of the deployment identity rather than an untracked assumption.

Operator commands are explicit:

- `service_control show` — read-only desired-state observation;
- `service_control publish` — operator-plane CAS publication;
- `service_control verify` — read-only exact binding verification;
- internal `service_control worker` — detached physical executor entrypoint.

Generic model shell execution is fenced from `publish` and `worker`; those do not become model tools.

### 3.2 Dedicated model-visible lifecycle surface

`src/llm_loop/tools/builtin/service_control.py` adds model-visible `service_control` with only:

- `status`; and
- `restart` for `web`, `feishu`, or `all`.

P0-A deliberately does not expose generic `start` or `stop`.

`restart` requires the exact `expected_generation` just observed from status. A stale generation fails before a worker is created. An accepted action is durably written before the detached worker can affect Web/Feishu; the returned `action_id` can be queried through `status` for `accepted/running/succeeded/failed` terminal evidence.

### 3.3 Generic shell lifecycle fence

ToolRegistry receives `ManagedServiceMutationGuard` before optional EXEC_MODE approval. Generic approval therefore cannot manufacture shared-service authority.

The guard validates current managed PIDs against service-specific live manifests and the actual process command. It blocks the reproduced and adjacent mechanical mutation shapes, including:

- literal managed-PID `kill`;
- shell-wrapped `bash -c` kill;
- mutating official restart scripts from generic shell;
- direct `llm_loop.runtime.launch web|feishu`;
- broad `pkill` / `killall python` shapes that include managed LFL services;
- dynamic PID extraction from per-service manifests, Feishu heartbeat, or `lsof :8903` followed by kill;
- `kill -9 -1`;
- model attempts to invoke operator-only service-control publish/worker CLI.

The guard does not turn `execute_command` into readonly mode. Deterministic tests keep ordinary code/test/Git commands, `ps`, `kill -0`, `pkill -0`, restart `status`, `runtime.launch --dry-run`, manifest reads, and textual grep/echo mentions available.

### 3.4 Service-specific runtime identity observations

`src/llm_loop/runtime/manifest.py` preserves the existing last-writer compatibility manifest and additionally writes atomic:

- `runtime_manifest.web.json`;
- `runtime_manifest.feishu.json`.

These supply current service/PID identity observations for the guard. They never grant lifecycle authority by themselves.

### 3.5 Desired-state-bound physical restart and TOCTOU closure

The accepted action binds deployment ID and generation. The worker derives its restart plan only from the desired deployment:

- absolute `/bin/bash`;
- `<desired code root>/scripts/restart_mirror.sh`;
- desired runtime root as cwd;
- exact code/runtime root environment;
- existing `RESTART_WAIT_IDLE=1` mechanical behavior.

`service-control.lock` is held across generation/deployment revalidation, the physical official restart, and terminal receipt persistence. Desired-state publication takes the same lifecycle lock. A real cross-process test proves a concurrent publish waits while the restart window is active and advances generation only after the worker releases the lifecycle lease.

This closes the check-to-execute race rather than relying on a one-time precheck.

### 3.6 Restart script binding preflight

`scripts/restart_mirror.sh` now verifies the operator-published desired deployment **before any healthy service is stopped**:

- Web/all: exact code root, runtime root, Git SHA, tracked-clean state, and WebUI artifact tree;
- Feishu-only: exact roots, SHA, and tracked-clean state; WebUI artifact is intentionally irrelevant and skipped;
- status: remains read-only and requires no desired deployment.

Missing or mismatched state exits nonzero before stop and records `service_control_binding_failed`.

The existing WebUI artifact preflight from `2c4b9b08` remains in place. P0-A does not auto-build npm assets and does not auto-roll back.

### 3.7 Deterministic worker environment

The first full repository gate correctly rejected two new `dict(os.environ)` uses under the runtime-environment one-way ratchet. No baseline exception was added.

The worker/spawner now receive a minimal deterministic control environment only:

- real account HOME;
- fixed system PATH;
- LANG;
- exact `LFL_WORKSPACE_ROOT`;
- exact `LFL_RUNTIME_ROOT`;
- exact candidate `PYTHONPATH`;
- narrow restart-plan mechanical keys.

Provider credentials, caller `FORCE`, stale business anchors, and arbitrary caller environment are not inherited. A regression test injects `P0A_SHOULD_NOT_LEAK=ambient-secret` and proves the physical restart child sees `unset`.

## 4. TDD and deterministic qualification

The first test run was intentionally RED at collection because `llm_loop.runtime.service_control` did not yet exist. The test set then grew with implementation discoveries rather than weakening the contracts.

Covered contracts include:

- closed schema and generation CAS;
- exact real incident kill shapes;
- ToolRegistry BLOCKED result before shell execution;
- official restart/direct-launch/operator-CLI fencing;
- wrapped and dynamic-PID mutation shapes;
- readonly probes and ordinary shell compatibility;
- accepted action durable before worker spawn;
- stale generation rejection without spawn;
- worker stale-after-accept durable failure;
- worker success on exact desired roots;
- caller-env noninheritance;
- desired-state exact root/head/dirty/artifact verification;
- ignored WebUI artifact allowed while tracked dirty tree is rejected;
- cross-process lifecycle-lock serialization;
- restart-script preflight ordering before stop;
- missing desired deployment fails before restart effects;
- status remains read-only.

Focused P0-A/restart qualification reached **41/41 PASS** before later lock/environment cases were added. The final P0-A file plus runtime-env-ratchet set also passed **27/27** after the minimal-environment repair.

## 5. Adjacent and repository-wide gates

Broader adjacency matrix: **180/180 PASS**, covering P0-A/restart, runtime manifest/identity, Factory, approval flow, registry pipeline/unregister, JobRegistry, tool eligibility, and base/exec/pipeline/waterfall/skills tool behavior.

Static/mechanical checks:

- touched/full Ruff — PASS;
- Pyright — **0 errors / 0 warnings / 0 informations**;
- `bash -n scripts/restart_mirror.sh` — PASS;
- `git diff --check` — PASS;
- whole-tree `scripts/git_security_scan.sh` — PASS.

Final full repository gate:

`PY=<canonical mirror .venv/bin/python> bash scripts/ci_gate.sh`

Result: **PASS**

- whole-tree Ruff: zero violations;
- environment declaration gate: **586 test files / 0 undeclared COMPACT_RATIO dependents**;
- Pyright: **0/0/0**;
- tier0: PASS;
- full xdist pytest: PASS;
- architecture guard: PASS.

### Local CI reproducibility note

The first default `ci_gate.sh` invocation in this linked worktree exited `141` before any gate because the pre-existing fallback pipeline `git worktree list --porcelain | head -1 | cut ...` runs under `pipefail`; with many local worktrees, upstream `git` receives SIGPIPE. `bash -x` proved the exit occurred at that bootstrap pipeline.

P0-A did not expand scope to change CI infrastructure. The gate's supported `PY` input was set explicitly to the canonical `.venv`; `ci_gate.sh` itself then pinned `PYTHONPATH` to this candidate worktree's `src`, so all Python checks executed the P0-A candidate bytes. That run completed the full repository gate successfully.

The existing test-side-effect auditor continues to emit the same 41 low-risk provider-URL review warnings; P0-A adds no live provider calls.

## 6. Operator procedure and evidence

`docs/LFL-restart-guide.md` now documents:

- desired deployment `show → publish(CAS) → verify`;
- model-side `service_control(status) → model decision → restart(expected_generation) → status(action_id)`;
- generic shell lifecycle fence and retained readonly probes;
- exact WebUI artifact identity;
- lifecycle lease behavior;
- rollback as publishing the prior qualified code root as a **new** generation, never decrementing generation;
- the reproduced generic-shell shared-service kill incident and its authority analysis.

Operational evidence paths include desired deployment state, durable action receipts, per-service manifests, the existing restart receipt/log, proc-version evidence, and Feishu heartbeat.

## 7. Non-interference and limits

During all P0-A implementation and qualification:

- production remained on the previously frozen `c5772baa` code root;
- production Web/Feishu were not restarted by this candidate;
- Ornith 8901 was not restarted or reconfigured;
- no second local model was started;
- no provider selection, runtime.toml, model parameter, LFRT resource-governor state, or application-data schema was changed;
- no production desired-deployment record was published yet.

P0-A does change the future tool/control surface once deployed: generic LFL shell calls will no longer be the accepted path for shared Web/Feishu lifecycle mutations. Ordinary development shell capability remains available.

## 8. Deployment bootstrap and rollback

This commit must not be deployed by directly running its hardened `restart_mirror.sh` against an empty desired-state store: that correctly fails before stopping the currently healthy service.

First deployment procedure is intentionally two-step:

1. while the old production remains serving, operator-publish the qualified P0-A code root/runtime root as desired deployment generation 1 (`expected_generation=0`);
2. then invoke the candidate's official restart path or dedicated lifecycle control and complete normal post-canary qualification.

Later deployments publish generation `N+1` using observed `N` and then restart against that exact generation.

Rollback also advances generation: publish the prior qualified code root as the next desired generation, then restart through the same control plane. Do not delete or decrement lifecycle history to express rollback.

Reverting P0-A code itself requires no application-data migration. Desired deployment/action/per-service-manifest files are operational metadata ignored by older code paths and can remain as inert evidence if the implementation is reverted.

## 9. Publication boundary

This qualification is local only. No P0-A review branch, PR, main merge, production desired-state publication, or service restart is authorized by this record. Remote publication and any deployment remain behind the next human checkpoint.
