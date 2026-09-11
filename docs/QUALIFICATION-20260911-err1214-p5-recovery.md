# ERR1214 P5 interruption-recovery qualification — 2026-09-11

## Verdict

**QUALIFIED for convergence under zero-new-regression.**

Candidate: `6544ffdc533dcdca7eb34ed5f8d85f0ae01abbb5` (`fix(recovery): tolerate rebuildable journal drift`)

Base: `d15d900ed195451931465fc75ab1d6ec0c5a9b59` (`integration/convergence-20260911` at rebuild time)

Scope is intentionally narrow: interruption recovery may compare a recovery-only message identity that ignores lifecycle annotations rebuilt after `message.appended` and canonical cache-telemetry presentation. Stable provenance and the repository-wide audit/reconcile identity remain strict. This change is not a general history merger and does not repair already-entrenched divergent event branches.

## Root cause

Historical session `19adc0fa-3b3b-4f3d-93c1-15043f239368` showed `repair_failed reason=prefix_mismatch` although live Session state and EventStore replay represented the same pre-fork message history. The original forensic snapshot had 375 shared messages; 369 mismatches were metadata-only.

The mismatch is mechanically explained by post-append mutation order:

- `core/episode_history.py` attaches resolved/consumed/closed lifecycle refs and states after the original message append fact.
- `core/loop/engine_services/run_finalizer.py` can mark program decision messages `consumed` after their append event.
- `core/loop/build.py::_post_run_cache_health` can canonicalize the assistant cache-telemetry line and attach `cache_health` after append.
- `core/history.py` maintains cache-compaction lifecycle markers outside immutable message provenance.
- `core/loop/events.py::_append_message_event` records the append-time representation, so replay correctly lacks later in-memory annotations unless a dedicated event reconstructs them.

Therefore exact comparison of all metadata at recovery time made append-time journal truth incompatible with its own later-derived live representation.

## Qualified recovery identity

Recovery ignores only this closed set of rebuildable/lifecycle keys:

- `resolved_episode_ref`
- `episode_state`
- `consumed_tool_span_ref`
- `tool_span_state`
- `closed_tool_span_ref`
- `cache_health`
- `cache_compacted_for`
- `cache_compaction_scope`
- `consumed`

For assistant content, comparison also strips the deterministic `缓存命中率` telemetry presentation so append-time and post-run canonical forms compare as the same message.

The recovery identity still compares stable fields and all other metadata. In particular, attachment/provenance and queued-human-turn identity are not weakened. `event_log.reconcile.reconcile` remains strict and continues to report derived metadata drift for audit purposes.

## Historical replay boundary

The complete retained event log was replayed from `data/event_logs/19adc0fa-3b3b-4f3d-93c1-15043f239368/1.jsonl..7.jsonl` against the surviving Session JSON.

With the candidate recovery identity, live and replay are equal continuously for indices `0..496`, which covers the original 375-message failure window. The first remaining mismatch is index 497 and is deliberately **not** normalized:

- event seq 4541, `2026-09-08T19:38:50Z`: human ingress at index 497 begins with `GPT:已按推荐完整执行...`;
- that run continues through index 545 / event seq 4919 without a normal terminal settlement;
- event seq 4920, `2026-09-08T19:51:22Z`: another human ingress `继续` is appended again at index 497 from stale Session state;
- the contemporaneous recovery trace records `event_messages=546 vs memory_messages=497`, `prefix_mismatch`, `repair_failed`, then fallback to `open_stream_checkpoint`.

This proves the post-497 structure is an already-created historical fork downstream of the failed recovery. Two distinct human ingresses must remain unequal. P5 prevents the metadata-only mismatch from blocking tail repair before such a fork forms; it does not invent authority to merge an existing double branch.

## TDD and regression evidence

A detached `d4f00c4` baseline copied only the five new tests, without the production patch. Three positive recovery cases failed as required before the fix:

1. rebuildable runtime metadata drift;
2. finalizer `consumed` marker drift;
3. post-append cache telemetry content drift.

The two negative guards already passed on the baseline: stable provenance mismatch must still reject repair, and full reconciliation must still report metadata drift. The candidate turns all five green.

Further qualification on the fresh rebuild from `d15d900`:

- focused interruption recovery + reconcile + event replay: `35/35 PASS`;
- adjacent episode/span/cache/history set: `120/120 PASS`;
- fresh integration-ancestry set including recent continuity and interrupted-run persistence: `160/160 PASS`;
- changed-file Ruff: PASS;
- `py_compile`: PASS;
- staged security scan: PASS;
- `git diff --check`: PASS.

The fresh rebuild preserved the old candidate exactly: source patch SHA256 `3aad37b39bd5ca9bea72440588357590c5628aa5cc59cb0bf83c25d9216ddf4c`, stable patch-id `41a434ae9f2ed0f845d1d12bf887e0258fa0904e`; both modified files were byte-identical after applying onto `d15d900`.

## Committed-state gate and baseline waiver

Detached committed-state qualification at `6544ffd` produced:

- full Ruff gate: PASS;
- env-pin declaration scan: PASS, 521 test files;
- tier0 pytest: 100% PASS;
- full xdist pytest: 100% PASS, only existing skips/deprecation warnings;
- architecture guard report: PASS.

Repository Pyright is currently red on two lines outside this candidate:

- `src/llm_loop/feishu/rest.py:549` — `reportOptionalMemberAccess`;
- `src/llm_loop/feishu/rest.py:552` — `reportOptionalMemberAccess`.

This is accepted only as an explicit **baseline-identical, zero-new-regression waiver** for P5: the clean `d15d900` integration base and detached `6544ffd` candidate were run with the same Pyright environment and produce the exact same two diagnostics; `git diff d15d900..6544ffd` changes only `src/llm_loop/core/loop/events.py` and `tests/unit/test_interruption_recovery_r819.py`. P5 does not modify or suppress the Feishu diagnostics. That baseline debt remains a separate convergence item.

## Integration boundary

Qualified code commit changes exactly two files, `+196/-18`:

- `src/llm_loop/core/loop/events.py`
- `tests/unit/test_interruption_recovery_r819.py`

No provider prompt/schema, model configuration, remote state, runtime process, 8901 instance, or live service was changed for this P5 qualification. No remote push is performed by this workline; remote publication remains delegated to the LFL owner workflow.
