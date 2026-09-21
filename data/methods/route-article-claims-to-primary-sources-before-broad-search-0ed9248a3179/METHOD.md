---
method_id: route-article-claims-to-primary-sources-before-broad-search-0ed9248a3179
name: route-article-claims-to-primary-sources-before-broad-search
description: When an article supplies named products, standards, or organizations and the task requires verification or factual extension, first extract the material claims and route each to its likely primary source (vendor docs/repo, standards site, foundation announcement). Use broad web search only when the primary source is missing, ambiguous, or contradicted. Stop once each material claim is verified or explicitly marked unverified.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f7469d7b-59d1-494b-955f-c9153320141e:15:d7eddb9e9f4e5a97be6d
evidence_refs: learning:learn:d9dcde1415a0
created_at: 2026-09-20T17:45:15.823673+00:00
updated_at: 2026-09-20T17:45:15.823673+00:00
---
## Trigger
User provides an article or claim set and the answer will verify, correct, or extend facts beyond the article's own narrative.

## Discriminator
The article already names specific entities (e.g., a product, file format, foundation) whose authoritative sources can be targeted, so generic web search is not the first narrowing step.

## Short path
- Extract material claims and named entities from the fetched article.
- Classify each claim by source type: product feature, standard governance, statistics, or opinion.
- Fetch the most direct primary source for the central claim, such as vendor docs/repo or the standard's official site, before generic search.
- If a claim lacks a primary source, run one targeted site/domain search; if still absent, mark it unverified.
- Check local workspace only when the task asks for applicability.
- Answer with verified facts separated from unverified article claims.

## Stop conditions
- All material claims needed for the answer are either verified from a primary source or explicitly marked unverified.
- The central claim's primary source has been obtained and no further discovery is needed.
- The user's request is satisfied without adding unrequested changes or actions.

## Verification
- Each material claim has a citation to a primary source or an unverified label.
- No near-identical broad searches are repeated after a primary source has been fetched.
- The final answer distinguishes article narrative from independently verified facts.

## Counterexamples
- The article itself is the authoritative announcement and the user only asks for a summary.
- The claim is subjective commentary or a prediction with no external primary source.
- The article names no identifiable product, standard, or organization, so broad discovery is necessary.
- The user explicitly requires multiple independent corroborations, not just primary-source verification.
