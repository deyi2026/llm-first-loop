# M1-G2 Gate Closure — structured T02 effect receipt

- Date: 2026-09-15
- Historical REWORK audit: `942747de9e602bb566a61fcf8c72c634f384def2`
- Scorer/runner repair: `f633eff13c59c3623862a660b3bfd30029bea1ec`
- Parent measurement candidate: `fd56884d0036c5170172d4a7536a9488e2166490`
- Physical model service: existing single Ornith 8901, PID `52430` throughout
- G1 Scorer: **PASS**
- M1 phase exit: **PASS_WITH_SCOPE_LIMITS**
- G4 performance: **NOT_EVALUATED**
- M2: **NOT_STARTED**

## 1. Closure summary

The P0 measurement-semantic defect recorded by the historical Gate report is closed without changing production tool semantics and without parsing arbitrary tool-result prose.

T02 requires one declared transient failure followed by the same check succeeding. Real agents can execute `python3 gen.py; echo EXIT=$?`, causing the outer shell/tool receipt to appear successful even though the inner `gen.py` process exits 1. Treating `ToolResult.status` as the task effect therefore loses the fact the benchmark actually needs.

The repair keeps the layers separate:

1. production tool status keeps its existing meaning;
2. the benchmark owns a task-scoped process-exit observer for T02;
3. the observer emits only closed mechanical fields: `schema/check_id/target/scope/attempt/exit_code`;
4. the scorer counts the expected failure from exact `check_id + exit_code` and confirms repair only when the same `check_id/target/scope` later exits 0.

No model-visible T02 prompt, setup program, verifier, timeout, interrupt setting, or `first_tools` field changed from `fd56884d`. `telemetry.extract_raw()` is byte-identical to the parent candidate.

## 2. Exact implementation boundary

Commit `f633eff1` changes exactly six `evals/pilot/` files and no `src/llm_loop` production file:

- `analyze.py`
- `run_pilot.py`
- `tasks.py`
- `telemetry.py`
- `test_g1_fixes.py`
- `test_t02_effect_receipt.py`

The probe lives outside each task workspace under the run-root control area, so ordinary task file discovery cannot see it. The shim delegates to the real `python3`, records only the child exit fact, preserves the child exit code, and never classifies stdout/stderr.

## 3. Deterministic qualification

The real-shape fixture intentionally uses an outer shell whose final return code is 0 while the first inner `gen.py` exits 1. Its synthetic raw tool events are all `ok=true` and contain no `transient` marker. The structured receipt still yields:

- `expected_failure_count=1`
- `confirmed_repair_count=1`
- `unexpected_failure_count=0`
- `expected_failure_unresolvable_count=0`

Negative boundaries also pass:

- missing structured receipt => unresolvable, never guessed;
- wrong inner exit code => unexpected, not promoted to the declared transient failure;
- raw tool failure plus structured expected effect => no double count;
- T01 has no effect-probe fields;
- the task workspace contains no probe artifact.

Legacy F08/A05 fixtures remain separate and green.

## 4. Committed-state engineering gate

Exact `f633eff1` committed-state results:

- deterministic T02 real-shape test: PASS;
- G1 deterministic fixtures: PASS;
- whole-tree security scan: PASS;
- Ruff full repository gate: PASS;
- env-pin gate: 562 scanned / 0 undeclared;
- Pyright `src`: 0 errors / 0 warnings / 0 information;
- tier0: PASS;
- full xdist non-real-LLM gate: PASS;
- full `scripts/ci_gate.sh`: rc=0.

A clean linked worktree lacks the gitignored canonical `data/providers.json` used by an existing Browser SMC fixture. The gate used a temporary byte-identical canonical copy, sha256 `bf463c72a8cfcd9261ed2d8c11d4f8b3d4ed37569bb4f678d50566e231e6be4e`, then deleted it. No tracked file changed.

## 5. Frozen narrow live matrix

The live closure run deliberately did not repeat the full 96-row experiment. It used the narrow matrix required by the prior Gate recommendation:

- tasks: T02 + T01 control;
- agents: LFL + Deep Agents;
- repeats: 2;
- one runner process, strict sequential execution;
- Latin-square order, seed `20260915`;
- one existing physical Ornith 8901 instance;
- execution-plan sha256: `32df564761d8c0357f1acb74df5328c0ceec90adb78a12eb9c43c66a68e20045`;
- freeze sha256: `9eac82d93d77ad8e1aa32e9e45d96288c3833a69a8d58c9f3bc39ce97d6409f2`.

