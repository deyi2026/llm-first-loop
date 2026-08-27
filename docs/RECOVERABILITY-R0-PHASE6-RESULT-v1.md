# Evidence Recoverability R0 Phase 6 Result v1

Date: 2026-08-26
Status: **DETERMINISTIC PASS — NOT FULL R0**
Provider API calls: **0**
Production activation: **NO** (`EVIDENCE_MODE` remains unset -> `off`)

## Objective

Phase 6 closes ownership and lifecycle gaps left by the old deterministic truncation sidecars under
`data/audit/tool_outputs/` and `data/audit/cmd_outputs/`.

Invariant:

> Existing bytes are not Evidence merely because they exist on disk. A legacy sidecar becomes
> owner-visible Evidence only after a persisted session observation proves ownership and integrity;
> unowned bytes remain model-invisible. Physical blob deletion is allowed only when no logical
> Evidence record references the blob.

## Implemented

### Mechanical legacy ownership proof

`LegacySidecarMigrator` accepts a legacy `.log` only when all of the following hold:

1. a persisted `role=tool` message explicitly references that exact `.log` path;
2. the path is inside `DATA_DIR/audit/tool_outputs` or `cmd_outputs`;
3. the candidate is a regular non-symlink file;
4. the deterministic filename SHA-256 prefix matches the exact sidecar bytes;
5. the `[输出已截断]` marker's `total/head/tail` values parse correctly;
6. `total == len(full_sidecar)`; and
7. the persisted tool result actually starts/ends with the claimed head/tail bytes.

A proven sidecar is captured as owner-scoped Evidence with provenance
`producer=legacy_sidecar_migration`, `authority=persisted_tool_result`, and the original
`tool_call_id` when available.

### Quarantine inventory

Files that are orphaned, tampered, symlinked, unreadable, outside the permitted roots, or otherwise
fail proof are **not** added to the Evidence ledger. They remain physically untouched and are listed
only in:

`DATA_DIR/evidence/quarantine/legacy_sidecars.json`

The inventory explicitly records `model_visible=false`. Read/stat failures are represented as
`inventory_error` / `unreadable`; no fail-silent `pass` remains.

### Workspace ordering

An integration test exposed a real ordering bug in the first implementation attempt: migration was
running before WorkspaceStore legacy-session migration and before the current workspace's session
root was activated. Phase 6 corrected the order:

```text
WorkspaceStore legacy-session migration
-> activate current workspace/session partition
-> conservative legacy sidecar ownership scan
```

The same optional migration hook runs after later workspace activations, so a workspace switched in
after startup is scanned only after its session partition is active.

### Compression bridge reuse

For legacy tool messages, compression now checks the owner's Ledger by `tool_call_id` before
creating a conversation-history Evidence record. If Phase 6 already migrated the full sidecar, the
compressed message reuses that full EvidenceRef instead of replacing it with a new record containing
only the legacy truncated projection.

### Session deletion and shared blob lifecycle

Evidence logical ownership is cleaned when a session is physically deleted even if the current
runtime has returned to `EVIDENCE_MODE=off`. Ledger owner discovery uses persisted `owner.json`
metadata rather than current rollout mode or current workspace assumptions.

Deletion order is:

```text
remove owner-scoped logical records
-> compute remaining global blob refcount
-> delete immutable blob only at refcount == 0
```

Two sessions may therefore share identical content-addressed bytes safely: deleting the first owner
retains the blob; deleting the last owner collects it.

### Capture/GC race closure

Phase 6 also found and closed a concurrency race:

```text
GC sees refcount=0
-> concurrent capture commits a new record to the same blob
-> GC unlinks blob
-> dangling logical record
```

`EvidenceCapture` and physical GC now serialize on the same durable `.gc.lock`. A forced race test
pauses deletion after zero-ref observation, starts a concurrent capture, and proves capture waits
behind GC; after both complete the surviving record always has valid blob bytes.

## Deterministic gates

Phase 6 focused tests cover:

- valid `tool_outputs` migration and exact hydration;
- valid `cmd_outputs` migration;
- migration idempotence;
- tampered sidecar quarantine;
- orphan sidecar quarantine;
- symlink rejection;
- shared-blob last-owner GC;
- idempotent delete of unknown owner;
- enforce factory auto-migration after workspace activation;
- compression reuse of the migrated full sidecar by `tool_call_id`;
- off-mode session deletion of prior Evidence;
- corrupt owner metadata isolation;
- forced capture-vs-zero-ref-GC race safety.

## Verification

- Phase 6 focused suite: **11/11 PASS** before the additional race/cleanup checks; final focused file
  contains the full expanded gate set and passes.
- All `tests/unit/test_evidence*.py`: **PASS**.
- Targeted Ruff: **PASS**.
- Targeted Pyright: **0 errors, 0 warnings**.
- Broad workspace/session/history/factory/cache/event regression: **PASS** in project `.venv`.
- Full repository non-real-LLM suite:
  `PYTHONPATH=src .venv/bin/pytest -q --ignore=tests/unit/test_action_guard_a3.py` -> **exit 0**.
- The ignored A3 file is the already-stopped development artifact with its unrelated broken import.

## Runtime boundary

Current `.env` remains:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

No production Evidence behavior is enabled. Enforce + the currently enabled ToolExecutionPipeline
still fails closed until its post-hook/capsule ordering is explicitly integrated or the pipeline is
disabled for a controlled enforce run.

## Remaining R0 work

Only Phase 7 remains:

- aggregate R0-1..R0-12 deterministic gate;
- post-run integrity/status audit;
- explicit runtime activation eligibility decision.

Phase 6 makes no provider-effectiveness claim.
