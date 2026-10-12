# Evidence Recoverability R1 Historical Replay Result v1

Date: 2026-08-26
Status: **PASS — historical replay gates satisfied**
Provider/model calls: **0**
Source tool executions during replay: **0**
Production activation: **NO configuration change**

## Executive result

R1 confirms the root-cause hypothesis on frozen historical traces without asking a model to interpret them.

Across 120 frozen event logs:

- tool calls: **5,419**
- same-run exact tool+args repeat instances: **226**
- repeats with any compression event between calls: **120**
- repeats where the *specific previous concrete tool-result message* was actually compressed before the repeat: **83**
- those 83 prior observations recoverable exactly from temporally replayed Evidence before the repeat: **83/83 (100%)**
- lost EvidenceRefs in this hidden-repeat cohort: **0**

The high-confidence program-amnesia bucket contains **48 repeats**. Every one is `read_file`, the previous concrete read result was hidden before the repeated call, the old observation hydrated exactly through the new Evidence layer, and the later historical repeated read returned byte-for-byte the same result.

This establishes that program-induced evidence loss was a real causal contributor to historical repeated reads. It does **not** establish that every repeat was caused by amnesia.

## Frozen inputs

- Pre-registration: `docs/RECOVERABILITY-R1-PRE-REGISTRATION-v1.md`
- Input manifest: `tests/fixtures/evidence_r1_historical_v1.json`
- Input manifest SHA-256: `271c980b7143ba9f1922bc8fb234d1f85f018c90cea4767863909d922e74ddb3`
- Frozen cohort: every `data/event_logs/*.jsonl` whose maximum event timestamp is at or before `2026-08-26T08:45:17.163758+00:00`
- Frozen session count: 120
- Frozen bytes: 66,294,228
- Spec SHA-256: `97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771`
- Design SHA-256: `95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b`

Every input log path and SHA-256 is frozen in the manifest before scoring.

## Replay mechanism

`scripts/evidence/run_r1_replay.py` replays persisted events in historical temporal order into an isolated Evidence store.

For each successful historical tool result:

1. the persisted observation is capture-written to a temporary owner-scoped Evidence ledger;
2. no original source action is run;
3. when a same-run exact tool+args repeat declaration is later encountered, the replay checks whether the previous concrete tool-result had already been compressed;
4. if a prior EvidenceRef exists, `EvidenceHydration` reads it before the repeated historical result is consumed;
5. the hydrated bytes are compared with the original persisted observation.

Network access is mechanically denied for non-UNIX sockets during replay.

## Cause classification

| Class | Count | Meaning |
|---|---:|---|
| `program_amnesia_avoidable` | **48** | Hidden prior `read_file`; exact hydration available; repeated historical read later returned identical bytes |
| `freshness_change_observed` | **2** | Hidden prior `read_file`, but later exact reread returned changed content |
| `freshness_or_polling` | **33** | Hidden prior dynamic/status/command observation; old snapshot recoverable but cannot prove currentness |
| `model_repeat_while_visible` | **141** | Prior concrete result had not been compressed before repeat; Evidence loss is not the explanation |
| `no_temporal_prior_observation` | **2** | Exact-repeat key existed but a prior successful result/Evidence was not temporally available |
| **Total** | **226** | Frozen same-run exact-repeat cohort |

This classifier is intentionally conservative. In particular, commands, web calls, job polling and runtime status are never called `program_amnesia_avoidable` merely because the old bytes are recoverable.

## `read_file` result

`read_file` is the strongest causal signal:

- exact same-run repeats: **89**
- prior concrete result still visible: **39**
- prior concrete result hidden: **50**
- hidden + later content identical: **48**
- hidden + later content changed: **2**

Therefore **48/50 = 96%** of hidden repeated reads in the frozen history did not obtain different source content. Under the new contract, the previous bytes were already available through Evidence hydration without rerunning the read.

This is the direct answer to the earlier question “被截断的文件有没有被归档保存、模型为什么还要重新找文件”：historically, the bytes often existed somewhere, but lacked a stable provider-neutral identity and exact hydration path in active semantic state. R0 supplies that missing path; R1 shows it would have covered these historical cases.

## Synthetic/stress vs naturalistic stratum

All-history totals remain authoritative; no trace is removed from them. A frozen first-user-prefix rule separately labels explicit pressure/SWE/operator-test sessions.

### Explicit synthetic/stress stratum

- sessions: 22
- same-run exact repeats: 71
- hidden prior concrete results: 44
- `program_amnesia_avoidable`: 39

### Naturalistic stratum

- sessions: 98
- same-run exact repeats: 155
- hidden prior concrete results: 39
- `program_amnesia_avoidable`: **9**
- `freshness_or_polling`: 30
- `model_repeat_while_visible`: 114
- no temporal prior observation: 2

The naturalistic result matters: the causal signal remains after separating explicit stress/benchmark traces, but it is much smaller than the all-history count. This prevents overclaiming that “all repeat loops were program amnesia.”

## Dynamic-state boundary

`architecture_status` illustrates why Evidence recovery and freshness are separate concepts:

- exact repeats: 46
- hidden prior results: 30
- all 30 classified as `freshness_or_polling`

The old observation can be recovered, but a runtime/status snapshot is not automatically current. The correct future behavior is: recover old evidence for context, then refresh only when currentness is decision-relevant.

`execute_command` shows the same principle: old stdout/stderr is evidence of what happened at acquisition time, not proof of present machine state.

## Provider/model switching

11 same-run exact repeats crossed a recorded model change in the historical cohort. All 11 occurred while the prior concrete result was still visible, so R1 does not attribute those repeats to Evidence loss.

R0 separately proved provider-neutral Evidence identity across projection switches. R1 therefore finds no historical basis to claim that every model-switch repeat is a recoverability failure.

## Performance observations

The first frozen historical replay records local Evidence overhead distribution rather than retroactively inventing a blocking SLO:

- Evidence capture: n=5,136; p50 about **0.69 ms**; p95 about **1.02 ms**; max about **15.75 ms**
- Evidence hydration before repeat: n=224; p50 about **0.15 ms**; p95 about **1.09 ms**; max about **1.47 ms**

These measurements are on the local replay workload and are suitable as input to a later rollout SLO; they are not a provider-latency claim.

## Verification

- formal R1 replay: **PASS**
- frozen sanity: **120 sessions / 5,419 calls / 226 repeats** reproduced exactly
- hidden prior-result recoverability: **83/83**
- lost EvidenceRef count: **0**
- provider/model calls: **0**
- source tool executions: **0**
- R1 unit tests: **3/3 PASS**
- targeted Ruff: **PASS**
- targeted Pyright: **0 errors / 0 warnings**

Machine-readable report: `data/audit/evidence_r1_replay_v1.json`

## Decision

R1 is **PASS**.

The architectural conclusion is narrower and stronger than a blanket anti-repeat rule:

1. program-induced evidence loss caused a measurable subset of repeated file reads;
2. stable EvidenceRef + exact hydration removes the need to rerun those reads merely to recover already-acquired bytes;
3. many repeats happened while prior evidence was still visible, so they require separate model/task-loop analysis rather than Evidence fixes;
4. dynamic observations require explicit freshness policy, not blind reuse and not blind rerun;
5. A3 duplicate suppression remains the wrong upstream fix and stays stopped.

Per frozen design, the next confirmatory phase is R2 fresh MiniMax + DeepSeek provider confirmation using new fixtures that isolate recoverability from freshness and from Action Guard behavior.
