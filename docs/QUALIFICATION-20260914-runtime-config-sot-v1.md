# Runtime Config SoT v1 — Qualification 2026-09-14

## Decision

Business configuration moves toward a typed file-backed single source of truth without turning runtime/session state or secrets into ordinary files.

Precedence for governed business keys is:

1. explicit CLI argument;
2. process environment only when `LFL_ALLOW_RUNTIME_OVERRIDE=1`;
3. workspace `runtime.toml`;
4. legacy workspace `.env` during migration;
5. launch / `Settings` defaults.

Secrets are not valid `runtime.toml` fields. Secret-looking or unknown TOML fields fail closed. Existing secret environment / legacy `.env` support remains a compatibility boundary while a dedicated secret provider is outside this tranche.

## Mechanical ownership

`RuntimeConfig` is frozen and exposes read-only mappings for values, provenance and ignored stale shell values. `legacy_settings_snapshot()` supplies old consumers without requiring them to read process-global state. `apply_to_environ()` remains only as a temporary bootstrap adapter for deep legacy readers.

`DATA_DIR` and `LFL_DATA_DIR` stay distinct fields. Existing code and restart contracts use them for different legacy anchors; v1 does not collapse them.

Runtime/session facts such as session id, `run_generation`, provider-call identity, active task state and browser state are explicitly outside `runtime.toml`.

## First migration tranche

The first tranche covers central `Settings` assembly plus Web / Feishu startup consumers:

- `load_settings(mapping)` and typed parsers accept an explicit snapshot;
- identity checks accept an explicit environment/workspace snapshot;
- Web host/port and exit log paths no longer require direct business-key reads in the startup path;
- Feishu config and exit log paths receive explicit startup config;
- `runtime.launch --config <path>` supports an explicit TOML file and dry-run provenance reporting.

Legacy module-local environment readers remain migration debt and are not claimed closed by this tranche.

## Static debt ratchet

`scripts/audit_runtime_env.py` performs AST-only inventory and never reads environment values. `tests/unit/test_runtime_env_access_gate.py` freezes the reviewed signature/count baseline: old access can disappear, but a new direct `os.environ` / `os.getenv` signature or an increased count fails the Gate until explicitly reviewed.

Using the same scanner on base `6d04158f` and this candidate:

| metric | base | candidate | delta |
| --- | ---: | ---: | ---: |
| direct/bulk env access nodes | 239 | 190 | -49 |
| unique keys/bulk markers | 146 | 105 | -41 |
| source files containing access | 62 | 62 | 0 |
| import-time access nodes | 40 | 40 | 0 |

The unchanged import-time count is deliberate evidence that more migration remains; the Gate prevents that debt from growing silently.

## Qualification evidence

- typed TOML precedence / strict schema / secret rejection / immutability / explicit mapping tests: PASS;
- Web + Feishu + adjacent config/runtime regression matrix: PASS;
- current legacy non-secret config projected into a temporary `runtime.toml`: 9 present schema fields, 0 effective-value mismatches, 0 secret fields written;
- Ruff / Pyright / `git diff --check`: required before commit;
- staged security scan: required before commit.

## Promotion boundary

This commit does not create a live workspace `runtime.toml`, restart services, deploy, push or alter the currently running model process. Promotion is a separate checkpoint: generate the local non-secret `runtime.toml`, compare the effective manifest, then restart/canary only with explicit deployment authorization.
