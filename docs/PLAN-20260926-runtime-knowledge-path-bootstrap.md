# Runtime Knowledge path bootstrap parity

Date: 2026-09-26

## Status

**Isolated qualification: PASS. Production deployment: NOT YET AUTHORIZED.**

Base production generation: 117

Base head: `22ff47ce6f56acf103066ce65d6baf73ec549406`

## Problem

The generation-117 Learning retry recovery fixed cross-workspace Memory extraction, and the exhausted Memory job recovered successfully on its single repair attempt. The pre-existing Reflection job then retried naturally and failed again on generation 117:

`PermissionError: knowledge store quarantined: mutation disabled`

The live runtime manifest simultaneously reported Knowledge `healthy` with `writes_enabled=true`.

This contradiction was mechanically reproduced in a clean child process. Runtime manifest construction hydrates Knowledge path bindings from the canonical runtime-root `.env`, while the service engine's subsequent `load_settings()` did not. In a linked worktree this caused the two paths to disagree:

- manifest: `EXPERIENCES_DIR` / `METHODS_DIR` source = `explicit_env`, healthy;
- engine: the same physical mutable stores were inferred from `DATA_DIR`, source = `data_dir_inferred`, `auto_rebind_applied=true`;
- Knowledge health therefore treated the worktree-local legacy Experience/Method trees as divergent mutable stores and quarantined writes;
- MethodStore's existing write guard correctly rejected candidate persistence.

The write guard and Knowledge health rules are not the bug and remain unchanged.

## Qualified design

`load_settings(env=None)` now gives `resolve_runtime_paths()` the same missing Knowledge path bindings that the runtime manifest already derives from the canonical runtime-root `.env`.

The fallback is deliberately narrow:

- only real process bootstrap (`env is None`) may inherit the runtime-root dotenv paths;
- explicit mapping callers remain hermetic and do not inherit host `.env`;
- only `EXPERIENCES_DIR`, `METHODS_DIR`, `METHOD_SEED_DIR`, `SKILLS_DIR`, and `DOCS_DIR` are considered;
- existing process values still win; dotenv only fills missing values;
- values are supplied only to `resolve_runtime_paths()` and are not projected back into `os.environ`;
- no MethodStore or ExperienceStore write guard is bypassed;
- no Knowledge quarantine criterion is weakened;
- runtime.toml semantic scopes are unchanged.

This makes engine path authority match manifest path authority while preserving the existing explicit-mapping qualification boundary.

## RED/GREEN evidence

Two permanent tests were added:

1. process bootstrap with `LFL_RUNTIME_ROOT/.env` path bindings must resolve Experience and Method as `explicit_env` and produce healthy/writable Knowledge;
2. `load_settings(explicit_mapping)` must remain isolated and continue to infer paths from the supplied mapping instead of reading runtime-root dotenv state.

Before the fix: 1 FAIL / 1 PASS.

After the fix: 2/2 PASS.

## Production-equivalent parity probe

Artifact: `evals/retrieval_ab/runtime-knowledge-path-bootstrap-qualification-20260926.json`

The probe runs generation-117 bootstrap semantics with Knowledge path variables removed from the child environment, then:

1. resolves and applies the current Learning RuntimeConfig;
2. calls the fixed `load_settings()`;
3. independently computes the manifest Knowledge RuntimePaths;
4. compares the two.

Result:

- engine Experience path == manifest Experience path;
- engine Method path == manifest Method path;
- both Experience sources = `explicit_env`;
- both Method sources = `explicit_env`;
- engine Knowledge = healthy / writes enabled;
- manifest Knowledge = healthy / writes enabled;
- both reason lists are empty.

The original contradiction is therefore eliminated without altering write safety.

## Regression gates

- focused bootstrap tests: 2/2 PASS;
- config / runtime manifest / Knowledge health / Knowledge preflight / runtime paths / factory / Learning / runtime-env-access adjacency: 118/118 PASS;
- runtime env-access ratchet: PASS;
- Ruff: PASS;
- Pyright: 0 errors / 0 warnings / 0 information;
- `git diff --check`: PASS.

## Current production job state

Production remains generation 117 at the base head.

- Memory retry `learn:234dda64a513`: **saved**, attempt 4, 8 entries. Closed; do not touch.
- Reflection retry `learn:e5f25020b688`: **failed**, attempt 4, `candidate_save_failed`. It is exhausted and not automatically runnable.

No further journal action should be taken until this bootstrap fix is deployed and the new Learning worker is mechanically verified healthy/writable.

## Production recovery boundary

If production deployment is authorized:

1. freeze a clean candidate commit;
2. satisfy the existing deployment invariants for the new worktree: canonical ignored `.env` dual-root Experience/Method binding; reuse the qualified WebUI artifact only if tracked WebUI bytes are unchanged;
3. run Knowledge binding/preflight and managed service-control verify;
4. CAS publish the candidate as the next desired generation;
5. restart **Learning only**;
6. verify exact candidate head and identity; Memory=1 / Method=1 / Archive=Docs=Experience=0; engine/manifest Knowledge path sources both explicit and healthy/writable; Web/Feishu PIDs, heads and scopes unchanged;
7. append exactly one `LearningJournal.mark_requeued("learn:e5f25020b688", "operator_repair_verified:knowledge_path_bootstrap")` event;
8. do not requeue the already-saved Memory job;
9. allow the Reflection repair attempt to run naturally;
10. require Reflection to end in `saved` or justified `none`, MethodStore mutation to be durable if a candidate is produced, no further automatic retry, 8765/provider/resource health normal, and Web/Feishu unaffected.

If Reflection fails again for a different current-code reason, stop and diagnose that new failure. Do not bypass Knowledge guards or mass-reset journal state.
