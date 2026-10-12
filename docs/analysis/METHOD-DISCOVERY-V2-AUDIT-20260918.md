# Method Discovery / Freshness Audit — 2026-09-18

## Scope

Read-only audit of the live Method inventory plus an isolated implementation/qualification of Discovery v2. No live Method lifecycle state was mutated during the audit because session `8264c548…` still holds an active run lease and is concurrently changing the service-control path.

## Live inventory snapshot

- Method assets: 182 total at snapshot time.
- Lifecycle: active=7, candidate=171, teacher=3, hold=1.
- LearningJournal: 96 jobs; saved=78, none=13, failed=2, started=1, queued=2; terminal candidate-save rate ≈83.9%.
- Durable `method.usage_observed`: 4 observations / 4 unique refs.
- Main imbalance: production of candidates is much faster than independent qualification/use.

## Discovery defect and qualification

Old MethodStore discovery was whitespace lexical AND over name/description/body. It omitted method_id/method_ref from the searchable surface. Consequences observed in real session history included:

- `a80acb208b99` -> MISS although `method:candidate-a80acb208b99` existed.
- `poc-a-b` -> MISS / wrong incidental hit although `method:poc-a-b-6dd78baba7e8` existed.
- broad mixed-language deploy query -> MISS although the active deploy Method existed.
- `navigate` returned incidental candidate mentions ahead of the active semantic-operation Method.

Discovery v2 changes only mechanical recall/ranking:

1. normalize hyphenated identifiers and CJK/alphanumeric terms;
2. search method_id + stable ref + name + description + body;
3. partial-term coverage replaces all-terms-must-match;
4. stable-id-like fragments receive strong identity weight;
5. lifecycle status is only a ranking prior, never an applicability verdict;
6. optional semantic RRF reuses the existing SemanticRetriever and a separate versioned Method embedding cache;
7. exact `method:<id>` hydration remains exact-only and never falls back semantically.

Real-query replay with 14 queries having an unambiguous expected Method:

| Metric | old | v2 |
|---|---:|---:|
| Hit@1 | 7/14 | 14/14 |
| Hit@5 | 8/14 | 14/14 |

The regression includes actual prior misses, not synthetic-only examples.

## Freshness defect

`method:lfl-mirror-qualified-worktree-33ba78f2f2e7` is active and was genuinely useful/qualified, but its body still says S5 manually rewrites `managed_service_deployment.json`. Current `docs/LFL-restart-guide.md` explicitly says **do not manually edit that record**; desired-deployment advancement now goes through `service_control publish` CAS + verify + restart. The Method has therefore become partially stale through code/control-plane evolution.

Discovery v2 adds an opt-in mechanical freshness contract:

- Method frontmatter may declare `freshness_refs` (workspace-relative files only).
- `record_qualification` snapshots SHA-256 of those exact files into the qualification receipt.
- discovery/exact hydration recomputes those bytes and reports only `current | changed | missing | unbaselined | not_tracked`.
- `task_applicability` remains `not_evaluated`; a hash change never lets the program decide that the Method is semantically invalid.
- model-visible `search_records` renders freshness state and exact changed refs.

The deploy Method currently has no `freshness_refs`; it should be moved to hold/revised only after the concurrent service-control run releases, then re-qualified against the new publish + two-phase restart contract. This audit deliberately does not mutate it mid-run.

## Next lifecycle work (not part of this isolated P0 change)

1. Add model-declared Method use receipt: `applied | adapted | not_applicable | rejected`; loading alone stays `application_proven=false`.
2. Turn later independent episodes into qualification opportunities, not automatic verdicts/promotions.
3. Reflection should see a small set of nearest existing Method cards and choose `none | new | refine(parent_ref)` to reduce the current ~84% new-candidate rate.
4. Introduce schema versioning/migration for legacy Method cards; do not mechanically rewrite historical semantic content.
5. Run held-out same-budget no-Method vs Method-discovery A/B after the consumption loop is observable.
