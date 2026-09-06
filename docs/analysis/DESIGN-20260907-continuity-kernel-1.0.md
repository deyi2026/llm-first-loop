# Continuity Kernel 1.0 - authority and precedence contract

- Date: 2026-09-07
- Status: CK1 G2 contract; implementation must conform before CK1 can close.
- Scope: the mirror LFL repository only.
- External research: the external research workspace and StateBraid are read-only references for this workline. They are not modified or activated by CK1.

## 1. Purpose

Continuity Kernel 1.0 keeps long Agent work coherent across provider truncation, process restart, history compaction, evidence folding, and an immediately adjacent user continuation without creating a second semantic decision system.

The kernel preserves facts and recoverable representations. It does not decide what evidence is relevant, whether a task is complete, whether a checkpoint is "clean", or what the model must do next.

## 2. Authority map

| Surface | Owner / truth | Model-visible role | CK1 authority |
| --- | --- | --- | --- |
| Session + EventLog | durable chronological facts | projected history as eligible | authoritative storage chronology |
| Evidence Ledger + EvidenceRef | exact already-acquired Tool Observation, provenance and source-version facts | explicit list/search/read hydration; receipts may carry stable ref | authoritative evidence recovery |
| Provider partial / native sidecar | exact bytes and provider-native in-flight transport state | one-shot adjacent continuity when mechanically eligible | authoritative unfinished transport fact |
| History compaction | provider-view representation under physical/operator budget | retained raw history only; no generated semantic summary | representation only |
| Tool working-set receipt | representation of an already-exposed, durably recoverable tool result | thin factual receipt with EvidenceRef | representation only; default OFF |
| WorkingStateCheckpoint | optional model-authored derived state + selected raw evidence IDs | only at the exact transcript/provider/model boundary where it was authored | optional derived state; production producer HOLD |
| Recent continuity | structural placement of immediately prior model state + current genuine human ingress | final adjacent suffix on the initial human build | structural precedence only |
| Goal / hotcard / handoff | durable historical task evidence | only after explicit resume/recovery authorization | never self-authorizing |
| Cache / prefix / StateBraid facts | compute/cache observability | status/telemetry when queried | never task strategy, relevance or completion authority |
| `fixed_summary` / `summary_chain` | legacy serialization compatibility | none in current production | dormant; do not revive as CK1 state |

## 3. Non-negotiable authority rules

1. The current genuine human ingress is the current task-authorization truth. A short reply such as `continue` binds only to the nearest relevant interaction and must not reactivate older Goal, memory, archive, hotcard or assistant-plan state by itself.
2. Durable history is evidence, not current instruction authority.
3. Program code may validate identity, pairing, provenance, source version, bounds, provider/model identity, transcript boundary and resource limits. It must not infer evidence relevance, importance, sufficiency, task applicability, completion or next action.
4. Compaction and receipts may change representation only after exact source bytes are durably recoverable. They must not synthesize semantic fold summaries.
5. WorkingStateCheckpoint remains optional model-authored derived state. CK1 does not add a forced producer, pressure-threshold prompt, required checkpoint field, or semantic checkpoint gate.
6. Generic cache hit / cached-token-to-message estimates are observability only. Only an explicit exact provider contract may become a mechanical cache-boundary fact.
7. Goal/hotcard recovery requires explicit user-authorized resume. No new session automatically attaches a stale Goal.

## 4. Precedence and lifecycle

### 4.1 Initial build for a genuine human turn

At the initial provider build for the current human turn:

1. Load durable Session/EventLog truth.
2. Resolve current provider/model identity and mechanically eligible evidence/representation state.
3. An exact-boundary WorkingStateCheckpoint, if one already exists, may preserve its selected raw evidence and append its model-authored state. Any later transcript change makes that checkpoint stale.
4. History compaction / working-set receipts may shrink only recoverable older representation; selected raw protocol groups remain exact.
5. Recent continuity runs last among continuity representations so the immediately adjacent unfinished model state (or nearest completed model assistant) and the current genuine human ingress form the final suffix.
6. Once the current turn has advanced into assistant(tool_calls) -> tool protocol, native append order is authoritative and recent-continuity tail reordering is disabled.

