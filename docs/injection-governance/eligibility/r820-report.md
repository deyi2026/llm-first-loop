# R8.20 — Consumed Tool Span Lifecycle Closure

Status: **PASS**
Date: 2026-08-31
Surface: E04 `resolved_tool_calls_and_tool_results`

## Decision

Raw tool protocol has a shorter lifecycle than the whole user task. A complete `assistant(tool_calls) -> tool result` chain is necessary while the model is actively consuming it, but after a later real non-tool model assistant has consumed that evidence, the raw declaration/result payload is historical evidence rather than default working context.

R8.20 therefore separates **tool evidence consumed** from **whole episode resolved**. The runtime may retire only the raw tool protocol after durable indexing, while keeping the human instruction and consuming assistant answer visible whenever the overall task is still unresolved or legacy resolution cannot be proven.

## Root cause and real-data census

R8.5 correctly retired whole episodes only after durable resolution proof, but that left legacy/ambiguous turns fail-open in provider history even when their raw tool evidence had already been consumed. A read-only census of current session storage found:

- 6,808 assistant tool-call chains total; 6,799 protocol-complete;
- only 77 chains were already covered by whole-episode `resolved_episode_ref` retirement;
- 6,722 complete chains remained default-visible across 121 sessions, carrying about 17.72M raw tool/declaration characters;
- 5,379 of those had a later non-tool assistant before the next genuine human turn under a coarse scan.

After applying the stricter R8.20 consumer gate in a temporary EpisodeStore simulation (no session writes):

- **559 durable tool spans** across 80 sessions;
- **9,527 protocol messages / 7,656,075 chars** become provider-retirable;
- this is **36.61% of all current session message content** in the census;
- largest single-session reduction is about 743,664 chars.

Strict residual classification found no provably consumed chain that the new rule failed to mark. Remaining complete chains were either:

- **1,407** with no real model consumer, or
- program-only finals: **963** legacy program-feedback prefixes, **141** `answer_origin=program`, and **6** system-source program errors.

Those remain visible fail-closed.

## Lifecycle and durability

Implementation commit: `43a878f` (`fix(injection): retire consumed tool spans`).

`EpisodeStore` gains an append-only `tool_span` entry subtype and stable `toolspan:` identity. The span stores only visible retrieval material: the genuine human instruction, exact tool declarations/results, and the real model consumer. It does **not** claim that the whole task is resolved.

At the next human ingress, before the new user message is appended:

1. existing whole-episode backfill runs first;
2. R8.20 scans each prior human turn for exact complete tool groups;
3. a consumer must be a non-empty non-tool assistant that is not `answer_origin=program`, not system-source, and not a shared program-feedback prefix;
4. every declaration must have exact non-empty matching tool receipts; incomplete/orphan/current tool-followup chains are denied retirement;
5. the tool span is fsync-durably indexed;
6. only the assistant tool declaration and tool receipt messages receive `consumed_tool_span_ref` metadata;
7. provider projection and provider-visible char accounting omit those marked raw protocol messages;
8. the human instruction and consumer assistant remain visible unless the separate whole-episode lifecycle proves them resolved.

Index failure is fail-closed: no retirement metadata is written.

## Retrieval

`search_records(kind=episode)` reuses the existing EpisodeStore search/hydration surface. R8.20 extends search matching to the stored visible transcript, so a query using an old tool-result keyword can discover the `toolspan:` ref. Hydration remains bounded/paged. No queryless pointer or toolspan summary is automatically injected into prompt.

## Verification

Main-worktree verification:

- focused consumed-tool + existing resolved-episode suite: **25/25 PASS**;
- wider history/cache/1210/reference/core-loop suite: **244/244 PASS**;
- factory/introspection/search assembly: **65/65 PASS**;
- final combined smoke after search compatibility adjustment: **81/81 PASS**;
- changed production/tests pyright: **0 errors / 0 warnings**;
- canonical R0: **PASS**.

Detached clean fixed-point at `43a878f`:

- consumed/resolved focused: **25/25 PASS**;
- broader history/cache/1210/reference/factory/introspection/core-loop: **275/275 PASS**;
- pyright: **0/0**;
- canonical R0-1 through R0-4: **PASS**;
- frozen R0 reference remains `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`;
- checkout clean before and after standard read-only mounts.

The independently pre-existing `test_declaration_discrepancy_correction` assertion remains excluded where core-loop is included; it was already reproduced at parent `5be8425` and is unrelated R8.9 test debt. The current environment does not expose ruff/uv/uvx; no dependency was installed for this batch.

## Matrix result

E04 `PARTIAL -> DONE`. Matrix becomes **DONE=31 / KEEP=1 / PARTIAL=2 / OPEN=0**. Remaining PARTIAL surfaces are E05 historical reasoning and E06 durable constraints/decisions. Behavior canary / R9 remain not started.
