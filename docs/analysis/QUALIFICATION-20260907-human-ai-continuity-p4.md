# Human-AI Continuity P4 Qualification — 2026-09-07

## Verdict

**P4 design correctness gate: PASS, with a model-specific protocol-continuity limitation.**

The final candidate run used product runtime commit `ba72592` (`fix(workspace): project model file effects`) on top of the independently closed P1–P3 chain. The P4 harness itself did not add runtime policy, prompt producers, automatic continuation summaries, or semantic completion scoring.

The reproducible handoff achieved the §13.2/§13.3 correctness requirements:

- the model completed the first two items through explicit snapshots and versioned edits;
- the authenticated human path preserved a real manual addition;
- a stale human draft was rejected and never overwrote newer bytes;
- the handoff process terminated with a deliberate hard process exit;
- a new process opened the same durable session and received only the user's continuation message;
- the model completed only the remaining four items;
- no already-completed write was replayed;
- all six final files matched the required byte-level conditions;
- the human addition remained intact;
- model and human effect receipts were queryable and mechanically attributed.

A separate observation remains **not qualified as a general model capability**: in both real runs, the resumed GLM did not continue using `read_file(snapshot=true)` plus `edit_file(expected_snapshot_ref=...)` for the remaining four writes, even though that mechanical rule remained verbatim in the durable initial user message. This is reported as `resume_versioned_write_contract=false`; it did not violate the P4 design's stated correctness gate, but it is a real instruction/protocol-continuity weakness for this model/run and should not be hidden.

## Scope and non-goals

This qualification covers the first Human-AI Continuity slice only:

- one workspace;
- one durable session;
- six UTF-8 text files;
- sequential model → human → process restart → same-session model handoff;
- one real model family for the final experiment;
- no concurrent human/model writes during the editing interval;
- no S1 WorkingStateCheckpoint producer;
- no program-generated continuation summary;
- no cross-machine or cross-session claim.

It does **not** prove universal Agent capability, semantic completion quality, or invisible chain-of-thought restoration.

## Product baseline

Relevant feature history:

- `8583e0d` — P1, Task Evidence ref verification
- `3bf1a9f` — P1 factory import-ratchet closure
- `60c088c` — P2, versioned shared file service
- `10f14a8` — P3, authenticated human file collaboration and unified file-effect query
- `ba72592` — P4-discovered mechanical fix: correctly project model-tool prepared/observed events

The main mirror remained untouched during P4.

## Deterministic mechanical handoff

`tests/integration/test_human_ai_continuity_p4.py` exercises the production file/session/event stack without a model call.

Sequence:

1. Create six real fixture files.
2. Create a stale human observation for item1.
3. Exercise the model-side durable path for item1/item2 using:
   - `read_file(snapshot=true)`;
   - `ToolExecutionJournal` declared/started/effect binding;
   - `edit_file(expected_snapshot_ref=...)`;
   - finished + receipt committed.
4. Human re-observes item2 and appends `HUMAN_NOTE: preserve-this` through `HumanFileOperationService`.
5. Human attempts the stale item1 save; `version_conflict` rejects it and stale bytes do not land.
6. Destroy the first Engine object graph.
7. Build a new Engine against the same data/session/workspace and verify the original session exists.
8. Query both model-tool and authenticated-human file effects.
9. Complete item3–item6 through the model-side mechanical path.
10. Verify exact final file invariants and that the handoff fabricated no chat messages.

Result: **PASS**.

The prepared/observed crash tri-state remains covered by the P3 T18 fault-injection test: a child process exits between durable prepared facts and any proven completion, and a fresh process reports `current_matches_before`, `current_matches_expected`, or `current_diverged` while keeping `causation_proven=false` and `auto_reexecuted=false`.

## P4-discovered P3 projection defect

The first real run exposed a factual-query defect rather than a failed write:

- EventStore contained real `tool.execution.effect_prepared` and `tool.execution.effect_observed` pairs with SHA, artifact ref, and `matches_expected`.
- `FileEffectQueryService` grouped them correctly but selected prepared/observed records through `.prepared` / `.observed` string suffix checks.
- The model-tool event names use `_prepared` / `_observed`, so completed model effects were incorrectly projected as `outcome_unknown`.

