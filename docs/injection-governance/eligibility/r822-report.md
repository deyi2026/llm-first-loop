# R8.22 — Historical Decisions and Constraints On Demand

Status: **PASS**
Date: 2026-08-31
Surface: E06 `durable_effective_constraints_and_decisions`

## Decision

Conversational history does not become permanent prompt authority merely because a user once used standing-rule wording such as “以后”, “始终”, “always”, or “never”. The current human instruction remains exact inline, but once that turn is durably resolved its source text becomes retrievable history rather than default future working context.

Likewise, extracted `decision` and `convention` memories are searchable state, not generic automatic prompt material. R8.22 deliberately avoids guessing semantic supersession between arbitrary natural-language rules. Truly always-on rules must live in an explicit stable rule/config/control-plane source.

## Root cause evidence

The former resolved-episode guard matched standing-rule words and granted the entire historical user message provider visibility. A read-only census found:

- 114 standing-marker user messages across 23 sessions;
- 409,422 source characters total;
- median length 1,124 chars;
- p90 length 12,223 chars;
- maximum single source message 54,933 chars;
- 13 matched messages exceeded 10,000 chars.

This proves lexical standing-language detection was too coarse to be a prompt-eligibility authority boundary.

MemoryStore also contained 261 `decision` + `convention` entries / 37,645 chars, all persisted with legacy `inject_policy=auto`. Of those, 103 entries were already versioned with 452 historical versions, proving the store already had current-version plus version-history durability without requiring every decision to remain prompt-visible.

New-format memory snapshot evidence also showed decisions/conventions mixed with old progress, model-switch state and historical observations in the same current-turn background. Current-turn retrieval identity therefore does not by itself prove current-task necessity.

## Runtime rule

Implementation commit: `efdb5aa` (`fix(injection): make historical decisions on demand`).

1. Current human input is unchanged and remains protected by E01.
2. A durably resolved historical user source is removed from default provider history even if it matched standing-rule language.
3. Legacy `resolved_episode_keep_provider=true` cannot resurrect a resolved source turn.
4. Exact resolved source text remains available through EpisodeStore hydration.
5. `build_memory_messages` excludes memory types `decision` and `convention` from automatic projection, including legacy entries whose stored policy is still `auto`.
6. Explicit `search_records(kind=memory)` still finds these entries, including exact `memory:<id>` retrieval.
7. Newly extracted `decision` and `convention` entries persist with `inject_policy=recall_only`; `fact` and `procedure` behavior is unchanged by this batch.
8. MemoryStore current version and `version_history` remain the durable supersession record; no semantic overwrite inference was added to prompt admission.

## Verification

Main-worktree gates:

- focused E06/resolved/memory: **29/29 PASS**;
- wider resolved/consumed/memory/reference/history/1210/fingerprint: **182/182 PASS**;
- core-loop/factory adjacent: **39/39 PASS** excluding one independently pre-existing stale declaration-reminder assertion;
- changed pyright: **0 errors / 0 warnings**;
- py_compile: **PASS**;
- canonical R0-1 through R0-4: **PASS**.

Detached clean fixed-point at `efdb5aa`:

- combined suite: **221/221 PASS**;
- changed pyright: **0/0**;
- py_compile: **PASS**;
- canonical R0: **PASS**;
- checkout clean before and after.

## Matrix result

E06 `PARTIAL -> DONE`. Matrix becomes **DONE=33 / KEEP=1 / PARTIAL=0 / OPEN=0**.

This green matrix does **not** authorize behavior canary or R9 by itself. The next gate is a strict re-audit of all 34 surfaces under the stronger owner rule: program state and historical information must not self-inject merely because older lifecycle rules called them current-turn eligible.