Valid-run artifacts:

| Artifact | sha256 |
|---|---|
| manifest.json | `e9340f657641e104fd3571f36cf6cc48bd422b6c82ec6668ef548dd0b79d0fd8` |
| results.jsonl | `910c1edfd3a31b9e771df56135cbc19f5f3db2e4810a27a8907de4dd4338c20f` |
| summary.md | `e97ea69aa98702d536d9293e13e7c335bb36b2272f1ae8fba18feab8149ece85` |
| invocations.jsonl | `4131b2c1c6df26ba5cd82436926e102e65d66382c157039c9a904e38f18667df` |

The first attempted narrow run is preserved separately as infrastructure-invalid evidence, not overwritten. Its LFL rows exited before any model call because the invocation omitted the explicit local LLM environment contract used by the formal M1 runner. Its results sha256 is `44611f7d7956b8f24ba83cf8783451d9aa49e4e30edbb7b7959a8d130776d618`. DA rows from that invalid attempt are not used for Gate closure.

The valid rerun restored the formal local contract and canonical provider fixture while keeping `PYTHONPATH` pinned to exact `f633/src`. Plan hash and freeze hash were identical to the pre-run freeze before execution.

## 6. Live results

All eight valid rows passed:

| Task | LFL | DA | Total |
|---|---:|---:|---:|
| T02 transient retry | 2/2 | 2/2 | **4/4** |
| T01 control | 2/2 | 2/2 | **4/4** |
| **Total** | **4/4** | **4/4** | **8/8** |

Every T02 row contains `task_effects_status=ok`, first observed effect exit 1, and later same-check exit 0. Exact `f633` scoring is identical on all four rows:

- `expected_failure_count=1`
- `confirmed_repair_count=1`
- `unexpected_failure_count=0`
- `expected_failure_unresolvable_count=0`

Every T01 control row is PASS and contains no task-effect fields. The 8901 listener remained PID 52430 before and after the run. Web/Feishu were not restarted or modified.

## 7. Scope limits that remain

### 7.1 Historical event limits stay historical

Formal108/frozen112 cannot be retroactively given task-effect receipts that were never recorded. Missing historical facts remain unknown/unresolvable; no synthetic history is invented.

### 7.2 Performance remains outside this Gate

The previous baseline/candidate 48-row arms overlapped while sharing 8901, so their latency/cache/queue figures remain **INVALID_FOR_GATE / DIAGNOSTIC_ONLY**. This narrow closure run is intentionally too small and is not used to manufacture a performance threshold. G4 is **NOT_EVALUATED**, not PASS.

### 7.3 T02 FCR directness is not a closure claim

Under the existing frozen `first_tools=[read]` oracle, all four T02 rows have first-tool selection false while their first calls are mechanically executable. This repair did not change that oracle and makes no T02 directness-improvement claim. If T02 directness becomes a decision KPI, that task-oracle semantic should be audited separately.

## 8. Final Gate matrix

| Gate item | Verdict | Boundary |
|---|---|---|
| Oracle vocabulary / startup validation | **PASS** | deterministic valid + poison cases |
| Call identity / result completeness | **PASS** | retained from `fd56884d` qualification |
| Old 200-char silent truncation repair | **PASS** | retained F08/A05 evidence |
| T02 structured expected failure | **PASS** | real 4/4; exact inner exit 1 |
| T02 confirmed repair association | **PASS** | real 4/4; same check/target/scope later exit 0 |
| Missing/wrong evidence fail-closed | **PASS** | deterministic negative cases |
| T01 non-regression control | **PASS** | real 4/4, no effect fields |
| Committed-state engineering quality | **PASS** | full ci_gate rc=0 |
| Historical fixed-event rescoring | **PASS_WITH_SCOPE_LIMIT** | old missing effect facts remain unknown |
| Performance/cache/latency | **NOT_EVALUATED** | prior overlap remains diagnostic-only |
| **G1 Scorer** | **PASS** | targeted measurement defects closed with positive/negative + real T02 evidence |
| **M1 phase exit** | **PASS_WITH_SCOPE_LIMITS** | required M1 artifacts exist; no G4/G2/G3 overclaim |

## 9. Next boundary

M1 is now at a valid phase boundary. This report does not authorize or start M2, remote push, merge, deployment, model restart, or performance qualification.

The next owner decision should choose whether to preserve/push exact `f633eff1` plus this closure report to an independent review ref, enter M2 from the frozen M1 package, or separately audit the T02 FCR directness oracle before using directness as a decision metric.
