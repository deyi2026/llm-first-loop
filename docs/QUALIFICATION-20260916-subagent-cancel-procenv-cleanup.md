# Qualification — SubAgent cancelled-session index + proc-version env isolation

Date: 2026-09-16

## Scope and exact identity

- Base: `fb8da1774a9e96952a3c027f18df2b08b74e1b54` (`lfl/main` at qualification start).
- Production fix commit: `a585f981b102b39babf80fbf81c1d392b1040f5d` — `fix(subagent): archive durably cancelled child sessions`.
- Test-harness isolation commit: `af8a41e33eaa9e7cee79492c1bcc69ad2efa2ae6` — `test(runtime): isolate proc version source workspace`.
- This review line does not change LFRT authority, provider routing, Web/Feishu startup, 8901, secrets, or persistent application schemas.

## Problem 1 — cancelled SubAgent remained visible as active

Observed production-shaped state had already reached durable `subagent.generation.released` and `subagent.terminal` with no surviving worker, but the child Session JSON retained `status="active"`.

`Session.status` is intentionally an `active|archived` visibility lifecycle, not the SubAgent execution-outcome authority. The exact execution outcome remains the durable topology/EventStore record. Therefore the fix does **not** add `cancelled` or `terminal` to the Session schema.

The narrow implementation in `SubAgentRunner._finalize_child()` archives the child Session only when all of the following are mechanically true:

1. the terminal result is already durable;
2. `SubAgentTopologyJournal.terminal()` itself succeeds for the same generation;
3. the exact result outcome is `cancelled`.

Archive projection is best-effort so failure to update the visibility index cannot prevent generation cleanup. Normal completed children remain active/session-visible, preserving the existing `agent_followup` lifecycle.

## Problem 2 — `LFL_WORKSPACE_ROOT` leaked into proc-version unit fixtures

The production `proc_version` implementation correctly treats explicit `LFL_WORKSPACE_ROOT` as the dual-root source-workspace authority. The false red came from `tests/unit/test_proc_version.py`: tests that relied on `chdir()` to create Git/non-Git fixtures inherited the outer production workspace anchor.

The fix is test-only. An autouse fixture removes inherited `LFL_WORKSPACE_ROOT`; tests that explicitly exercise source-workspace behavior set it themselves. Production dual-root semantics are unchanged.

## TDD and adjacent qualification

- Cancel-path RED reproduced: durable cancelled child still loaded with `Session.status == "active"` before the implementation fix.
- Focused cancel + AgentFollowup + proc-version: 14 PASS after the fix.
- Hostile inherited `LFL_WORKSPACE_ROOT=$MIRROR_ROOT`: proc-version 7/7 PASS.
- SubAgent adjacent matrix: 106/106 PASS across core SubAgent, AgentFollowup, delivery journal/restart, topology journal/restart, settlement, restart durability, report, async engine, and run-generation ownership.
- Explicit regression proves normal completed children remain `status="active"`.
- Explicit failure-path regression proves a failed terminal-event write does not create a false durable terminal/hidden child.

## Static and repository gates

On exact committed `af8a41e33eaa9e7cee79492c1bcc69ad2efa2ae6` before this qualification-only metadata commit:

- touched Ruff: PASS;
- production Pyright: 0 errors / 0 warnings;
- `git diff --check`: PASS;
- whole-tree `scripts/git_security_scan.sh`: PASS;
- full `scripts/ci_gate.sh`: exit 0;
  - repository Ruff PASS;
  - env-pin gate: 584 test files / 0 undeclared `COMPACT_RATIO` dependents;
  - Pyright: 0 / 0 / 0;
  - tier0 PASS;
  - xdist full PASS.

The final metadata head is rechecked with the branch-wide A.5 checker and security/CI before remote review publication.

## Non-interference / production state

No deployment or restart occurred during this repair/qualification. At the final local pre-review guard:

- formal remote main remained exact `fb8da1774a9e96952a3c027f18df2b08b74e1b54`;
- canonical runtime configuration remained on the already-qualified LFRT admission authority;
- runtime manifest remained identity-consistent with formal main;
- Web and Feishu remained healthy;
- the single existing Ornith 8901 listener remained unchanged and was not restarted.

## Rollback

- Revert `a585f981...` to restore prior cancelled-child session-index behavior. No data migration is required; durable topology/EventStore history remains authoritative either way.
- Revert `af8a41e3...` to restore the prior test harness environment behavior. Production runtime behavior is unaffected by this test-only commit.
- No LFRT/runtime.toml rollback is part of this review line.

## Boundaries

This change does not attempt to:

- create a new SubAgent execution-state schema;
- archive normal completed/failed/truncated child sessions;
- change AgentFollowup task/model semantics;
- change process-version production workspace authority;
- alter RG-2/LFRT admission behavior;
- start the historical 8902 service.
