---
method_id: resume-inflight-via-red-executable-spec-045b0b447d6b
name: resume-inflight-via-red-executable-spec
description: On a 'continue' handoff onto an uncommitted work-in-progress tree, if an untracked/failing test file targets the same change label as the uncommitted diffs, run that suite first: RED output is a machine-checked enumeration of the remaining delta (missing wiring points per seam, plus API drift such as newly required kwargs). Do not front-load full planning-doc reads — Status headers can lag the working tree (this doc still said the phase was 'pending' while its mechanism was already in-tree) — and do not deep-read every diff hunk before letting failures say which hunks matter.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:2273:5b7c55c449dfba1133b3
evidence_refs: learning:learn:4eb41c32be41
created_at: 2026-10-02T08:29:15.250744+08:00
updated_at: 2026-10-02T08:29:15.250744+08:00
---
## Trigger
Resuming an in-flight task from a bare continuation instruction: git status shows uncommitted source changes plus an untracked or modified test file whose names or change labels (GAP/feature tag) match those uncommitted diffs.

## Discriminator
Knowledge-at-time: after diff --stat + untracked listing, an untracked test file shares the change tag with the modified sources (both labeled e.g. 'GAP-RESP-1 (C1)'), so the spec for remaining work is already written and executable; the suite can be run immediately and its failures enumerate exactly what is missing (visible: TypeError naming 'site_index' kwarg drift, 8 failures naming each seam).

## Short path
- git status + diff --stat: identify uncommitted surface and untracked test files; unknown = what remains to do.
- If labels match, run the untracked suite immediately, before reading the full plan doc; unknown = exact missing behaviors. RED output enumerates per-seam expectations and exposes harness/API drift.
- Read only the failing tests and the source seams they reference; treat harness-drift errors (e.g. missing newly required kwarg) as 'committed API moved, reconcile fixture against committed contract'.
- Implement just what the failures demand; rerun the suite.
- Gates: RED→GREEN, then focused neighbors + full regression; commit including the previously untracked test file.

## Stop conditions
- Spec suite is GREEN and regression/focused gates pass — stop; no further doc reading for confirmation of completion.
- No matching test file exists, or its labels target a different/abandoned change — red spec unusable; fall back to the plan doc's GAP list as the spec.
- RED output shows the suite itself is stale versus an intentionally changed committed API — fix the harness against the committed contract first before treating the suite as spec.

## Verification
- RED→GREEN on the previously failing suite with assertion semantics preserved (only fixture/harness fixes allowed).
- Focused-neighbor suites and full regression pass with true exit codes recorded.
- Previously untracked test file is included in the final commit, so the executable spec ships with the change.

## Counterexamples
- No executable test exists for the in-flight phase (design-only work, tests written after implementation): the plan doc is the only spec; RED-first yields nothing and doc reading is the correct next step.
- Untracked tests already pass GREEN or target an unrelated change (label mismatch): no red signal about remaining work; resume via provenance/plan instead of tests.
- Clean working tree: nothing in-flight to spec; the continuation problem is locating the resume point, not enumerating a delta.
