# Runtime Config P0 Qualification — current main rebuild

Date: 2026-09-15

## Verdict

**P0 local committed-state: PASS.**

This qualification covers only the non-secret file-backed runtime configuration core on the current official main baseline. It does **not** deploy a live `runtime.toml`, migrate provider-admin writes, migrate credentials, retire `.env`, or restart any running service.

## Exact lineage

- Baseline: `lfl/main@96a4dce50c2dcaa0509780e1ff30929d6ca9cc8f`
- Core implementation: `fa2923ce08b2a90aa887b1fcd1e62e19fa38c0c7`
- Frozen-manifest compatibility follow-up: `719a041e`
- Branch: `fix/runtime-config-p0-main-20260915`

The implementation was rebuilt on the current dual-root main. The older RuntimeConfig v1 commit `591e55e3` was used only as a content/design reference and was not cherry-picked wholesale because it is based on `6d04158f` and conflicts with the current main in identity/resolver tests and dual-root semantics.

## P0 contract

1. `LFL_WORKSPACE_ROOT` identifies the exact source checkout (`code_root`).
2. `LFL_RUNTIME_ROOT` identifies the stable operational/config root (`runtime_root`).
3. Default non-secret business configuration file is `<runtime_root>/runtime.toml`.
4. Precedence is: CLI > explicit shell override (`LFL_ALLOW_RUNTIME_OVERRIDE=1`) > `runtime.toml` > legacy `.env` > launch defaults.
5. `runtime.toml` is typed and closed-schema; unknown fields and secret-like fields fail closed.
6. Missing default `runtime.toml` preserves legacy `.env` compatibility. An explicitly requested missing config path fails closed.
7. `RuntimeConfig` is a frozen snapshot with provenance; `values`, `sources`, and ignored-shell facts cannot be mutated through the public snapshot.
8. `load_settings(mapping)` accepts an explicit configuration snapshot without mutating process-global `os.environ`.
9. `apply_to_environ()` remains a migration compatibility boundary only; it is not the target API for new business logic.
10. Runtime manifest records the effective config path, source provenance, and config hash without exposing secret plaintext.

## TDD / focused evidence

The new P0 contract was written RED first. Initial collection failed because current main had no `RuntimeConfig`, as expected. After implementation, the following focused contracts pass:

- dual-root resolution from `runtime_root/runtime.toml` while the code worktree contains no `.env` or `runtime.toml`;
- TOML precedence over legacy `.env` and stale inherited shell business values;
- shell override only with explicit opt-in;
- secret-like and unknown TOML fields rejected;
- immutable RuntimeConfig snapshot;
- explicit `load_settings(mapping)` without ambient-env mutation;
- explicit missing config path rejected;
- launch `--dry-run` uses dual-root TOML, reports provenance, keeps identity valid, and does not print the secret sentinel;
- runtime manifest / runtime identity / existing resolver contracts remain compatible.

Focused plus adjacent suites covering runtime resolver, identity, manifest, runtime paths, config, Feishu config and Web exit-log all passed before commit.

## Current `.env` -> temporary TOML equivalence

The canonical current `.env` was read only through the resolver. Only non-secret fields already represented by the P0 TOML schema were mechanically projected to a temporary `runtime.toml`; no secret field was written.

- schema-covered current non-secret fields projected: **10**
- parser fields recovered: **10**
- effective-value mismatches: **0**
- secret-like fields written to TOML: **0**

The compared keys were the currently populated schema subset only. P0 does not claim the rest of the legacy `.env` has been migrated.

## Env-access ratchet

The same AST scanner was run against the exact main parent and the P0 candidate:

| State | direct/bulk env accesses | files | import-time accesses |
|---|---:|---:|---:|
| `main@96a4dce5` | 243 | 63 | 40 |
| P0 candidate | 202 | 63 | 40 |

Net change: **-41 accesses**.

Seven new signatures relative to the parent were explicitly reviewed and frozen in `tests/fixtures/runtime_env_access_baseline.json`. They are all centralized injected-env / legacy projection / bootstrap boundaries in `runtime.identity` and `runtime.resolver`; none is a new direct business-key reader and none uses the rejected `business_value()` call-time pattern.

The one-way AST Gate is now committed: future direct process-env access may decrease, but a new signature or larger count requires an explicit reviewed baseline change.

Import-time env access remains 40 in P0. Eliminating those belongs to P1 subsystem migration and is intentionally not claimed here.

## Frozen contract regression caught by full CI

The first committed-state full gate on `fa2923ce` found one real compatibility regression:

- frozen Agent Qualification Envelope required the existing manifest contract anchor `"config_sources": ec.sources`;
- the first P0 implementation used `dict(ec.sources)` to make the frozen mapping JSON-serializable.

This was not waived and the frozen contract was not edited. Follow-up `719a041e` introduced a JSON-serializable read-only dict snapshot for `sources`, restored the real manifest expression, and added mutation + JSON round-trip coverage. The focused runtime-config/runtime-manifest/envelope set then passed 34/34.

## Final committed-state Gate

Exact `719a041e` was qualified from a clean linked worktree using the candidate source tree. The canonical project virtualenv was symlinked temporarily and the gitignored `data/providers.json` fixture was copied temporarily with byte-identical SHA256 to satisfy existing Browser SMC tests; both were removed after the run.

Final `scripts/ci_gate.sh` result: **rc=0**.

- Ruff full repository: PASS
- env-pin declaration gate: **573 files scanned / 0 undeclared**
- Pyright `src`: **0 errors / 0 warnings / 0 information**
- tier0: PASS
- full xdist non-real-LLM gate: PASS
- git security scan on implementation/follow-up commits: PASS
- post-gate worktree: clean

## Runtime boundary

P0 was not deployed. Web, Feishu, and the unique Ornith 8901 service were not restarted or replaced during this work.

Therefore current user-facing runtime behavior remains on the previously qualified production identities. P0 is a **local qualified candidate**, not yet a live configuration migration.

## Out of scope / next phases

- **P1:** migrate direct/import-time business config reads subsystem by subsystem toward explicit RuntimeConfig/Settings injection; target import-time business env reads = 0 while retaining only reviewed bootstrap/secret/debug/child-process boundaries.
- **P2:** provider-admin atomic writes to `runtime.toml` / `providers.json` as a separate change.
- **P3:** independent SecretProvider for credentials; do not place secrets in `runtime.toml`.
- **P4:** retire `.env` from normal runtime configuration only after P1-P3 qualification, then simplify restart-script `source/unset` compatibility logic.

No push, PR, merge, deployment, or service restart is authorized by this P0 report.
