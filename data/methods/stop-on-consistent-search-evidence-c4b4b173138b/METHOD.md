---
method_id: stop-on-consistent-search-evidence-c4b4b173138b
name: stop-on-consistent-search-evidence
description: For entity or project lookups, treat one well-targeted search as a candidate map. If multiple snippets already agree on the target’s identity and key attributes, fetch one high-signal source to fill remaining gaps, then stop. Re-query or re-fetch only when a new unknown appears, evidence conflicts, or a source is stale/truncated.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:d8f3d445-6e86-457c-bf7f-b10c1665f75e:4:7fcef129a0a58699cf19
evidence_refs: learning:learn:7fd4a42a8484
created_at: 2026-09-22T16:43:36.178661+00:00
updated_at: 2026-09-22T16:43:36.178661+00:00
---
## Trigger
Web research where search results already contain consistent snippets and URLs for the target entity, and further actions repeat the same queries or URLs without resolving a new unknown.

## Discriminator
At least two independent search snippets, or one fetched source, already answer the core question such as what the thing is, who made it, and its key mechanism, with no unresolved conflict.

## Short path
- Run one disambiguating search for the entity and inspect snippets and URLs.
- If snippets identify the entity and key attributes, fetch one detailed source that covers missing details.
- If the fetched source answers the user question, synthesize the answer and stop.
- If a gap remains, fetch one new non-duplicate source or run one targeted query for that specific gap.

## Stop conditions
- The core user question is answered by fetched or snippet evidence.
- Two independent sources agree on identity and key attributes.
- A repeated query or URL would not add a new unknown or resolve a conflict.

## Verification
- Check that each final claim maps to a snippet or fetched source.
- Check that no action repeats a prior query or URL unless a dynamic-change or conflict reason is recorded.
- Check that remaining gaps are explicitly identified rather than hidden by more broad searches.

## Counterexamples
- Search snippets conflict about which entity the acronym denotes.
- The user asks for live status, pricing, or recent changes that require fresh fetches.
- The first fetched source is paywalled, truncated, or lacks the needed detail.