### 4.2 Provider truncation and process restart

- A provider token-limit stop or interrupted stream is unfinished model output, not a completed answer.
- Exact partial text/reasoning and hash-verified native sidecar state may be restored for the next genuine human ingress.
- Provider-native opaque replay state is transport state, not prose. It must survive restart when captured, but it may only be projected back through the existing provider whitelist for the originating provider identity. It must never leak as a foreign provider wire field.
- Partial tool-call drafts remain non-executable crash facts until a normal provider completion produces an actual ToolCall.
- When transcript boundary advances after an S1 checkpoint, the checkpoint becomes mechanically stale and interruption/provider-truncation continuity owns the adjacent recovery path.

### 4.3 Current user identity and attachments

The current genuine human message must be identified structurally, not by comparing raw `Message.content` to provider-wire content.

`Message.to_llm_dict()` may mechanically add attachment facts to the user wire while durable human content remains byte-exact. Recent continuity must preserve that exact already-projected attachment-bearing wire message; attachments must not disable recovery of the immediately preceding interrupted model state.

## 5. State that must not be duplicated

CK1 must not add another parallel semantic state representation for any of the following:

- task summary;
- evidence importance ranking;
- completion status inferred from prose;
- fold summary;
- "clean checkpoint" selection;
- auto-resume instruction;
- cache-driven task strategy.

Existing `fixed_summary` / `summary_chain` are compatibility fields only. Existing archive/Evidence recovery remains the exact source path.

## 6. Current production defaults and reachability

As of this contract freeze:

- `LFL_TOOL_WORKING_SET_RECEIPTS` defaults OFF.
- `build_working_state_checkpoint()` has no production `src/` producer callsite; consumer/persistence/tests/benchmark exist.
- automatic Evidence Recovery Manifest prompt injection is retired.
- automatic LLM history summarization is retired; compaction is archive + representation mechanics.
- generic cache-window boundary has `boundary_exact=False`.
- `get_goal` / hotcard are explicit recovery surfaces, not automatic prompt authority.

## 7. G1 defects that G3 must repair

### CK1-R1 - provider-native interruption replay is dropped

`InterruptedCapture` and `_prepare_interruption_resume` durably preserve `provider_replay`, but `recent_continuity._resume_message()` currently reconstructs only `content` and normalized `reasoning_content`. The internal `_provider_replay` marker required by `LLMClient._project_provider_replay()` is lost.

Required result: preserve captured opaque replay into the recovered assistant representation, keep it identity-bound, and let the existing LLMClient provider whitelist decide whether it becomes a native wire field.

### CK1-R2 - attachment-bearing current user cannot be found by recent continuity

The current implementation locates the current user by comparing provider-wire `content` to raw `Message.content`. Attachment projection changes wire content by adding `[attachment_facts]`, causing `current_user_not_in_wire`.

Required result: identify/preserve the exact projected current-user message mechanically and retain attachment facts while placing an interrupted partial immediately before it.

## 8. Verification contract

CK1 closure requires deterministic coverage for:

- nearest completed model assistant + current human;
- exact interrupted partial + current human;
- provider-native replay retained for origin provider and not emitted to foreign provider;
- attachment-bearing current human + interrupted partial;
- provider-truncation factual runtime marker without imperative prose;
- S1 checkpoint becoming stale after later partial/human ingress;
- tool protocol already advanced => no continuity reorder;
- hard-restart open stream checkpoint and hash-verified full sidecar;
- receipts default OFF and selected raw evidence preservation when explicitly enabled;
- exact Evidence hydration remains available after representation shrink.

Correctness, exact recoverability, protocol pairing and absence of prompt-authority drift are gates. Cache-hit improvement is not a correctness gate.

