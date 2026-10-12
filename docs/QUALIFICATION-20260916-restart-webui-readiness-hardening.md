# Qualification — restart Web V2 artifact/readiness hardening

Date: 2026-09-16
Base: `c5772baa3b0617289c6087564e149f7f7d77d0db`
Branch: `fix/restart-webui-readiness-c577-20260916`

## 1. Problem reproduced

The production `c5772baa` dual-root restart returned `rc=0`, bound Web on 8903, and returned `200` from `/auth/status`, while `/ui/v2/` was `404` and the user could not use the Web UI.

The failure was mechanical and deterministic:

- `webui/dist/` is intentionally ignored by Git, so a fresh linked code worktree can lack the build artifact even when its tracked source tree is exact.
- `llm_loop.web.create_app()` mounts `/ui/v2` only when the resolved Web V2 dist directory exists.
- `restart_mirror.sh` previously declared Web ready from `/auth/status` alone.

The stable recovery used a byte-identical, previously qualified dist only after proving the tracked `webui` tree was identical between the target and stable code versions. This qualification hardens the restart contract so the same false-success state cannot recur silently.

## 2. Narrow implementation

Only `scripts/restart_mirror.sh` changes production/operator behavior.

1. `_webui_artifact_preflight` runs for `web` and `all` **before any existing Web process is stopped**.
2. It resolves the same operator override surface used by the Web process: `UI_V2_DIR` when present, otherwise `<code-root>/webui/dist`.
3. It requires `index.html` and mechanically parses local `/ui/v2/...` `src`/`href` references, rejecting a partial artifact when any referenced file is absent.
4. Failure is fail-closed with an actionable `npm run build` instruction and a persisted `webui_artifact_preflight_failed` restart receipt.
5. `_start_web` now requires both `/auth/status=200` and `/ui/v2/` returning a 2xx/3xx response before reporting Web ready. Backend-ready/UI-unavailable becomes an explicit restart failure.

No default automatic build was added. A restart path must not silently invoke npm/network/dependency resolution or mutate a qualified code root. No automatic rollback was added. Existing rollback/operator control remains unchanged.

## 3. TDD evidence

RED was captured before the implementation:

- no WebUI artifact preflight existed;
- `web`/`all` had no fail-fast artifact check before `_stop_web`;
- `_start_web` considered `/auth/status` alone sufficient.

Three initial deterministic RED assertions failed exactly on those missing contracts.

GREEN coverage now includes:

- static ordering: artifact preflight precedes long-task precheck and any Web stop in both `web` and `all`;
- artifact contract: `UI_V2_DIR` / code-root default, `index.html`, and local referenced assets;
- readiness contract: `/auth/status` plus `/ui/v2/`;
- dynamic linked-worktree fixture: missing dist exits `1` before restart work and persists `detail=webui_artifact_preflight_failed`;
- dynamic partial-dist fixture: existing index with a missing hashed asset fails preflight.

Restart-focused/adjacent matrix:

- `tests/scripts/test_restart_mirror_hardening.py`
- `tests/unit/test_restart_mirror_script.py`
- `tests/unit/test_runtime_startup_sot.py`

Result: **24/24 PASS**.

## 4. Repository gates

Pre-commit candidate validation:

- `bash -n scripts/restart_mirror.sh` — PASS
- focused restart matrix — **24/24 PASS**
- `scripts/ci_gate.sh` — **PASS**
  - full Ruff gate: zero violations
  - env-pin: **585 files / 0 undeclared**
  - Pyright: **0 errors / 0 warnings / 0 informations**
  - tier0: PASS
  - full xdist pytest: PASS
  - architecture guard: PASS
- `git diff --check` — PASS

The existing test-side-effect audit continues to report 41 low-risk provider-URL review warnings; this change neither adds a real provider call nor changes that warning baseline.

- staged security scan: **PASS (6 files)**
- staged A.5 architecture submission gate: **PASS** (`changed_paths=6`, `components=5`, `controls=1`)

These staged results cover the complete candidate path set assembled with this qualification and submission metadata.

## 5. Operator manual

`docs/LFL-restart-guide.md` is now part of the candidate instead of an untracked local note. It records:

- the `webui/dist` linked-worktree lifecycle hazard;
- the narrow conditions under which a previously qualified dist may be mechanically reused;
- the requirement that `/auth/status=200` is insufficient by itself;
- `/ui/v2/` and login/UI asset post-restart verification;
- the `c5772baa` incident/recovery chain.

Before tracking it, two machine-specific absolute paths were replaced with portable `<mirror-runtime-root>` placeholders. No credential value or private machine path is intentionally included.

## 6. Authority / non-interference

This change is mechanical deployment safety only.

- It does not add model-visible prompt text, a tool, provider schema, task strategy, evidence relevance judgment, completion judgment, or Agent authority.
- It reuses the existing restart lifecycle as the sole owner of service stop/start/readiness.
- It does not modify LFRT/8901, Feishu lifecycle semantics, runtime config precedence, provider selection, or durable application data.
- Missing/partial Web V2 artifacts fail before stopping the current Web service.
- A post-start backend-ready/UI-unavailable state returns restart failure instead of a false success.

Production `c5772baa` Web/Feishu/8901 remained untouched while this candidate was implemented and tested in an isolated linked worktree.

## 7. Rollback

Revert the restart-hardening commit. No schema migration, data conversion, provider change, model restart, or artifact rewrite is required. The already frozen `c5772baa` production stable point remains the deployment rollback reference until a later qualified release replaces it.
