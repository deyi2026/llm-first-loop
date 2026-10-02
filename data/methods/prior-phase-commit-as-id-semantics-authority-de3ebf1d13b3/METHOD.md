---
method_id: prior-phase-commit-as-id-semantics-authority-de3ebf1d13b3
name: prior-phase-commit-as-id-semantics-authority
description: When a phased task must join or correlate with ids/seams introduced by the just-landed sibling phase, and current source mixes multiple same-named id families, the sibling commit visible in git log is the identity authority: its subject scopes the artifact family and its diff shows where the ids are minted and threaded. Read that one commit before wide or overlapping source reads; keyword greps over entangled current source cannot say which id family the plan means.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:1375:697594d4db5dd0abcb41
evidence_refs: learning:learn:ed01974c68f1
created_at: 2026-10-02T03:05:22.759908+08:00
updated_at: 2026-10-02T03:05:22.759908+08:00
---
## Trigger
Implementing phase N of a named multi-phase plan where the work must add correlation keys joining to ids or seams introduced by the just-landed phase N-1, and the current source contains multiple same-named id families (e.g. two different 'attempt_id' concepts from different subsystems) that keyword greps cannot disentangle.

## Discriminator
Knowledge-at-time: the first state-anchoring command (git log) already displayed the prior phase's feature commit as HEAD, and its subject explicitly scoped the artifact family whose ids are the join targets ('prepared facts on transport attempts'); that commit's message+diff define id names, type/nullability, mint point, and seam ownership — an authoritative identity answer one command away, available before any wide source read.

## Short path
- Anchor once (git log/status); check whether HEAD or a recent commit is the prior phase this task extends — its subject should match the plan's previous gap/phase item.
- Unknown: which id space does the required join key belong to? Run `git show <prior-phase-commit>` (message, --stat, key hunks); this yields the id names, nullability, mint point, and seam ownership in one hop.
- Unknown: is there a read path for that id? Grep only the exact field/accessor names surfaced by the diff, restricted to the module the diff names.
- Read a narrow line range around the mint/accessor point to confirm join semantics and the unavailable-binding fallback; do not re-read large overlapping windows of the same file.
- Write the RED payload-shape test first, then implement the additive accessor plus payload keys, and run the focused gate before full regression.

## Stop conditions
- The prior-phase commit's message+diff has answered the identity question (which id family, where minted, how threaded) — stop gathering provenance and start the RED test.
- A red test pins the new correlation keys plus the empty/fail-open behavior when binding is unavailable; exploration is finished.
- The prior-phase commit is absent, docs-only, or unrelated to the target artifact — abandon this path and fall back to definition-surface plus full-callsite discovery.

## Verification
- RED→GREEN tests assert the new join keys appear in the target payload and that adjacent payloads' shapes stay frozen where timing structurally excludes the id.
- Reparsed durable records (e.g. settlement JSONL) show the joined ids equal the ids minted at the site the commit diff identified.
- Lint/type-check/full-test exit codes and diagnostic counts compare delta-0 against the HEAD baseline, so the change does not mask pre-existing errors.

## Counterexamples
- No recent or git-visible sibling commit exists (feature predates history or lives outside git): commit archaeology cannot answer; use current-source definition + full-callsite discovery instead.
- The question is about current runtime behavior or lifecycle, not 'which id family did the prior phase introduce': running code and current source are the authority; the commit may be stale.
- The prior-phase commit is docs/changelog only, with no id-threading hunks: its diff cannot resolve identity; go read the code.
- Source has exactly one unambiguous id definition and no same-named decoy families: a single targeted read is already the shortest path; the extra commit hop adds cost without narrowing anything.
