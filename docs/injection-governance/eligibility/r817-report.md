# R8.17 — Compact Runtime Observability Closure

Date: 2026-08-31

Status: **PASS**

## 1. Scope

R8.17 closes E10 `compact_archive_pointer_and_fold_status`.

R3 already established that compressed historical bodies, key facts and catalogs should be retrieved on demand rather than automatically replayed. E10 was the remaining control-plane leak: the compact path still narrated the fact of compression/folding itself into the provider request.

The corrected owner rule is:

> **Compression is a program operation. Its occurrence is observable; archived content is retrievable. Neither fact needs a per-compaction prompt message.**

## 2. Pre-change provider surface

`build_history_messages()` could create a dynamic compact appendix containing combinations of:

- `[上下文压缩] 已归档 N 条旧消息（约 M 字符）`;
- `ref=archive:search_archive`;
- `[中段折叠]` / `[渐进折叠]` with fold count K;
- `[缓存降级]` with head-keep/cache-rebuild explanation.

The appendix was program-origin STATUS material, `_dynamic=True`, and therefore became a role=user tail frame in provider view.

### Current-format reachability

A structured scan of current offending payload artifacts found one canonical metadata `compact_archive_appendix` provider message:

- role: `user`;
- chars: **224**;
- contents: one `[上下文压缩]` archive-count/ref frame plus one `[中段折叠]` fold-count/search frame.

Canonical session storage contained **0** messages with `injection_kind=compact_archive_appendix`. Literal compression-prefix matches in session files were tool outputs/source documents, not canonical compact metadata. This confirms the surface was a temporary request-view artifact rather than durable conversation truth.

## 3. Why dynamic discovery was redundant

The stable base system prompt already tells the model that overflow history is stored in the compression archive and that exact original content is recoverable with `search_archive`.

The compact runtime also already exposes independent structured state:

- `compact_view_stats`: `pre_chars`, `post_chars`, `drop_pct`, `archived_count`;
- provider middle-fold: `message.cache_compacted` event with message sequence/provider;
- degraded compression: cache-monitor state and transport metadata;
- durable content: ArchiveStore + `search_archive` / RecordSearcher.

Therefore N/M/K counts and repeated search pointers were not required to discover or preserve the capability. They were program-authored observability competing with the current task for attention.

## 4. Implementation

Implementation commit: `b2b18d9` (`fix(injection): retire compact runtime prompt status`).

### 4.1 Runtime compression status exits provider view

`history.py` no longer appends automatic:

- compression occurrence/count frame;
- archive search pointer;
- progressive/middle-fold note;
- cache-degrade note.

`APPEND_COMPRESSION` remains accepted for compatibility but no longer grants prompt authority.

Archive selection, pairing preservation, provider cache-compaction marking, archive writes and fold algorithms are unchanged.

### 4.2 Active decision compatibility stays separate

Legacy anchor-mode logic can still create a current-decision frame from independently derived active state. R8.17 does not conflate that with compression observability. If present, it is labeled `compact_active_state_appendix` rather than the retired `compact_archive_appendix`.

This keeps E10 narrow: removing runtime narration must not silently delete another surface whose eligibility belongs to active-state governance.

### 4.3 Stable system prompt is corrected

The base prompt previously said compression produced a `[上下文压缩]` marker + archive catalog + key facts. R3/R8.17 no longer do that, so the sentence was corrected to state only the durable truth:

- old messages are completely archived;
- information is not lost;
- exact original text can be retrieved with `search_archive`.

This is an intentional one-time stable-prefix byte change. The injection golden fingerprint changed only after its semantic slot checks (memory→tip, no retired hotcard/gate note) passed.

### 4.4 `run.compact` telemetry is repaired

The old action audit treated missing `[压缩关键事实]` / `[压缩推理结论]` prompt frames as a warning, even though R3 intentionally retired them.

Historical action-trace census:

- all `run.compact` rows: **7,635**;
- `warn`: **6,910**;
- `ok`: **725**;
- 2026-08-30/31: **192 warn / 10 ok**;
- all 192 recent warn rows contained the obsolete “关键事实帧缺失” condition.

R8.17 now records `run.compact / ok` with actual view statistics:

```text
view <pre>→<post> chars;
archived=<count>;
drop_pct=<pct>;
anchor_moved=<0|1>;
prompt_chars=0;
retrieval=search_archive;
stable_prefix_guard=pass
```

## 5. Preserved capability proof

Tests no longer use “a compression sentence appeared in provider output” as proof that compression worked. They use the actual state transitions:

- `compacted_out` proves budget compaction occurred;
- archive sink proves exact messages were stored;
- `compact_view_stats` proves pre/post/drop/archive counts;
- `cache_compacted_out` proves provider-fold marking;
- a real RecordSearcher/ArchiveStore integration test retrieves a unique archived original after compaction;
- the stable system prompt proves `search_archive` discovery remains available.

This makes the tests stronger: capability and UI narration are no longer the same assertion.

## 6. Verification

Before commit:

- focused R8.17: **24/24 PASS**;
- wider adjacent behavior suite: **348/348 PASS**;
- production/new-test pyright: **0 errors / 0 warnings / 0 informations**;
- `py_compile`: PASS;
- canonical R0-1..R0-4: **PASS**;
- frozen R0 hash: `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`.

Three legacy broad test files show 10 pyright findings when checked as a group. Detached parent `0b24482` reproduces the same 10 errors at the same locations; they are pre-existing test typing debt and were not repaired opportunistically.

Detached-clean fixed-point at `b2b18d9` repeated:

- clean before;
- production/new-test pyright 0/0;
- focused 24/24 PASS;
- wider 348/348 PASS;
- R0 four gates PASS;
- frozen hash byte-identical;
- clean after.

## 7. Matrix result

E10 moves `PARTIAL -> DONE`.

Matrix after R8.17:

- `DONE=28`
- `KEEP=1`
- `PARTIAL=5`
- `OPEN=0`

Remaining PARTIAL surfaces: E04, E05, E06, E09 and E32.

Behavior canary / R9 remain **not started**.
