---
method_id: treat-polluted-retrieval-as-source-class-verdict-7274d4444032
name: treat-polluted-retrieval-as-source-class-verdict
description: When a query returns systematically off-target results for a clearly-phrased intent, treat it as a verdict on the (channel, query-style) pairing, not on the question. Switch to the source class matched to the question's genre (research/technical unknowns -> scholarly or technical indexes; system-specific unknowns -> internal record corpus); never re-issue a pairing that already returned pollution. If the matched class also fails within budget, bound the claim honestly (label content as prior) and reallocate effort to the unknowns the already-successful corpus answers.
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:28:8edd51edeff2c132f08f
evidence_refs: learning:learn:cd838ee3b798
created_at: 2026-09-20T05:05:21.560596+00:00
updated_at: 2026-09-20T05:05:21.560596+00:00
---
## Trigger
A retrieval query on a niche technical/system-specific question returns a full page of consumer-grade or off-target results, and at least one alternative source class matched to the question's genre exists (scholarly index, internal record corpus).

## Discriminator
Knowledge-at-time, visible before the retry round: the first two broad web queries both returned 100% off-target consumer content (browser products, dictionaries, generic LLM intros) while the same-intent internal-record query hit 5/5 verified relevant records. That contrast already showed (a) the generic-web pairing fails for this niche unknown and (b) the system-specific half of the question was answerable from in-hand records — yet a third broad web query in the same style was still issued in the retry round and again returned junk the final answer never used.

## Short path
- Split the question into its unknowns and assign each a genre-matched source class up front; issue one precise query per class.
- Read the hit profile: if a channel returns systematically off-target results for a clear intent, record a source-class verdict — do not refine-and-resend the same pairing a third time.
- Give the matched-channel query at most one refinement; if hits are on-topic, read one or two key items to confirm the direction exists.
- If external evidence stays thin, compose the answer with explicit evidence labels (retrieved sources vs training prior) instead of buying more searches, grounding the system-specific half in the already-hit corpus.

## Stop conditions
- Every unknown has either a grounded authoritative source or an explicit honest bound ('labeled as prior, not retrieved') — stop searching once this holds.
- A (channel, query-style) pairing has returned systematic pollution — that pairing is retired for the rest of the episode.

## Verification
- Audit the trace: no pairing that returned off-target results was re-issued later in the episode.
- Final answer's evidence labels match source reality: on-topic retrieved items cited as retrieved; everything else labeled as training prior.
- On-topic hit counts recorded per query; channel switches justified by the recorded verdict, not by wording tweaks alone.

## Counterexamples
- First query returns partially relevant results (some on-topic hits): that is a query-refinement signal within the same channel, not a source-class verdict.
- Question is consumer/product-facing (e.g., 'which browser is fastest'): generic web search IS the matched class; pollution there points to query wording, not the channel.
- Single empty or failed call without a pattern (e.g., a required param accidentally dropped): fix the call and retry once before judging the channel — one mechanical slip is not systematic pollution.
