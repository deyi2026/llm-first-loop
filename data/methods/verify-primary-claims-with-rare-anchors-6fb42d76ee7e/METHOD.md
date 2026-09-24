---
method_id: verify-primary-claims-with-rare-anchors-6fb42d76ee7e
name: verify-primary-claims-with-rare-anchors
description: When a fetched primary artifact already contains the target content but some claims need corroboration, first extract rare identifiers from that artifact (exact entity names paired with distinctive numbers, versions, parameters, or benchmark values) and use those as narrow search/fetch anchors. Only fall back to broad topic search when no rare anchor exists or targeted searches fail. This reduces noisy enumeration caused by ambiguous common terms.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:9f0b8d02-5ee4-426e-bd9f-1eeca2436fb0:22:8f8990d177c3db7f9a78
evidence_refs: learning:learn:ef96179d3aa9
created_at: 2026-09-22T17:09:53.379540+00:00
updated_at: 2026-09-22T17:09:53.379540+00:00
---
## Trigger
A primary source has been fetched and the task requires summarizing plus verifying or supplementing claims, but the source contains multiple named entities or metrics that may be ambiguous.

## Discriminator
The primary artifact contains high-specificity anchors: rare entity names combined with distinctive numeric/parameter/benchmark facts that can be quoted or used as exact query terms.

## Short path
- Read the primary artifact and decide whether it already satisfies the user request.
- If verification is needed, list the claims to corroborate and extract rare anchors: exact entity names plus distinctive numbers/parameters/benchmarks.
- Search or fetch using quoted rare anchors, not broad topic phrases.
- Open the top source whose title/snippet matches the anchor and compare the specific fact.
- If no independent source matches after a few targeted attempts, label the claim as unverified rather than broadening to ambiguous terms.

## Stop conditions
- The primary artifact alone answers the request and no verification was requested.
- Each high-risk claim is either corroborated by a matching secondary source or explicitly marked unverified.
- Targeted anchor searches return no relevant source and further broad search would likely add noise.

## Verification
- Final summary attributes claims to the primary source or to a specific corroborating source.
- Numbers, versions, and entity names match between primary and secondary sources.
- Ambiguous common terms are disambiguated by rare anchors before being used as queries.

## Counterexamples
- The primary artifact is known to be stale or unreliable and the task requires independent verification from scratch.
- The artifact contains only common nouns and no rare identifiers, so anchor-based search is impossible.
- The user explicitly asks for broad discovery or exhaustive enumeration, not targeted corroboration.
- The search environment provides direct structured filters (repo, site, API) that are more reliable than text anchors.
