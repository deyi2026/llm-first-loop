# Runtime Config P0 + P1 Fresh-Main Qualification — 2026-09-16

## 1. Verdict scope

This record qualifies the **local fresh-main rebuild** of Runtime Config P0, P1-A,
and P1-B against formal base:

- base: `e5bfe24985efd3328592692b496241b0ed743781`
- branch: `fix/runtime-config-p1-fresh-main-20260916`
- implementation tip before this qualification record: `7ef5d962`
- execution scope: local only; no push, PR, merge, deployment, service restart, or
  second local model was used by this qualification.

The historical P1 line ending at `fa9d3b2d` is **reference material only**.  The
fresh branch intentionally excludes the unrelated R05 / memory-schema lineage
(`16d9d61a`, `5f92c0a3`, `ba23add0`, `fd42bacd`) and does not reuse the old
`031a0e9b` / `dc2a2ab8` qualification claims or the old P1-B A.5 manifest.

## 2. Fresh-main convergence boundary

Before rebuilding, the formal main and old P1 candidate were audited read-only.
Their merge-base was `96a4dce5`; formal main had 12 unique commits and the old
candidate had 10.  The whole historical candidate could not be merged safely
because its memory-schema history conflicts with main's later memory fixes.

The actual configuration-governance overlap was narrow.  Four production paths
changed on both sides and their semantics were orthogonal:

- `core/loop/engine.py`: main NonconvergenceFuse + P1 typed runtime settings;
- `factory.py`: main `AgentFollowupTool` registration + P1 settings injection;
- `subagent/runner.py`: main bounded child follow-up + P1 guidance-mode injection;
- `tools/registry.py`: main `agent_followup` tool description + P1 guidance state.

The fresh rebuild preserves both sides.  The final branch diff contains neither
`src/llm_loop/memory/store.py` nor `tests/test_memory_schema_compat.py`.

## 3. Rebuilt local commit chain

The implementation chain on top of exact `e5bfe249` is:

1. `42923a6a` — file-backed dual-root Runtime Config P0 implementation;
2. `89c8f1c9` — preserve runtime manifest source contract;
3. `2f37448d` — refresh the env-access ratchet for the fresh-main parent;
4. `dd20487a` — P1-A remove all module-import environment reads;
5. `7ef5d962` — P1-B migrate data/history/tool-runtime policy to typed settings,
   including the fresh-main NonconvergenceFuse controls.

## 4. Measured environment-access ratchet

The env inventory was recomputed from the fresh base; no old counts were reused.

| Stage | direct env accesses | module-import accesses | note |
|---|---:|---:|---|
| formal main `e5bfe249` | 245 | 40 | measured before any rebuild |
| P0 | 204 | 40 | central file-backed resolution / compatibility boundary |
| P1-A | 164 | 0 | all 40 import-time reads removed |
| P1-B | 126 | 0 | path/history/tool-runtime consumers migrated |

Final inventory facts at the implementation tip:

- `access_count=126`
- `module_import_access_count=0`
- `file_count=42`
- `unique_key_count=50`
- class key counts: bootstrap OS `2`, business config `32`, debug/test `10`,
  dynamic/bulk `2`, secret `4`.

The original P0 ratchet introduced the same seven reviewed central bulk/bootstrap
signatures as the historical implementation.  The parent count changed from the
old line because formal main added NonconvergenceFuse after that historical base.
That inherited addition was recorded rather than hidden.

## 5. Fresh-main NonconvergenceFuse adaptation

Formal main introduced three operator controls after the historical P1 branch:

- `LFL_NONCONV_FUSE_WINDOWS`
- `LFL_NONCONV_FUSE_JACCARD`
- `LFL_NONCONV_FUSE_MIN_DELTA`

They originally reached `NonconvergenceGuard.from_env()` through two dynamic
`os.environ.get()` helper signatures.  Leaving those reads as a permanent fresh-main
exception would violate the P1 direction, so P1-B now resolves them at startup into
`ToolRuntimeSettings`, exposes them through closed-schema `[tools]` Runtime TOML,
and explicitly injects them into `InterruptedCapture` / `NonconvergenceGuard`.

