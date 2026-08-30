# R8.9 Ephemeral Control Lifecycle Closure

Status: **IMPLEMENTATION PASS / detached-clean fixed-point pending**

## Root cause

Several program-generated controls had two different lifetimes conflated:

- **same-human-turn control**: useful for another LLM/tool round while the current human request is still unresolved;
- **future-human-turn prompt authority**: should not exist after the controlling event is consumed or the answer is already produced.

Persisting both as ordinary session history caused stale control text to re-enter later provider prompts, increasing structural drift and cache instability and encouraging repeated tool/search behavior.

The owner rule for this batch is:

> **same-turn useful does not imply next-turn injectable**

## Closed surfaces

- **E14 declaration reminder** — validation occurs after the model final answer exists, so a prompt reminder cannot repair that answer. New code keeps the discrepancy in `LoopResult.verification_note`, UI/CLI/Feishu presentation, validator audit, and action telemetry only. It no longer appends a prompt/session reminder. A census found 131 legacy user-role reminders across 39 sessions; all used the same complete historical program sentence. Eligibility filters only that exact sentence, not the generic `[声明提醒]` label, preserving user-authored discussion.
- **E15 stagnation reminder** — new reminders carry `prompt_lifecycle=current_turn` and exact `turn_ref`; they remain available to subsequent LLM/tool rounds in the same human turn and expire on the next human ingress. Legacy unlabelled system reminders are denied centrally.
- **E16 empty-search reminder** — same current-turn lifecycle; durable negative-evidence/action state remains the persistence surface.
- **E17 overflow feedback** — overflow reinjection now carries explicit STATUS/program identity plus current-turn lifecycle. It can drive the immediate retry/decision but cannot leak to a later human task. Legacy overflow system messages are denied centrally.
- **E27 fallback notice** — fallback notices are generated only after the fallback call has returned, so storing them as future prompt history had no ability to influence the already-produced response. Successful fallback remains visible in status/audit/action state; all-failed detail is appended to the current program final result, not a separate future system notice. Legacy fallback system notices are denied centrally.

## Eligibility implementation

`current_turn_program_prompt_eligible()` is the central persisted-control gate. New emitters use explicit lifecycle metadata rather than text prefixes. Prefix matching exists only as a conservative compatibility path for known pre-metadata historical frames; declaration compatibility uses the full exact fixed program sentence to avoid hiding genuine human input.

## Verification so far

- touched production pyright: **0 errors / 0 warnings**
- new/clean touched tests pyright: **0 errors / 0 warnings**
- focused + adjacent behavior suite across 22 test files: **PASS**
- history/reference compatibility subset: **77/77 PASS**

Detached-clean fixed-point, R0 four-gate replay, frozen hash verification, and exact staging are still required before this batch is final.

## Boundary

R8.9 closes only E14/E15/E16/E17/E27. Remaining PARTIAL/OPEN surfaces are not implicitly solved. `behavior_canary_gate_state=READY` remains an R8.8 fact, but **behavior canary and R9 are still not started** while the deep-audit Goal continues.
