# Evidence Recoverability R12 — Tool Pipeline Compatibility Result v1

Date: 2026-08-26
Status: **PASS / SEALED**
A3: STOPPED
Production Evidence mode: unchanged/off

## Production blocker removed

R11 v1 discovered that production configuration could not start in `EVIDENCE_MODE=enforce` because `.env` enables ToolExecutionPipeline for materialization. R12 replaces the old blanket prohibition with a precise compatibility boundary.

## Compatible subset

Evidence enforce now accepts an enabled pipeline when no pre/post hooks are registered. This covers current production settings:

- `TOOL_PIPELINE_ENABLED=1`
- `TOOL_MATERIALIZE_ENABLED=1`
- `TOOL_GUARD_ENABLED=0`

Materialization and monotonic guard already execute before source resolution / Evidence capture, so no capture-order change was needed.

## Fail-closed hook boundary

`ToolExecutionPipeline.lock_for_evidence_enforce()` rejects pipelines carrying pre or post hooks. After an Evidence-compatible pipeline is accepted, future `add_pre_hook` or `add_post_hook` raises immediately. `set_guard()` remains allowed.

This preserves the unresolved safety boundary: pipeline result replacement still cannot mutate model-visible Evidence projection/capsules after capture policy.

## Assembly invariants

Both orders are supported and enforce the same lock:

- enforcer -> pipeline;
- pipeline -> enforcer.

Off/shadow pipeline behavior and existing waterfall APIs remain unchanged.

## Verification

- R12 new focused tests: **5/5 PASS**.
- Existing pipeline integration/waterfall tests: **26/26 PASS**.
- Evidence focused tests: **33/33 PASS**.
- broader Evidence+pipeline suite: **PASS**.
- targeted Ruff: **PASS**.
- targeted Pyright: **0 errors / 0 warnings**.
- R0 aggregate: **12/12 PASS**.
- real Web startup smoke with current production `.env` pipeline flags + subprocess `EVIDENCE_MODE=enforce`: `/health` **OK**, no provider request sent.
- full repository regression excluding only already-stopped A3 development test: **FULL_REPO_EXIT=0 / 100% PASS**.

R12 removes the real production activation blocker found by R11 v1 without weakening post-result mutation safety.
