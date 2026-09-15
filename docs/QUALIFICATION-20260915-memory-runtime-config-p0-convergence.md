# Memory + Runtime Config P0 Convergence Qualification

Date: 2026-09-15

## Verdict

**Local convergence candidate: PASS, ready for a human-authorized remote-review/deployment decision.**

This candidate combines the currently deployed memory-schema/read-recovery line with the separately qualified Runtime Config P0 line. It has not been pushed as a convergence ref, merged to main, deployed, or used to create a live `runtime.toml`.

## Exact lineage

Common base:

- official `lfl/main`: `96a4dce50c2dcaa0509780e1ff30929d6ca9cc8f`

Current deployed memory side:

- `16d9d61a` — exact-read recovery mechanically resumable
- `5f92c0a3` — R05 governance fold
- `ba23add0` — R05 rescope after main advance
- `fd42bacd1ae3440dca3bf725078dbb8bf319d3af` — memory future-schema fail-closed

Runtime Config P0 source line:

- `fa2923ce08b2a90aa887b1fcd1e62e19fa38c0c7`
- `719a041e`
- `e54f22f0da9e3e53e135b922e097000a835a18b7`

Convergence replay on exact `fd42bacd`:

- `b4c7003c` — replay of `fa2923ce`
- `5758f395` — replay of `719a041e`
- `031a0e9bb19cb613c9e9e6ce4ebf11bb419a3d1e` — replay of `e54f22f0`

Each replay commit has the same stable patch-id as its P0 source commit. The fd42 side changes 12 paths and the P0 side changes 12 paths; their path intersection is zero and pre-replay `merge-tree` contained no conflict markers.

All 12 fd42-side path blobs were verified byte-identical at convergence HEAD after the replay.

## P0 remote anchor

The independent P0 review ref already exists and is green:

- `review/runtime-config-p0-main-20260915` -> exact `e54f22f0da9e3e53e135b922e097000a835a18b7`
- GitHub Actions push run `34986100932`: **completed / success**
- security job: SUCCESS
- pytest + Ruff + Pyright job: SUCCESS
- nightly real-LLM job: expected SKIPPED on push
- official `main` remained `96a4dce5`

The convergence line itself has not yet been pushed.

## Combined focused qualification

The same convergence candidate passed the combined affected-owner suite covering:

- memory phase 2 / phase 3 RRF / phase 5 entity;
- memory schema compatibility / version / concurrent write / extract;
- fd42 evidence enforcement, phase 4, phase 5, source resolution and tool-result factualization;
- Runtime Config P0, env-access ratchet, resolver, identity and manifest.

The corrected focused run reached 100% and exited 0.

## Current production memory compatibility

A read-only copy of the live memory index was loaded by the convergence candidate:

- entries: **1483**
- unique IDs: **1483**
- entries with non-empty `observation_history`: **6**
- live index SHA256 at qualification: `b98a00741f0b56da997283b13f69598a90757135f1e59235582685a5ae9c79a6`

A separate future-schema copy was injected with `future_field_v100`:

- constructor entered fd42 schema-lock state;
- diagnostic named the unknown field;
- `_save()` raised `MemorySchemaMismatchError`;
- file bytes remained unchanged;
- no false `index.corrupt.json` backup was created.

The live production index was never modified by this qualification.

## Runtime Config staged-canary equivalence

No live `runtime.toml` exists at the canonical runtime root during this qualification.

A staged, owner-only `0600` file was created at:

`/tmp/lfl-runtime-config-canary-031a0e9b.toml`

Staged-file SHA256:

`7f7948389565f8149bfc0c624cd885d760181685919c60c1c5b5d8cb4d83e1b1`

It contains only the **10** currently populated, schema-covered non-secret business fields mechanically projected from the canonical legacy effective state.

Validation:

- projected non-secret fields: **10**
- secret fields written: **0**
- full effective values under staged TOML + canonical `.env` fallback vs current legacy effective state: **exactly equal**
- source changes: only the 10 projected fields, each becoming `runtime_toml`
- real `python -m llm_loop.runtime.launch web --config <stage> --dry-run`: rc=0
- dual-root identity: valid
- secret plaintext in dry-run stdout/stderr: **not present**

This is a staging artifact only. It has not been copied to the canonical runtime root.

## WebUI qualification

The convergence WebUI source is byte-identical to fd42.

Using the canonical dependency tree temporarily:

- Vitest: **22 files / 137 tests PASS**
- `tsc -b && vite build`: PASS
- build artifact count: 63 files

A first aggregate calculation was found to be path-dependent because it hashed `shasum` output containing absolute paths. The qualification therefore uses a normalized manifest of `relative_path + file_content_sha256`.

Normalized exact-source build SHA256:

`002092d6c7dbc22d7f1c113aec067b24851dfd33ac43f28869dcbfed8126d44f`

A fresh `/tmp` build from exact fd42 source and the convergence build have the same 63-file normalized manifest and the same normalized SHA. The currently serving fd42 worktree build artifact was not modified during this comparison.

## Full committed-state engineering gate

Exact code HEAD `031a0e9bb19cb613c9e9e6ce4ebf11bb419a3d1e` passed:

- whole-tree security scan: PASS
- `git diff --check`: PASS
- Ruff full repository: PASS
- env-pin declaration gate: **574 files / 0 undeclared**
- Pyright `src`: **0 errors / 0 warnings / 0 information**
- tier0: PASS
- full xdist non-real-LLM gate: PASS
- `scripts/ci_gate.sh`: **rc=0**

The clean linked worktree used only temporary canonical `.venv` and byte-identical `data/providers.json` fixtures; they were deleted after the gate.

## Live runtime remained unchanged

During convergence qualification:

- unique Ornith 8901 remained PID `52430`;
- Web remained PID `4483`, runtime identity exact `fd42bacd...`;
- Feishu remained PID `98365`;
- no live `runtime.toml` was written;
- no Web / Feishu / 8901 restart was performed.

## Decision boundary

The candidate is locally qualified for the next controlled step, but that next step is intentionally not automatic.

Before any of the following, require a human checkpoint:

- pushing the convergence line to a remote review ref;
- writing canonical `<runtime_root>/runtime.toml`;
- restarting Web or Feishu onto the convergence code root;
- merging any line to main.

The rollback procedure is frozen separately in `docs/RUNBOOK-20260915-runtime-config-canary.md`.