A RED assertion was added requiring a model observed event to project as `observed_match`, `causation_proven=true`, with the observed SHA and artifact ref. The implementation now recognizes the explicit registered event constants rather than guessing from string suffixes.

Fix: `ba72592 fix(workspace): project model file effects`.

After the fix, the existing real-run event ledger re-projects all six model writes as `observed_match` with `causation_proven=true`.

## Real-model experiment

### Model and isolation

Final real qualification model: `glm/glm-5.3`, resolved through the existing provider registry to the configured GLM endpoint. Provider fallback was explicitly disabled for the experiment.

The initially considered local model server was excluded from formal evidence after an exploratory alias probe caused that server to enter an unrelated model-resolution/fetch state. It was not restarted or reused for the final P4 run, and no second local large model was loaded. This prevents a contaminated local inference state from being mistaken for a continuity result.

No credential value is stored in this report or the P4 runner. The runner requires an explicit environment file path, provider-registry path, and model ref at execution time; secret values remain environment-only.

### Fixed task

Initial user instruction required the model to edit exactly item1 and item2 first. For every file, the target transformation was:

- `STATUS: pending` → `STATUS: reviewed`;
- add exactly one `AI_MARKER: completed` immediately after STATUS;
- preserve all other existing content and later human additions;
- do not repeat already-completed items.

The initial instruction also explicitly requested a snapshot/version-precondition write protocol and prohibited using shell/Python/sed as a mutation bypass.

After the human handoff and hard process exit, the new process received only:

> 继续完成刚才的任务，保留我的修改。

No program-generated handoff text was inserted.

## Final candidate run (R2, product baseline `ba72592`)

### Timeline

1. Initial process/session created the six files and a stale item1 human observation.
2. GLM initial run used 3 rounds and exactly:
   - 2 × `read_file(snapshot=true)` for item1/item2;
   - 2 × versioned `edit_file(expected_snapshot_ref=...)` for item1/item2.
3. A separate human process re-observed item2, appended `HUMAN_NOTE: preserve-this`, and saved through the authenticated human path.
4. The stale item1 human request was rejected with `version_conflict`; stale content did not land.
5. That process terminated through deliberate `os._exit(73)`, bypassing graceful interpreter/Engine teardown.
6. A new process opened the original session and ran the literal continuation message above.
7. The resumed model inspected the workspace, re-read item2, explicitly observed the human note, left item1/item2 untouched, and edited item3–item6.
8. Two `execute_command` calls in the resume trace were read-only (`pwd/ls` and final `cat/grep` verification); neither mutated a fixture file.
9. Final byte checks passed for all six files.

### Mechanical result matrix

| Check | R2 |
|---|---|
| final six files satisfy byte conditions | PASS |
| manual `HUMAN_NOTE` preserved | PASS |
| stale item1 bytes did not land | PASS |
| stale request produced version conflict | PASS |
| initial run touched only item1/item2 | PASS |
| initial item1/item2 writes used snapshot + expected ref | PASS |
| resume completed item3–item6 | PASS |
| resume did not rewrite item1/item2 | PASS |
| authenticated human success receipt present | PASS |
| authenticated human stale rejection receipt present | PASS |
| all six model write effects project as observed facts | PASS |
| explicit human-change observation | PASS — item2 was re-read and final answer named `HUMAN_NOTE` |
| resume continued snapshot + expected-ref protocol | **FAIL / limitation** |

### Final bytes

Each item contained exactly one `AI_MARKER: completed`, no `STATUS: pending` remained, and every original `KEEP: keep-N` line survived. Item2 additionally retained exactly the manual handoff line `HUMAN_NOTE: preserve-this`.

There was no repeated write to item1/item2 during resume.

## Discovery run (R1)

The first real run is retained as discovery evidence rather than final qualification evidence because it exposed the model-effect projection bug that was subsequently fixed.

R1 still satisfied the byte-level Human-AI correctness gate:

- all final files correct;
- human note preserved;
- stale request rejected;
- no duplicate completed writes.

However:

- explicit recognition of the manual item2 change was **not proven**; the model did not query file effects or re-read item2;
- resume again did not use snapshot + expected-ref writes.

This difference between R1 and R2 shows that explicit human-edit awareness is a model/tool-choice behavior, not something this single experiment can claim as deterministic. The final correctness contract therefore remains mechanical: preserve the human bytes, do not replay already-completed side effects, and do not fabricate unknown outcomes.

## Cost evidence

Token accounting is provider-reported usage. Cache-hit rate below is `cache_hit_tokens / input_tokens`; missing usage would have been reported as unknown rather than zero.

| Run | Phase | Rounds | Input | Output | Cache hit | Hit rate |
|---|---:|---:|---:|---:|---:|---:|
| R1 discovery | initial | 3 | 19,697 | 1,329 | 12,160 | 61.74% |
| R1 discovery | resume | 4 | 29,514 | 2,355 | 25,600 | 86.74% |
| R1 total | — | 7 | 49,211 | 3,684 | 37,760 | 76.73% |
| R2 final | initial | 3 | 19,411 | 948 | 17,856 | 91.99% |
| R2 final | resume | 9 | 78,780 | 3,888 | 71,936 | 91.31% |
| R2 total | — | 12 | 98,191 | 4,836 | 89,792 | 91.45% |

Observed parent wall time was about 192 s for R1 and 245 s for R2. Those totals include repeated fail-open initialization time for an unrelated unavailable MCP server and therefore **must not** be interpreted as pure model latency or time-to-first-token.

The higher R2 resume cost came from more workspace discovery/verification: several `search_files` calls, reads of all six items, and final read-only shell verification. This is an observed model choice, not a program-enforced workflow.

## Protocol-continuity finding

Both R1 and R2 showed the same extra limitation:

- initial: `snapshot + expected_snapshot_ref` protocol observed;
- resume: version-precondition protocol not observed.

The durable session was inspected after R2. The original 523-character user message remained present verbatim and still contained both `snapshot=true` and `expected_snapshot_ref`; `summary_mode=off` was used and the session was far below its context bound. Therefore there is no evidence that LFL lost this instruction during persistence/restart.

The narrow conclusion is:

> GLM recovered the task goal and completed the remaining work correctly, but did not reliably carry forward the user's earlier mechanical write-protocol instruction into resumed tool selection.

This is a model-specific instruction-following observation. It is **not** a reason to inject a program-authored continuation prompt, hide tools, or add a semantic policy engine. If this behavior is pursued further, it should be measured as a separate model/tool-schema ergonomics experiment.

## Architecture boundary audit

P4 did not add any of the following:

- automatic `engine.run` after a human save;
- synthetic user/assistant/tool messages for the human edit;
- automatic summary/checkpoint injection into the model prompt;
- semantic determination that a task is complete;
- automatic replay of an unknown file effect;
- model tool filtering based on task keywords;
- S1 WorkingStateCheckpoint producer activation;
- a second Goal/Task truth source.

The new P4 code is an experiment/test harness only.

## Qualification hygiene and limitations

- Only one model family (`glm/glm-5.3`) is used for the final real experiment.
- R1/R2 are two samples, not a statistical benchmark.
- Cache state was warm to different degrees; results are reported, not normalized into a claimed speedup.
- The local model exploratory probe is excluded from final evidence because its server state became contaminated by alias-driven model resolution.
- The experiment does not prove arbitrary external-editor coordination, cross-session ownership, directory moves, or cross-machine recovery.
- Explicit awareness of the human edit varied between R1 and R2; only preservation/no-replay is treated as the deterministic correctness requirement.

## Closure decision

**P4 is eligible to close against the original Human-AI Continuity v0.1 correctness gate.**

P1–P4 now demonstrate a complete narrow chain:

1. claimed evidence refs are mechanically authenticatable;
2. AI/human file writes share byte/version/locking facts;
3. authenticated humans can edit through a thin version-protected entry and query effects;
4. after real human intervention and a hard process boundary, a new process can reopen the original session and a real model can finish the remaining work without overwriting the human change or replaying completed writes.

The GLM resume protocol-continuity limitation remains an explicit follow-up observation, not silently upgraded into a product guarantee.
