# R8.10 Program-Final + Program-Fault Authority Closure

Status: **PASS / detached-clean fixed-point verified**

Implementation commit: `7b5334d fix(injection): retire program fault prompt authority`

## Root cause

R8.8/R8.9 separated resolved history and same-turn control lifecycle, but two related forms of program output could still gain conversational authority:

1. a run that ended in a program result (`llm_error`, cancellation, guard block, stagnation, routing override, and similar exits) was persisted as an assistant message whose full error/control prose was replayed on later turns;
2. auxiliary component faults (`session_persistence`, `archive_sink`, memory retrieval) could be materialized as ordinary model-facing messages even though the same facts already existed in recovery, selfheal, status, or action telemetry.

The R8.10 owner rule is:

> **storage/event truth, user-visible result, provider protocol shape, and prompt authority are separate concerns.**

A fact may need durable storage or current-user disclosure without earning automatic model prompt authority.

## Program-final provider boundary

Current storage census found **52** `answer_origin=program` assistant messages across **22** sessions:

- `llm_error`: 34
- `cancelled`: 13
- `guard_blocked`: 3
- `routing_override`: 1
- `stagnation`: 1

Those messages contained **8,251 chars** of historical program-result prose. Replaying the full body was unnecessary, but deleting the assistant frame outright could transform `user → program-assistant → user` into consecutive user roles and recreate provider 1210-sensitive structure.

R8.10 therefore keeps exactly one byte-stable provider boundary:

```text
[程序终止边界·无模型回答]
```

The provider projection replaces historical program-result detail with this assistant frame and clears `reasoning_content`. Session/event storage remains untouched. The 52-message census would project to **728 chars**, a **91.18% reduction** in dynamic historical program-result text (old median 118 chars; max 492), while preserving `user → assistant → user` protocol shape.

The `resp=None` assignment in the fallback-exhausted path is also placed immediately after program-final construction so a stale earlier model response cannot lend reasoning content to a program-produced final result.

## E33 program-fault observability closure

E33 is now **DONE / OBSERVABILITY_ONLY**.

### Initial session persistence failure

The runtime still:

- logs the failure;
- attempts the existing recovery channel;
- calls `_fault_feedback()` for `selfheal_log` evidence;
- increments structured program-fault state;
- emits action telemetry.

It no longer appends the generated `[程序异常]` prose to `sess.messages`, so the failure cannot become model history.

### Archive sink failure

Archive failure still records selfheal/status/action evidence. It no longer appends a program-authored fault `Message` to the active or stored session.

### Memory retrieval failure

A memory backend exception remains fail-open and observable, but it is not semantic memory. R8.10 therefore does not convert fault prose into a current-turn `memory_snapshot`; the model receives no synthetic memory-fault instruction.

### Legacy compatibility

The current storage census found **0** persisted system-role `[程序异常]` messages, but old backups/imported sessions can still contain them. `current_turn_program_prompt_eligible()` denies legacy system `[程序异常]` frames so historical data cannot regain prompt authority after restore/import.

### Loop-end save failure remains user-visible

A failure while saving the completed turn is different: the user must know that the answer may not have persisted. The existing current `final_answer` disclosure remains. That result is marked `answer_origin=program`; on a later user turn the program-final projection replaces its fault details with the fixed assistant protocol boundary. Thus current-user honesty is preserved without future prompt pollution.

## Verification

Detached clean checkout of `7b5334d` passed:

- focused R8.10/E33 suite: **105/105 PASS**;
- broader archive/history/fail-open/cache/reference/answer-origin/1210 adjacent suite: **274/274 PASS**;
- touched production pyright: **0 errors / 0 warnings**;
- canonical R0 replay: **R0-1 through R0-4 PASS**;
- tracked `docs/injection-governance/r0` directory: **byte-unchanged**; frozen hash remains `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`;
- detached checkout status: **clean before and after verification**.

Updated tests specifically prove that program faults retain observability while producing zero new session/provider prompt prose, and that historical program-final storage remains exact while provider projection is minimized.

## Matrix state and boundary

After closing E33, the eligibility matrix is:

- `DONE=20`
- `KEEP=1`
- `PARTIAL=10`
- `OPEN=3`

`behavior_canary_allowed=true` / `behavior_canary_gate_state=READY` remains unchanged. **Behavior canary and R9 are still not started**; remaining PARTIAL/OPEN surfaces continue under the deep-audit Goal.
