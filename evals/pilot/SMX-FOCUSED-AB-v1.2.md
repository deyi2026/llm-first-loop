# AgentPilot SMX focused v1.2 A/B protocol (frozen before execution)

Status: **frozen_not_executed**. No model run is authorized by this file.

Supersession: **SMX focused v1.1 is deprecated and superseded by v1.2**. v1.1 remains immutable historical evidence at `dba31bd79c106820e021902d5bcf43bfb32f5fd1`; it must not be revived as a new formal execution protocol.

## 0. Supersession and re-freeze boundary

v1.2 is a **re-freeze, not a redesign**. Mechanical differential proof is committed as `smx_focused_v1_2_diff_from_v1_1.json`. It establishes:

- the 30 plan rows are identical to v1.1;
- tasks, arms, seed, repeats, invalidation conditions and required execution manifest are identical;
- 17/18 frozen source hashes are identical;
- the only changed frozen source is `evals/pilot/analyze.py`, where `session_continuity` was corrected to the actual result key `resume_session_continuity`;
- SMX implementation/glue/registry hashes remain byte-identical.

This document therefore makes no new causal claim. The analyzer change is recorded as a display-key correction; the proof preserves the exact unified-diff fingerprint.

SMC provenance relevant to this re-freeze: the initial uncommitted `SMC-CONTRACT-v0.1` draft was 338 lines; adversarial review expanded the normative contract to 515 lines. The later 516-line main-worktree copy was byte-identical after trimming one extra EOF newline and was deleted after the committed 515-line version was secured.

## 1. Purpose and causal boundary

This experiment measures the incremental effect of registering LFL's opt-in `smx_perceive` tool while keeping the same LFL harness, Ornith model weights, `/research/mlx-lm` inference server, task judge, and sampling/runtime configuration.

It does **not** modify or reinterpret AgentPilot v1's 108 formal results. SMX had zero calls in that matrix and therefore receives no causal credit for v1.

The treatment is integrated capability availability: OFF has no `smx_perceive` provider tool; ON registers the exact `tools/smx/smx.py` implementation through `LFL_SMX_PERCEIVE`. The program never requires the model to call SMX.

## 2. Task set (5)

| focused id | source fixture | role | reason |
|---|---|---|---|
| `sx_wait_existing_writer` | `tools/smx/lab/tasks/T3` | positive_wait | wait for an already-running writer's `done.flag` without sleep/re-read polling |
| `sx_background_worker` | `tools/smx/lab/tasks/T6` | positive_wait | start worker in background, observe completion, then collect result |
| `sx_bulk_rename_diff` | `tools/smx/lab/tasks/T4` | positive_diff | snapshot/diff can describe net directory changes after bulk rename |
| `ap_t06_log_count` | AgentPilot `t06_log_count` | negative_control | existing AgentPilot t06 is log counting, **not** the SMX Stage2 T6 wait task |
| `ap_t09_big_file_line` | AgentPilot `t09_big_file_line` | negative_control | `smx_perceive` does not read file contents; normal `read_file` remains the direct capability |

The task-id collision is intentional documentation: AgentPilot `t06` and SMX Stage2 `T6` are unrelated tasks and must never be conflated in analysis.

## 3. Arms

- **OFF (`lfl_smx_off`)**: `LFL_SMX_PERCEIVE=""`; provider tool surface must not contain `smx_perceive`.
- **ON (`lfl_smx_on`)**: `LFL_SMX_PERCEIVE=<absolute repo>/tools/smx/smx.py`; provider tool surface must contain exactly one `smx_perceive`, and manifest must record both glue and implementation SHA256.

No appended model instruction tells the model to use SMX. Tool availability/schema is the treatment. No placebo prose arm is required for this first LFL-native A/B because the earlier Stage2 four-line card confound is absent here; if mechanism attribution later matters, a separate placebo-tool study must be versioned independently.

## 4. Runs and ordering

- 5 tasks × 2 arms × 3 independent repeats = **30 runs**.
- Frozen scheduling seed: `20260912`.
- Unit of randomization: `(task_id, repeat)` paired block. Each block runs both OFF and ON; within-pair arm order is deterministically shuffled from the seed.
- Global OFF-first / ON-first counts may differ by at most one (15 paired blocks -> 8/7).
- Every run uses a fresh task workspace and fresh LFL session. No historical result file may be reused.
- Do not execute while another user test is occupying 8901; current server is prompt-concurrency=1 and a competing run would contaminate latency/trajectory.

