# Runtime Environment Access Inventory — 2026-09-14

## Scope

AST-only inventory of direct `os.environ` / `os.getenv` access under `src/`. It records key names and source ownership only; it never reads or persists environment values. The same scanner was run against implementation base `6d04158f` and the current Config-SoT candidate.

| metric | base `6d04158f` | current candidate | delta |
| --- | ---: | ---: | ---: |
| direct/bulk access nodes | 239 | 190 | -49 |
| unique keys/bulk markers | 146 | 105 | -41 |
| files with direct access | 62 | 62 | +0 |
| import-time access nodes | 40 | 40 | +0 |

Current key classes: `{'bootstrap_os': 2, 'business_config': 86, 'debug_test': 12, 'dynamic_or_bulk': 2, 'secret': 3}`. This tranche removes central Settings and Web/Feishu startup business-key reads while retaining a small number of reviewed bulk environment fallbacks at compatibility boundaries. It does **not** claim the remaining import-time/legacy debt is gone.

## Ownership classes

- `business_config`: migration debt; new direct reads are forbidden by the static ratchet.
- `secret`: credentials stay outside `runtime.toml`; consume only at explicit secret/bootstrap boundaries.
- `bootstrap_os`: process/workspace bootstrap facts; environment remains an allowed boundary mechanism.
- `debug_test`: diagnostics/qualification toggles; keep isolated from durable business configuration.
- `dynamic_or_bulk`: compatibility/bootstrap boundary only; each new signature requires explicit review and baseline change.

## Migration rule

The JSON inventory is the reviewed one-way CI baseline. Existing legacy accesses may disappear without updating it. Any new signature or increased count fails the static Gate. `runtime.toml` v1 owns model/base URL (non-secret), reasoning mode/effort, LLM budgets/protocol, DATA_DIR/LFL_DATA_DIR as separate anchors, history budget, runtime identity/wire mode, Web bind host/port, summary mode, tool-schema lazy mode and DSH home. Provider credentials remain secret-boundary inputs; provider registry structure remains in `providers*.json`.
