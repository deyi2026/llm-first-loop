# Execution Efficiency v2 baseline — 2026-09-29

## Disposition

**Do not optimize for fewer visible tools. Do not start main-domain semantic tool projection from the current evidence.**

The useful objective is whole-run execution quality in this order:

1. verified correctness as a hard gate;
2. First-Call-Ready (appropriate first action × mechanically dispatchable call);
3. wrong / rejected / repair calls;
4. serial tool barriers and wall time;
5. uncached input + output tokens, with cache-hit tokens reported separately.

There is deliberately no pooled weighted score. Tool count is diagnostic context, not a target.

## Why the previous FCR number was misleading

The historical pilot registry defaults most tasks to `first_tools=["read"]`. That is too narrow for several whole-run tasks:

- `t02_retry_transient` explicitly asks to run `python3 gen.py`; `execute_command` is the intended first action.
- `t11_env_facts` explicitly requires `whoami` / `pwd`; command-first is required by the task.
- `t04_fix_bug` legitimately permits test-first or source-read-first diagnosis.
- `t05_multi_file_sum` and `t09_big_file_line` both admit a bounded read path or a direct shell path.

The old scorer also treated `first_call.ok == false` as mechanically invalid arguments. That incorrectly penalizes `t02`: its first process exit is intentionally nonzero and is the required observation before retry.

EEv2 therefore separates **selection** from **dispatchability**. Runtime/process failure may still be a mechanically valid first call; schema/contract/safety rejection is not. The acceptable first-action classes are pre-registered in `evals/execution_efficiency_v2/oracles.py` rather than inferred from prompt text during scoring.

## Frozen source evidence

Current main no longer carries the historical `evals/execution_efficiency_fcr/*.py` source bundle; it is preserved on `archive/root-untracked-eval-bundle-20260929@80f7ff79b51252da162634bbcf391a6a0e3e2017`. Current `evals/pilot/telemetry.py` is byte-identical to the archived evaluator source (SHA256 `f9d35c07bc8907acdddb750daf150a55a655dbc1679d390a8960a52c370e2605`).

The complete P1A input used here is `P1A-WHOLE-RAW.v0.2.jsonl`, 36 rows, SHA256 `76745ea044d9848a8f06ca010f00aa751b2490d2dd362a071fd63474a0c7cfcf`, Git blob `0a169307b001a8dde19b1138273a03c844ae05bc`.

`P1B-RAW.v0.1-r1.jsonl` contains only 45 of the expected 48 rows and is diagnostic only. P2 has no EEv2 wrong-tool oracle and is not used to infer one.

## P1A whole-run re-score

All three arms remain **12/12 correct**. Legacy FCR was 13/36 overall; after fixing the oracle/dispatchability confounds, FCR-v2 is **36/36**, with **0 measured wrong first-tool calls** in this six-task corpus.

| Arm | Correct | FCR-v2 | Legacy FCR | Rejects | Contract rejects | Repair sequences | Serial barriers | Median rounds | Median uncached input | Median wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A-current | 12/12 | 12/12 | 5/12 | 8 | 2 | 6 | 40 | 5.5 | 1,205 | 55.866s |
| B-fcr-contract | 12/12 | 12/12 | 4/12 | 6 | 1 | 4 | 33 | 4.5 | 1,456.5 | 46.547s |
| D-full-reference | 12/12 | 12/12 | 4/12 | 5 | 1 | 3 | 32 | 4.0 | 1,463 | 49.379s |

This reverses an important interpretation. The richer B/D surfaces do **not** win because they expose fewer tools; they keep correctness and corrected FCR unchanged while trading roughly +250 median uncached input tokens for fewer failed/repair paths and fewer serial barriers. That is exactly why schema bytes or tool-call count cannot be the objective by themselves.

The P1A corpus also has zero `get_tool_schema` rereads. It therefore provides no evidence that progressive schema disclosure is currently causing its whole-run overhead.

## What actually failed

There were 19 rejected tool calls:

- 15 `execute_command`
  - **13**: macOS/BSD portability failure from GNU-style `cat -A`;
  - 1: expected `t02` transient process failure;
  - 1: shell syntax failure.
- 4 `edit_file`
  - 2: empty `old_string` anchor;
  - 2: snapshot/version-precondition contract failures.

The current main already exposes the edit contract prominently: `edit_file` says to call `read_file(snapshot=true)` and pass its `snapshot_ref` unchanged as `expected_snapshot_ref`; its current lazy machine schema also requires that field. Historical edit failures are therefore not evidence that current edit schema remains deficient.

By contrast, current `execute_command` explains fresh-shell/workdir behavior but does not expose a compact host-portability fact. The 13 `cat -A` failures are the largest measured repair source in this baseline.

## Schema size cross-check

Current main's isolated lazy registry has **74 tools** and about **32,749 per-tool JSON characters**. The largest rows are:

- `browser_perceive`: 4,056
- `browser_operate`: 3,359
- `method_manage`: 1,113
- `service_control`: 1,104
- `task_update`: 995
- `search_records`: 915

But the measured P1A failure-bearing schemas are small:

- `execute_command`: 298 chars
- `edit_file`: 449 chars
- `read_file`: 383 chars
- `get_tool_schema`: 208 chars

Therefore **compressing the largest schemas first is a token experiment, not an error-reduction experiment**. It may still be useful later, but it does not target the dominant measured failure source.

## Next experiment

The next qualified experiment should keep every mechanically healthy tool visible and test one narrow mechanical contract:

> `execute_command.command` executes against the actual host shell/toolset; do not assume GNU-only flags. Prefer host/POSIX-portable forms, or inspect `uname` / command help when platform-specific behavior matters.

Run baseline vs this small treatment on a **new holdout** containing:

1. portable-shell failure families that do not leak `cat -A` specifically;
2. true wrong-tool discriminator tasks with pre-registered acceptable and negative alternatives;
3. current `edit_file` contract controls.

Promotion gates remain correctness → FCR-v2 → wrong/rejected/repair calls → serial barriers/wall → uncached tokens. A separate later experiment may target the large browser schemas for token savings, but it must not be conflated with wrong-call reduction.

This baseline does **not** authorize semantic tool hiding, main-domain tool projection, or a production schema/default change.