## 9. Explicitly out of scope for CK1

- modifying the external research workspace or StateBraid;
- switching or concurrently loading local research models;
- making StateBraid/Cognitive cache policy the task controller;
- enabling a production WorkingStateCheckpoint producer;
- Durable SubAgent topology/ownership recovery (the next major phase after CK1);
- ExecutionWorkspace/capability-boundary redesign.

## 10. G4 deterministic verification matrix

The matrix is a contract map, not a requirement to duplicate every existing test in one file. Rows with existing focused tests remain authoritative; CK1 adds only missing interaction cases.

| Case | Expected precedence / invariant | Deterministic coverage |
| --- | --- | --- |
| raw recent history | nearest real model assistant + current genuine human form final suffix | `test_recent_continuity.py::test_resolved_previous_model_answer_is_rehydrated_for_adjacent_user_turn` |
| receipts OFF | raw tool results remain unchanged | `test_tool_working_set_projection.py::test_working_set_receipts_default_off` |
| receipts ON + selected raw | selected atomic protocol group stays raw; eligible unselected older recoverable group may become receipt | `test_selected_group_stays_raw_while_unselected_old_group_uses_receipt`, `test_multi_tool_selected_group_is_preserved_atomically` |
| S1 consumer | checkpoint is exact-boundary/provider/model scoped; model-authored state is provider-view only | `test_engine_projects_state_provider_only_and_preserves_selected_raw` |
| checkpoint mismatch | provider/model/boundary/resource mismatch fails closed to ordinary view | `test_malformed_or_mismatched_checkpoint_fails_closed_to_ordinary_view` |
| later human ingress | checkpoint becomes stale/cleared; historical state never self-authorizes | `test_new_human_task_removes_provider_state_without_mutating_checkpoint`, `test_later_persisted_message_clears_checkpoint_in_json_and_event_log` |
| provider truncation after S1 boundary | S1 becomes stale; exact partial + factual runtime marker owns adjacent recovery | `test_provider_truncation_takes_recovery_ownership_after_s1_boundary_advances` |
| hard restart | hash-verified full sidecar/native state outranks bounded event tail for adjacent recovery | `test_fork_pairing_disconnect.py::test_hard_restart_open_stream_checkpoint_is_first_class_recent_continuity`, `test_hard_restart_uses_full_sidecar_reasoning_not_bounded_event_tail` |
| provider-native replay | opaque replay survives capture/restart representation and only origin provider projects native fields | `test_interruption_resume_preserves_provider_native_replay_marker`, `test_interruption_replay_marker_keeps_existing_provider_projection_boundary` |
| attachments + interruption | current attachment-bearing projected wire stays exact and receives prior partial immediately before it | `test_attachment_bearing_current_user_keeps_interruption_continuity` |
| attachments + provider truncation | attachment facts remain, runtime provenance appends after them | `test_attachment_projection_survives_provider_truncation_runtime_fact` |
| current-turn factual capability suffix | factual provider-view suffix does not destroy current-human identity | `test_current_turn_capability_fact_does_not_hide_current_human_identity` |
| tool protocol advanced | assistant(tool_calls)->tool native order wins; no recent-continuity reorder | `test_tool_round_after_current_user_is_never_reordered` |
| failed tool + retry protocol | failed receipt and retry declaration/result remain paired; continuity does not move current human after protocol starts | `test_failure_then_retry_tool_protocol_is_never_reordered_by_recent_continuity` |
| Evidence exact recovery | representation shrink never removes exact already-acquired source recovery | Evidence enforce/read/search suites + receipt EvidenceRef assertions |
| cache facts | generic boundary remains `boundary_exact=False`; cache telemetry cannot decide task/fold semantics | cache-window + history cache-boundary tests |

The matrix gate is correctness and recoverability. A test may measure cache/prefill as telemetry, but cache-hit rate is not a pass/fail criterion for semantic continuity.
