# Qualification — Runtime Config P1-A2 Feishu Import-Time Closure

Date: 2026-09-16

## Scope

This tranche closes the five **effective** Feishu module-import business-configuration reads exposed by the corrected alias/helper-aware environment audit on current formal main.

Exact identities:

- formal base: `fe209380a13b20e69bdb2e2ebdd17dc77c31fd40`
- implementation commit: `4ba02f4e30542158d8dac325b940a40bc6bedb49`
- branch: `fix/runtime-config-p1a2-fe209-20260916`

The older P1-A qualification reported `module_import=0` using direct AST syntax only. C0-A later corrected the scanner to project literal helper calls and showed five real import-time reads. P1-A2 closes that proof gap rather than redefining the old result.

## Before / after inventory

Corrected scanner facts on exact formal base `fe209380`:

- physical/direct env accesses: **134**
- effective env accesses: **150**
- effective module-import env reads: **5**
- files with env access: **44**
- dynamic-secret signatures: **6**

The five import-time reads were exactly:

- `FEISHU_EXIT_WAIT_S` — 1
- `FEISHU_EXIT_DRAIN_S` — 2
- `FEISHU_MSG_PROCESS_TIMEOUT_S` — 1
- `FEISHU_SILENT_THRESHOLD_S` — 1

Committed P1-A2 result:

- physical/direct env accesses: **132**
- effective env accesses: **143**
- module-import direct reads: **0**
- module-import helper-projected reads: **0**
- total effective module-import reads: **0**
- files with env access: **44**
- dynamic-secret signatures: **6**

No new env signature is introduced. This is a strict one-way reduction.

## Implementation

The four timing controls are non-secret mechanical runtime policy and are now part of the closed typed `[feishu]` `runtime.toml` schema:

- `exit_wait_s` -> `FEISHU_EXIT_WAIT_S`
- `exit_drain_s` -> `FEISHU_EXIT_DRAIN_S`
- `msg_process_timeout_s` -> `FEISHU_MSG_PROCESS_TIMEOUT_S`
- `silent_threshold_s` -> `FEISHU_SILENT_THRESHOLD_S`

`llm_loop.feishu` and `llm_loop.feishu.bridge` freeze these values from immutable `business_config_snapshot(...)` results backed by canonical `RuntimeConfig`, matching the existing P1 import-time migration pattern.

The pure `_resolved_float()` parser preserves the old compatibility behavior for malformed legacy `.env` values: invalid strings fall back to the historical defaults rather than breaking import.

Default behavior is unchanged:

- exit wait: `10.0s`
- exit drain: `3.0s`
- processing timeout observation: `300.0s`
- silent threshold observation: `1800.0s`

At production preflight time none of these four keys was configured in canonical runtime.toml/.env or ambient process env, so the deployed `fe209380` service is already using those same defaults.

## Authority and precedence

The canonical resolver contract remains unchanged:

1. explicit CLI values;
2. shell only when `LFL_ALLOW_RUNTIME_OVERRIDE=1`;
3. canonical runtime-root `runtime.toml`;
4. legacy runtime-root `.env` during migration;
5. local defaults.

A hostile stale shell test proves ordinary ambient values cannot override runtime.toml. A separate test proves explicit `LFL_ALLOW_RUNTIME_OVERRIDE=1` still gives the operator the existing emergency override path.

## Secret boundary

This tranche intentionally does **not** migrate or serialize secrets. In particular it does not move:

- `FEISHU_APP_SECRET`
- provider/API credentials
- provider-admin dynamic credential reads/writes

SecretProvider/provider-admin remains a separate later tranche. `runtime.toml.example` remains secret-free and the existing gate continues to reject secret-looking fields.

## Deterministic qualification

On committed implementation `4ba02f4e30542158d8dac325b940a40bc6bedb49`:

- P1-A2 focused: **10/10 PASS**
  - closed schema recognizes the four typed fields;
  - runtime.toml beats stale ambient shell;
  - explicit runtime override remains authoritative when enabled;
  - malformed legacy `.env` timing values fail open to defaults;
  - effective module-import env access is exactly zero.
- runtime/config/resolver/identity/manifest/startup/proc-version adjacency: **132/132 PASS**.
- Feishu bridge / WS guard / interruption / exit-contract adjacency: **55/55 PASS**.
- changed Python Ruff: **PASS**.
- changed production Pyright: **0 errors / 0 warnings / 0 informations**.
- `py_compile`: **PASS**.
- `git diff --check`: **PASS**.
- whole-tree security: **1911 tracked files PASS** after the implementation commit.
- full committed-state `scripts/ci_gate.sh`: **exit 0**:
  - repository Ruff PASS;
  - env-pin gate **585 test files / 0 undeclared COMPACT_RATIO dependents**;
  - Pyright 0 / 0 / 0;
  - tier0 PASS;
  - xdist full PASS.

Two exploratory adjacency commands referenced non-existent test filenames and exited before executing their intended matrix; they are explicitly excluded from qualification. The corrected real-file matrix above is the authoritative result.

## Production boundary

No production mutation is part of this qualification:

- production remains exact formal main `fe209380`;
- Web and Feishu are not restarted by this tranche;
- the sole Ornith 8901 service is not restarted or duplicated;
- current LFRT RG-2 authority configuration remains unchanged;
- PR #17 remains an independent historical review anchor and is not modified.

## Remaining config-governance work

P1-A import-time business env semantics are now actually closed under the corrected scanner: effective module-import access is zero.

P1-C remains separate. Current call-time business reads in LLM/Web/Feishu and the SecretProvider/provider-admin migration must not be conflated with this import-time tranche.

## Rollback

Revert `4ba02f4e`. No runtime.toml migration is required because the four fields are optional and current production does not set them. Legacy defaults remain the same. No persistent data/schema conversion is involved.