## 5. Mechanical judging and telemetry

Task success is determined only by the existing fixture judge/verify logic. SMX adoption or non-adoption is **not** a success criterion.

Per run, preserve raw tool events and derive only mechanical measurements:

- task status / judge result;
- total model rounds and total tool calls;
- Gate-3 first-call fields: first mechanical-valid round, selection correctness, First-Call-Ready when the task oracle defines it;
- `smx_perceive` call count and action counts (`wait`, `snapshot`, `diff`, `receipt`);
- `execute_command` count; mechanically detected `sleep` command count;
- `read_file` / `search_files` count;
- for wait fixtures only, observation calls after trigger/background-start and before the completion fact first becomes visible;
- for diff fixture only, observation calls after the mutation and before final judge-ready state;
- unexpected tool failure count and repair count;
- wall time (secondary/noisy);
- cache/tokens as descriptive LFL-only telemetry, not a primary causal metric because ON changes provider tool-schema prefix bytes.

Do not infer “unnecessary” work from tool names at runtime. Any semantic/directness interpretation remains an offline scorer decision.

## 6. Predeclared interpretation boundaries

### Adoption gate
Among the 9 ON positive-task runs (3 positive tasks × 3 repeats), if fewer than 5 call `smx_perceive`, treatment adoption is insufficient. Report the runs, but do not claim benefit/non-benefit from pooled ON averages.

### Wait hypothesis
For adopted `sx_wait_existing_writer` / `sx_background_worker` pairs, report paired changes in rounds, sleep calls, and post-trigger observation calls. With n<=6, only directional/paired evidence is allowed; no significance claim.

### Diff hypothesis
For adopted `sx_bulk_rename_diff` pairs, report paired post-mutation observation calls and total rounds. A flat or worse result is a valid counterexample.

### Negative controls
`ap_t06_log_count` and `ap_t09_big_file_line` must retain task success. Any SMX calls are reported as treatment overhead/adoption spillover, not automatically scored as model error.

### Reliability
This focused experiment is not an H3 reliability qualification. If both arms remain ceiling-level on task success/tool errors, reliability stays `insufficient`.

## 7. Manifest / invalidation requirements

Before the first model call, freeze and hash:

- exact LFL git commit and dirty-state assertion;
- Ornith physical model directory fingerprint and 8901 runtime identity/config;
- sampling/reasoning/runtime config;
- OFF and ON provider tool-surface hashes;
- resolved `LFL_SMX_PERCEIVE` path for ON;
- `tools/smx/smx.py`, `smx_perceive.py`, config/factory/registry hashes;
- all focused task prompt/setup/judge or AgentPilot task-registry hashes;
- runner, telemetry and scorer hashes;
- seed, generated 30-run plan, and plan SHA256.

Invalidation conditions: any frozen hash changes, service/model identity changes mid-matrix, a duplicate/concurrent runner writes the same workdir, plan indices are missing/duplicated, or an unrelated 8901 workload overlaps a measured run. Preserve invalidated raw evidence; never rewrite it into a clean result.

## 8. Execution gate

This document freezes the protocol only. **Do not execute v1.1.** v1.2 model execution requires a later uncontended 8901 window and a fresh execution manifest that records the exact v1.2 commit/dirty state and rechecks every frozen source hash.

This document freezes the protocol only. Current user testing/no-restart boundaries remain in force. Running the 30 model calls requires a later uncontended 8901 window; no service restart is inherently required because SMX is per-run opt-in through LFL process environment.

## 9. v1.1 -> v1.2 differential proof

Machine-readable proof: `evals/pilot/smx_focused_v1_2_diff_from_v1_1.json`.

Required self-check before any model call:

1. `test_smx_focused_protocol_v1_2.py` passes on the exact execution tree.
2. v1.2 plan file SHA equals the spec's `execution_plan_sha256`.
3. canonical plan-row fingerprint equals v1.1's frozen fingerprint `cdac602f6e5b757ec1ee869eebc67c7506ac5f84fbc7ee8b9c55d223fe081414`.
4. canonical causal-design fingerprint equals v1.1's frozen fingerprint `7ea2738f77f9fb2de5e4b89d3025981e9f49a80a867f9a48f499d89c5695bdf0`.
5. the only v1.1 -> v1.2 frozen-source change remains `evals/pilot/analyze.py`; any additional change invalidates this re-freeze and requires a new protocol version.
