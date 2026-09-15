# Runtime Config P0 Canary / Rollback Runbook

Date: 2026-09-15

This runbook is a **prepared plan only**. Do not execute it without the deployment checkpoint explicitly authorizing the canary.

## Frozen identities

Runtime root:

`<runtime_root>`

Convergence code root:

`<runtime_root>/.worktrees/memory-runtime-config-p0-convergence-20260915`

Qualified convergence code HEAD before this runbook docs commit:

`031a0e9bb19cb613c9e9e6ce4ebf11bb419a3d1e`

Rollback code root:

`<runtime_root>/.worktrees/memory-schema-fail-closed-20260915`

Rollback HEAD:

`fd42bacd1ae3440dca3bf725078dbb8bf319d3af`

Prepared staged non-secret config:

`/tmp/lfl-runtime-config-canary-031a0e9b.toml`

Expected staged SHA256:

`7f7948389565f8149bfc0c624cd885d760181685919c60c1c5b5d8cb4d83e1b1`

Current live runtime-root `runtime.toml` state at preparation time: **absent**.

Current live memory-index SHA256 at preparation time:

`b98a00741f0b56da997283b13f69598a90757135f1e59235582685a5ae9c79a6`

## Canary invariants

1. Do not restart or replace the unique Ornith 8901 service.
2. Do not remove `.env`; it remains the compatibility/secret fallback in P0.
3. `runtime.toml` must contain non-secret business fields only.
4. Validate the staged file hash before installing it.
5. Install the live file atomically and with mode `0600`.
6. Restart only Web + Feishu using dual-root binding: canonical runtime root + convergence code root.
7. Build/retain exact-source `webui/dist` in the convergence code root before Web restart.
8. Verify runtime identity, config source provenance, memory health, Web UI and Feishu heartbeat after restart.
9. Keep the rollback fd42 worktree and its currently serving dist untouched until user canary is accepted.

## Prepared canary sequence

At the authorized deployment checkpoint, re-resolve every SHA/PID/hash instead of trusting this document blindly.

Mechanical sequence:

1. Verify convergence branch is clean and at the authorized exact HEAD.
2. Verify rollback worktree is clean and at exact `fd42bacd...`.
3. Verify staged TOML SHA equals the frozen expected SHA and still contains no secret-like keys.
4. Verify canonical runtime root still has no pre-existing `runtime.toml`; if that state changed, stop and re-adjudicate rather than overwrite.
5. Atomically install staged TOML as `<runtime_root>/runtime.toml`, mode `0600`.
6. Use the official dual-root restart contract with:
   - `LFL_RESTART_RUNTIME_ROOT=<canonical runtime root>`
   - `LFL_RESTART_CODE_ROOT=<convergence code root>`
7. Restart Web and Feishu only. Leave 8901 untouched.
8. Post-canary verify:
   - Web 8903 readiness and authenticated `/ui/v2/` rendering;
   - Web and Feishu actual code identity = authorized convergence SHA;
   - runtime manifest `identity_ok=true`;
   - manifest config file points to canonical `runtime.toml`;
   - projected business keys report source `runtime_toml`;
   - credentials are not printed in logs/manifest;
   - memory index loads and has no schema-lock/corruption warning;
   - Feishu heartbeat is connected and queue healthy;
   - unique 8901 PID remains unchanged.
9. User performs real work canary: multi-turn chat, model switching, tool calls, long-read/resume, session switch/re-entry and Feishu task execution.

## Rollback trigger

Rollback immediately if any of these appears and is attributable to the canary:

- Web or Feishu cannot start or cannot resolve required configuration;
- runtime identity points to the wrong code root;
- credential/config source resolution regresses;
- memory schema lock/corruption appears on the known-compatible live index;
- Web V2 becomes unavailable;
- material user workflow regresses.

Do not rollback merely for an unrelated historical log warning or an expected transient external-provider failure without attribution.

## Mechanical rollback

The pre-canary runtime state has **no** live `runtime.toml`, so rollback restores that absence and exact fd42 code.

At rollback:

1. Move the canary `runtime.toml` out of the runtime root to a timestamped forensic file instead of deleting its bytes.
2. Set dual-root restart binding back to:
   - runtime root = `<runtime_root>`
   - code root = `<runtime_root>/.worktrees/memory-schema-fail-closed-20260915`
3. Restart Web + Feishu only.
4. Verify actual runtime code identity = exact `fd42bacd...`.
5. Verify legacy `.env` is again the business-config source for the migrated fields.
6. Verify Web V2, Feishu heartbeat and memory index.
7. Verify 8901 PID never changed.

Do not roll back the memory data file to an old snapshot merely because code was rolled back. Memory data is durable live state; restore a memory snapshot only for a separately proven data incident.

## WebUI artifact note

When comparing builds from different directories, do not hash raw `shasum` output containing absolute paths. Use a normalized manifest of relative file path + content SHA256.

The exact fd42 fresh rebuild and the convergence build both produced 63 files with normalized manifest SHA256:

`002092d6c7dbc22d7f1c113aec067b24851dfd33ac43f28869dcbfed8126d44f`

This proves the WebUI source/build content is unchanged by Runtime Config P0.