The old mechanical defaults and semantics are preserved: windows `3`, Jaccard
threshold `0.6` constrained to `(0, 1]`, and minimum delta tokens `16`; windows `0`
still disables the fuse.  Tests prove stale process env does not override an
explicit startup snapshot or Runtime TOML.

## 6. Tool/runtime keys removed from direct production env access

The final AST inventory contains no direct reads for the historical nine P1-B
tool/runtime keys:

`LFL_BREAKER_PRESSURE_NARROW`, `LFL_E18_HARD_STOP`, `LFL_TOOL_OCTET`, `DSH_HOME`,
`JOB_MAX_CONCURRENT`, `LFL_EVIDENCE_CAPSULE`, `LFL_TOOL_GUIDANCE`, `EXEC_SANDBOX`,
`EXEC_SANDBOX_IMAGE`.

It also contains no direct production reads for the three fresh-main
`LFL_NONCONV_FUSE_*` keys, and no direct env signature remains in
`nonconvergence_guard.py`.

## 7. Remaining boundary — deliberately not claimed complete

P1-B does **not** claim that all process environment access is retired.  The final
126 accesses are the bounded residual inventory for later phases, including P1-C,
bootstrap, secret, debug/test, provider-admin compatibility, and dynamic boundaries.
For example, `LFL_DATA_DIR` has five remaining call-time reads in
`llm/client.py` and `web/routes.py`; `DATA_DIR` has nine call-time reads across
Feishu/runtime/Web-adjacent consumers.  Those are not silently pulled into this
phase.

Secrets are not written to `runtime.toml`; secret handling remains an independent
SecretProvider/provider-admin tranche.

## 8. Local qualification evidence before the qualification commit

Focused and adjacent evidence:

- P0 / resolver / identity / manifest: `41/41 PASS` after fresh baseline review;
- P1-A focused/adjacent: `62/62 PASS`;
- P1-B initial focused config/nonconvergence/factory set: `65/65 PASS`;
- Runtime TOML + Nonconvergence explicit-policy focused rerun: `11/11 PASS`;
- all 33 P1-B changed test files plus R4/R7/R7v2/R8/R10 frozen Evidence runners:
  `473/473 PASS`.

Dirty-state repository gates at implementation tip `7ef5d962`:

- whole-tree Ruff: PASS;
- Pyright: `0 errors / 0 warnings / 0 informations`;
- env-pin gate: `579 test files / 0 undeclared COMPACT_RATIO dependents`;
- staged security scan: `75 files` PASS;
- `git diff --check`: PASS;
- tier0: PASS;
- full xdist pytest: PASS;
- guard-report: PASS;
- `scripts/ci_gate.sh`: exit `0`.

The 39 provider-URL findings printed by the test-side-effect audit are the existing
non-blocking fixture review warnings; they are not new runtime-config failures.

## 9. Main capability preservation

The fresh implementation was mechanically checked to retain main's post-divergence
capabilities:

- `engine.py` still imports/handles `NonconvergenceFuseError`;
- `factory.py` still imports/registers `AgentFollowupTool`;
- `tools/registry.py` still publishes the `agent_followup` compact description;
- dedicated NonconvergenceFuse tests pass after settings injection.

## 10. A.5 and committed-state rule

This record is accompanied by one fresh branch-wide A.5 submission manifest.  The
pre-commit review must compare the final index tree against exact base `e5bfe249`,
not merely compare the last docs commit.  The final committed branch must then rerun
the A.5 base→HEAD coverage check, whole-tree security, env inventory, and full
`scripts/ci_gate.sh` before any push or deployment is considered.

This document freezes the measured inputs and pre-commit qualification facts.  It
does not infer the later committed-state result before that result is actually run.

## 11. Rollback and next boundary

Rollback before remote publication is local branch deletion/reset to the formal base.
After publication, the review branch can be abandoned or its commits reverted; no
runtime data migration is introduced by this phase.

P1-C (LLM/Web/Feishu call-time business reads) remains **not started** on this fresh
branch.  A new human checkpoint is required before push/PR/deployment or P1-C.
