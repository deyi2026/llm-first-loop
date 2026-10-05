---
method_id: verify-load-bearing-review-claims-at-cited-anchors-before-adoption-294b603ef67b
name: verify-load-bearing-review-claims-at-cited-anchors-before-adoption
description: An external analysis/review whose conclusions would correct or overturn your prior load-bearing decisions arrives with precise anchors (file:line, config keys, version strings). Treat it as a claim list, not evidence: batch-read each cited primary-source range, classify every load-bearing claim confirmed/refuted/partial against what the source actually says, adopt only verified claims, and separately record reviewer errors and omissions surfaced incidentally.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4dca8b27-b04e-4081-8690-f0d58c85ec34:132:c0330ee3d19f724ae926
evidence_refs: learning:learn:14037fadaf41
created_at: 2026-10-05T22:40:55.564495+08:00
updated_at: 2026-10-05T22:40:55.564495+08:00
---
## Trigger
An external review/analysis (tool, another model, human) delivers conclusions that would change your prior design or accept/reject decisions, and its assertions carry concrete, locally readable anchors (file:line citations, env values, version numbers) — e.g. a large review with a dozen file:line claims about your own design doc.

## Discriminator
Already observable at decision time, before any tool call: (a) each of the review's claims is load-bearing (it would alter the design/acceptance), and (b) each claim is pinned to a verifiable primary source readable now. These two facts collapse 'wholesale trust vs full re-audit' into O(claims) targeted reads.

## Short path
- Enumerate the review's load-bearing claims; adopt none yet
- Batch-read the cited ranges of each anchored file directly (parallel reads)
- Classify each claim confirmed / refuted / partially-correct against what the source actually says
- For partial cases, test whether the reviewer's conclusion survives via different evidence than the one cited
- Record reviewer-side factual errors and omissions discovered during verification as explicit findings
- Fold the classifications, each with your own re-verified primary-source citation, into the deliverable and reply

## Stop conditions
- Every load-bearing claim has a classification backed by a direct read of its cited range
- The deliverable incorporates all classifications; no further verification of stylistic or non-load-bearing remarks

## Verification
- Each adopted claim in the final answer cites a re-verified primary source, not the review itself
- Discrepancies between review and source are explicitly listed, including reviewer-side errors and omissions
- Claims whose anchors are unreadable or absent are marked unverified, never silently adopted

## Counterexamples
- Review is purely stylistic/preference feedback with no factual anchors — per-claim verification wastes budget
- Anchors reference artifacts you cannot access (external systems, other runs) — mark unverified instead of guessing
- Degenerate review output (polished shell, zero substantive issues) — different failure mode; use the review-contract execution method instead
- The cited source is already fully read in this session with content in context — verify from context; re-reading is redundant
- One disputed claim among many trivial ones — verify only the load-bearing claim, do not audit everything
