---
method_id: canonical-source-first-when-paper-identifiers-known-fc63b2749443
name: canonical-source-first-when-paper-identifiers-known
description: When the user requests an original paper/source document and the secondary source contains specific technical identifiers too specialized to be SEO-spammed, go directly to the canonical academic source's own search interface (e.g., arxiv.org/search/) before falling back to general web search.
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:4:6380a6b972c4f827fe81
evidence_refs: learning:learn:5021459b81cd
created_at: 2026-09-19T15:46:29.881264+00:00
updated_at: 2026-09-19T15:46:29.881264+00:00
---
## Trigger
User requests an original paper, source document, or technical report AND a secondary source (news article, blog) provides specific technical identifiers AND the content domain has a well-known canonical open source (arXiv for ML/AI, NeurIPS/OpenReview proceedings, HuggingFace for model weights, GitHub for code)

## Discriminator
At step 3 the model already held, from the article just read, multiple highly specific identifiers (versioned model name 'DeepSeek-V4.1-Flash', novel mechanism names 'CSA2' / 'Causal-Encoder-Decoder' / 'FP4 KV cache', exact numeric claim '890 bytes per token global KV cache'). The user's request was explicitly '论文原文' (the original paper). For ML/AI papers the canonical open archive is arXiv. These three together—user wants the paper, identifiers are paper-grade specific, canonical source is known—should have triggered a direct query to arxiv.org/search/ instead of generic bing search.

## Short path
- Identify 1–2 uniquely distinctive identifiers from the secondary source (exact title fragment, mechanism names, signature numeric claim)
- Query the canonical source's own search interface directly (e.g., arxiv.org/search/?searchtype=all&query=<unique term>)
- Match the returned title/abstract against the secondary source's specific claims (model size, KV size, mechanism names) to confirm the right paper
- Stop once the abstract aligns with the secondary source

## Stop conditions
- Paper retrieved and its title/abstract contains the specific technical identifiers extracted from the secondary source (e.g., 552B MoE, 890 bytes/token, CSA2, causal-encoder-decoder)
- Secondary source already contains a direct URL to the paper—follow the link instead of searching

## Verification
- Title string match (or close substring match) between secondary source headline and arXiv result
- At least one uniquely specific technical claim from secondary source appears in the arXiv abstract (numeric claim, mechanism name, architecture detail)
- Authors/team affiliation consistent between secondary source claim and arXiv listing

## Counterexamples
- Secondary source already includes the direct paper URL—follow the link, do not search
- Content is not on a canonical open archive (paywalled journal article, corporate-only whitepaper, book chapter not on arXiv)—general web search is the right primary tool
- Secondary source uses only generic marketing language with no specific technical identifiers (no mechanism names, no numeric claims, only the product brand)—general search first to disambiguate which paper or release is meant
- Terms are paraphrased descriptions rather than actual paper terminology (article says 'new sparse attention method' without naming it)—canonical search will not help because the discriminating terms are absent
- The canonical source's own search returns too many noise results because the term is generic even if 'specific-looking' (e.g., a model name shared with unrelated projects)—add a co-occurring unique numeric or mechanism qualifier before committing
