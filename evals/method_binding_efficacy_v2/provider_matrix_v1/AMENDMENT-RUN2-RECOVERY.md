# Run2 recovery amendment after operator-env contamination

The first formal execution is invalid for efficacy qualification. Rows 1-30 were mechanically healthy; rows 31-40 consumed attempt0 and attempt1 but failed before provider send because the resumed shell omitted `LFL_CANONICAL_RUNTIME_ROOT`, causing the isolated worktree to be treated as runtime root and `.env` loading to fail. Rows 41-84 were not consumed. No applicability verdict or aggregate efficacy was inspected.

Frozen SPEC rules forbid a third technical attempt and state that any unresolved mechanically unhealthy cell prevents qualification. Therefore run1 is closed as `EXECUTION_INVALID__OPERATOR_ENV_CONTAMINATION`; its matrix/status/run_data are immutable evidence and are not reused as formal efficacy observations.

A fresh run2 may reuse the already-frozen goldset, SPEC, cases, order, models, arms, thresholds, and plan exactly. It must use wholly fresh row/status/data namespaces and rerun all 84 formal cells from ordinal1. Before any O_EXCL row reservation, the run2 runner must require an explicit `LFL_CANONICAL_RUNTIME_ROOT`, require `<root>/.env`, `<root>/data/providers.local.json`, and `<root>/data/providers.json` to exist, and reject a runtime root equal to the isolated worktree. This is an execution-safety hardening only; it does not change treatment or analysis.

Run2 requires a fresh four-arm non-scored mechanical preflight before formal row1. No outcome-driven row reuse, skipping, or pooling from run1 is permitted.
