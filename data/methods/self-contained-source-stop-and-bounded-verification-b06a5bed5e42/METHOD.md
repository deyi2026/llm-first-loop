---
method_id: self-contained-source-stop-and-bounded-verification-b06a5bed5e42
name: self-contained-source-stop-and-bounded-verification
description: After a fetch returns a complete, directly relevant article, treat it as sufficient for read/summarize tasks. Do not broaden to web search or re-fetch the same URL unless the user asks for verification, the source is incomplete/stale, or a specific claim needs external corroboration. If verifying, identify the single uncertain claim, run at most a few narrow queries, and stop when results only corroborate entities or become irrelevant, labeling the claim single-source.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f66027f9-1a44-49f3-9d72-d41c37a3e3ee:5:eb11401ae9c08265401e
evidence_refs: learning:learn:d70868414be0
created_at: 2026-09-23T09:36:32.214707+00:00
updated_at: 2026-09-23T09:36:32.214707+00:00
---
## Trigger
A user provides a URL or asks to read/summarize it, and a fetch returns a complete short article that directly contains the requested content.

## Discriminator
The fetched result is marked success and already contains the full target text; no explicit request for external verification or updated data exists, and the same URL has just been fetched.

## Short path
- Fetch the URL once and check whether the returned text is complete and directly answers the task.
- If complete and no verification is requested, answer from that source and stop.
- If verification is requested or a claim is unusually important, list only the uncertain claim(s).
- Run one or two narrow queries for those claims, not broad topic searches.
- If queries only corroborate entities or return irrelevant/localized noise, stop and label the claim single-source.

## Stop conditions
- The fetched source already contains the full content needed for the user's request.
- The same URL was successfully fetched moments ago and no dynamic change or new parameters are needed.
- Verification queries no longer add new evidence for the specific uncertain claim.

## Verification
- Confirm the final answer is grounded in the fetched article.
- If verification was attempted, distinguish corroborated facts from single-source claims.
- Check that no duplicate fetch or repeated broad search was used after sufficiency.

## Counterexamples
- The user explicitly asks to verify, find the original source, compare sources, or update stale information.
- The fetched page is a stub, paywall, loading shell, or missing the target content.
- The claim is high-stakes or contradicted by other sources, requiring broader investigation.
