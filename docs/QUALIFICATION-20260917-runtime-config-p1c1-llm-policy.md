# Qualification — Runtime Config P1-C1 LLM Policy

Date: 2026-09-17

## Scope

This tranche starts Runtime Config P1-C by moving four **non-secret, non-debug LLM call-time business-policy reads** from ambient process environment authority into the existing startup-resolved `Settings` / `runtime.toml` boundary.

Exact identities:

- formal base: `49cd308209a4b9f06815141a1d985a343cc64c80`
- implementation commit: `742bc2db961d359f185ee9d7821c283be2386567`
- branch: `fix/runtime-config-p1c-llm-policy-20260917`

The four migrated keys are exactly:

- `LLM_TRUST_ENV`
- `LLM_RETRY_DISCONNECT`
- `ANTHROPIC_CACHE_CONTROL`
- `CACHE_GUARD_HIT_TELEMETRY`

This tranche does **not** migrate `LFL_DATA_DIR`, payload-trace diagnostics, `LOCAL_ENABLE_THINKING`, `LMS_*`, provider credential lookup, Web business settings, Feishu business settings, or SecretProvider/provider-admin state.

## Before / after environment inventory

Corrected alias/helper-aware scanner facts on exact formal base `49cd3082`:

- physical/direct env accesses: **132**
- effective env accesses: **143**
- effective module-import env reads: **0**
- business-config accesses: **69**

Committed P1-C1 result on `742bc2db`:

- physical/direct env accesses: **128**
- effective env accesses: **139**
- effective module-import env reads: **0**
- business-config accesses: **65**
- unique env keys: **53**

All four target keys disappear from the scanner inventory. No ratchet baseline was widened; this is a strict one-way reduction.

## Implementation and authority

The existing closed `[llm]` `runtime.toml` schema now accepts optional policy fields:

- `trust_env` -> `LLM_TRUST_ENV`
- `retry_disconnect` -> `LLM_RETRY_DISCONNECT`
- `anthropic_cache_control` -> `ANTHROPIC_CACHE_CONTROL`
- `cache_guard_hit_telemetry` -> `CACHE_GUARD_HIT_TELEMETRY`

`load_settings(...)` resolves these once into immutable `Settings`. `build_engine(...)` injects the snapshot into the default `LLMClient`, and `ModelClientPool` propagates the same startup policy to routed clients.

The runtime no longer re-reads these four process-environment keys during client construction, guard creation, request streaming, or Anthropic cache-policy evaluation.

Omitted optional booleans preserve the historical provider-aware automatic behavior:

- local LLM endpoints default to `trust_env=false`, remote endpoints to `true`;
- Anthropic cache control remains auto-enabled only for loopback endpoints;
- cache-hit telemetry remains disabled by default for `lms-chat`, enabled otherwise;
- disconnect retry remains `1` by default.

The canonical resolver precedence is unchanged. A hostile stale-shell regression proves `runtime.toml` is authoritative when ordinary ambient shell values disagree; the existing explicit operator override mechanism remains outside this tranche and is unchanged.

## TDD evidence

The initial P1-C1 RED was **5/5 RED**, each failure matching a required missing capability:

1. the closed runtime.toml schema rejected the four LLM policy fields;
2. `Settings` had no typed startup snapshot fields;
3. `LLMClient` could not receive a snapshot;
4. routed clients could not inherit the snapshot;
5. the corrected scanner still observed all four call-time env reads.

After the implementation, focused qualification is **7/7 PASS**, additionally proving runtime.toml precedence and the real `Settings -> build_engine -> LLMClient` assembly path.

Existing tests that intentionally mutated these environment variables *after* client construction were updated to inject the same values explicitly at construction time. This preserves the tested transport/cache behavior while removing the old shared-mutable-process-state contract.

## Deterministic qualification

On committed implementation `742bc2db961d359f185ee9d7821c283be2386567`:

- P1-C1 focused: **7/7 PASS**.
- runtime/config/env/startup + LLM client/pool/provider/factory adjacency: **313/313 PASS**.
- corrected env inventory: **128 direct / 139 effective / 0 module-import / 65 business-config**.
- changed-file Ruff: **PASS**.
- changed production Pyright: **0 errors / 0 warnings / 0 informations**.
- `py_compile`: **PASS**.
- `git diff --check` / `git show --check`: **PASS**.
- staged security scan: **PASS**.
- committed-state full `scripts/ci_gate.sh`: **PASS** when invoked with the formal repository Python explicitly:
  - repository Ruff PASS;
  - env-pin gate **587 test files / 0 undeclared COMPACT_RATIO dependents**;
  - Pyright 0 / 0 / 0;
  - tier0 PASS;
  - xdist full PASS;
  - architecture guard report PASS.

The first linked-worktree invocation of `scripts/ci_gate.sh` exited `141` before producing test output. Root cause is a pre-existing Gate bootstrap pipeline: when a linked worktree has no local `.venv`, `git worktree list --porcelain | head -1` runs under `set -o pipefail`, so upstream `git` may receive SIGPIPE. Re-running the unchanged committed candidate with `PY=../../.venv/bin/python` bypassed only that interpreter-discovery pipeline and completed the full Gate successfully. This tooling defect is recorded separately and is not attributed to P1-C1.

## Secret and diagnostic boundary

Secrets remain process/secret-provider material. In particular, dynamic provider `api_key_env` reads are not migrated into `runtime.toml`.

Residual `llm/client.py` process-env reads intentionally left for separate tranches are diagnostic/debug/compatibility paths such as `LLM_PAYLOAD_TRACE*`, `LFL_DATA_DIR` for trace output, `LOCAL_ENABLE_THINKING`, and `LMS_CHAT_TAIL`.

## Production boundary

This qualification performs no live deployment:

- no Web/Feishu restart;
- no 8901 restart or second local model;
- no provider/model switch;
- no push or PR;
- no production `runtime.toml` mutation.

## Next boundary

Runtime Config P1-C should continue independently with **Web call-time business settings**, then Feishu call-time business settings. SecretProvider/provider-admin and diagnostic/debug env governance remain separate tranches.

## Rollback

Revert `742bc2db`. The four runtime.toml fields are optional, no persistent data conversion is involved, and omission retains the historical automatic/default behavior.
