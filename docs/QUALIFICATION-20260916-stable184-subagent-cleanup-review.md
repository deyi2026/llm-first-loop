# Qualification — stable-184 SubAgent cancellation cleanup review

Date: 2026-09-16

## Scope and exact identities

This review line is intentionally derived from the frozen production stable point `184f6cc6b333612f2e6bf8b3346bc6798ecd6b7a` rather than rebuilt from a different historical checkout.

- Frozen production base: `184f6cc6b333612f2e6bf8b3346bc6798ecd6b7a`.
- Stable-freeze evidence: `data/audit/stable-freeze-184f6cc6-20260916T1215.json` (runtime data, not committed by this review line).
- Production fix commit on the 184-derived line: `04294fb1e7487e02656ab36f8e30fbf49096d67f` — `fix(subagent): archive durably cancelled child sessions`.
- Test-harness isolation commit on the 184-derived line: `9fb66650501b859efd8da7954fae9b4889aeab2b` — `test(runtime): isolate proc version source workspace`.
- Formal remote `lfl/main` at fresh-review preparation: `fe209380a13b20e69bdb2e2ebdd17dc77c31fd40`.

Important convergence fact: current formal main already contains patch-identical equivalents (`a585f981` / `af8a41e3`) plus the earlier qualification record. The four implementation/test blobs on `9fb66650` are byte-identical to formal main. Therefore this fresh review does **not** claim a new runtime delta relative to current main; it qualifies the exact 184-derived lineage requested for stable-point convergence and provides fresh mechanical review metadata.

## Defect reproduced on exact 184f

Before applying the fix on the 184-derived line, the production-shaped cancellation regression was reproduced deterministically:

- the child had a durable `cancelled` SubAgent terminal outcome;
- the child worker had stopped and no late tool action executed;
- nevertheless `Session.status` remained `active`, so the default active-session index still advertised the child.

`Session.status` remains an `active|archived` visibility lifecycle. The exact execution outcome remains authoritative in the durable SubAgent topology/EventStore; this review does not create a second execution-state schema.

## Narrow implementation

`SubAgentRunner._finalize_child()` archives a child Session only after all mechanical prerequisites hold:

1. the exact child result is durable;
2. `SubAgentTopologyJournal.terminal()` successfully persists the same-generation terminal;
3. the exact durable result outcome is `cancelled`.

The archive projection is best-effort. If visibility projection fails, generation cleanup still completes and durable topology truth remains authoritative. Normal completed children remain active/session-visible so existing `agent_followup` behavior is preserved.

The second commit changes tests only: `tests/unit/test_proc_version.py` removes inherited `LFL_WORKSPACE_ROOT` from unit Git fixtures unless a test deliberately sets it. Production dual-root workspace authority is unchanged.

## Patch identity and convergence

The 184-derived commits are content-equivalent to the already-reviewed formal-main commits:

- `04294fb1` and `a585f981` have the same stable patch-id: `43639c6baf944fba5d4f3df62c6f46a20500ae53`.
- `9fb66650` and `af8a41e3` have the same stable patch-id: `4fe3fe914fe043346094b17530fd96ff3f8983d4`.
- Exact blobs match current formal main for:
  - `src/llm_loop/subagent/runner.py`;
  - `tests/unit/test_agent_followup.py`;
  - `tests/unit/test_subagent.py`;
  - `tests/unit/test_proc_version.py`.

This distinction matters for review: GitHub/A.5 compares the PR base...head changed-path set mechanically from the merge-base, while semantic review must also know that current main independently reached the same file contents on its post-184 lineage.

## Deterministic qualification on the 184-derived candidate

On exact committed `9fb66650501b859efd8da7954fae9b4889aeab2b`:

- RED before fix: cancelled child loaded as `status="active"` — reproduced.
- Exact cancel/archive regression + completed-child visibility regression: 2/2 PASS.
- Hostile inherited `LFL_WORKSPACE_ROOT` proc-version suite: 7/7 PASS.
- SubAgent / AgentFollowup / delivery / topology / restart / settlement / P3 ownership adjacent matrix: 152/152 PASS.
- Ruff: PASS.
- Production Pyright: 0 errors / 0 warnings / 0 informations.
- `py_compile`: PASS.
- `git diff --check`: PASS.
- Whole-tree security scan: 1908 tracked files PASS.
- Full `scripts/ci_gate.sh`: exit 0:
  - repository Ruff PASS;
  - env-pin gate 584 test files / 0 undeclared `COMPACT_RATIO` dependents;
  - Pyright 0 / 0 / 0;
  - tier0 PASS;
  - xdist full PASS.

The final metadata head is additionally checked with A.5 exact base...head coverage and repository security before ordinary review publication. Remote PR checks are authoritative for the published review ref.

## P2 non-duplication note

A separate content audit established that historical P2 commits `5912acc2` and `1daefa04` carry identical production patches; `1daefa04` is already in the 184 lineage and later P6 further removed shared last-session fallbacks. No P2 code is added by this review line.

## Production non-interference

During this fresh review preparation, production remains on the frozen exact `184f6cc6` runtime:

- Web and Feishu are not restarted by qualification generation;
- the single existing Ornith 8901 service is not restarted or duplicated;
- `runtime.toml` / LFRT admission authority is not changed;
- no provider registry, secret, ruleset, tag, or persistent application schema is changed.

Publication of a review ref and PR does not itself authorize deployment or main mutation. Those remain a separate owner decision after remote checks are green.

## Rollback and boundaries

The 184-derived code commits can be reverted independently without data migration. Durable topology/EventStore history remains valid. Reverting the proc-version test isolation has no production runtime effect.

This review does not:

- add `cancelled` to the Session schema;
- archive normal completed children;
- change SubAgent task/model semantics;
- weaken production `LFL_WORKSPACE_ROOT` dual-root authority;
- change RG-2/LFRT admission behavior;
- restart Web, Feishu, or 8901;
- claim that duplicate commit identity implies a new runtime difference from current formal main.
